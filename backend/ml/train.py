"""Walk-forward training for the CatBoost earnings model.

Run from the backend directory:

    python -m ml.train --model earnings_catboost

Loads `historical_earnings_events`, builds features for every event with
≥4 prior events for that symbol, runs walk-forward CV in 6-month windows,
trains a final model on all trainable data, persists artifact + metrics.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from config import PROJECT_ROOT
from database import SessionLocal, init_db
from ml.baseline import ticker_median_baseline
from ml.earnings_catboost import (
    TrainingMetadata,
    load_model,
    make_model,
    save_model,
    to_pool,
)
from ml.features import (
    FEATURE_NAMES,
    PriorEarning,
    build_features,
    feature_matrix,
    sector_for,
)
from ml.sector_map import SECTOR_ETFS, VIX_SYMBOL
from models.historical_earnings_event import HistoricalEarningsEvent
from services.alpaca_client import get_daily_bars_history

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("train")


def _bars_to_series(bars) -> pd.Series:
    """Alpaca bars come back tz-aware (UTC). We normalize each timestamp to
    a tz-naive midnight Timestamp via `.date() → Timestamp` so the resulting
    DatetimeIndex compares cleanly with tz-naive `pd.Timestamp(date)`."""
    if not bars:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    closes = {pd.Timestamp(b.timestamp.date()): float(b.close) for b in bars}
    return pd.Series(closes).sort_index()


def _load_all_events() -> list[HistoricalEarningsEvent]:
    with SessionLocal() as session:
        return session.execute(
            select(HistoricalEarningsEvent).order_by(HistoricalEarningsEvent.earnings_date)
        ).scalars().all()


def _pre_fetch_bar_series(symbols: set[str]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for sym in sorted(symbols):
        bars = get_daily_bars_history(sym, years_back=5)
        out[sym] = _bars_to_series(bars)
    return out


def build_dataset(
    events: list[HistoricalEarningsEvent],
) -> tuple[pd.DataFrame, list[float], list[date], list[str]]:
    """Build (X, y, dates, symbols) for all trainable events.

    Trainable = symbol has ≥4 prior earnings strictly before the event date
    AND price/sector/VIX series are available for the lookback window.
    """
    needed_syms: set[str] = {e.symbol for e in events}
    sector_etfs: set[str] = set(SECTOR_ETFS) | {VIX_SYMBOL}
    bar_series: dict[str, pd.Series] = _pre_fetch_bar_series(needed_syms | sector_etfs)

    by_symbol: dict[str, list[HistoricalEarningsEvent]] = defaultdict(list)
    for e in events:
        by_symbol[e.symbol].append(e)
    for sym in by_symbol:
        by_symbol[sym].sort(key=lambda x: x.earnings_date)

    rows: list[dict[str, Any]] = []
    targets: list[float] = []
    dates: list[date] = []
    symbols: list[str] = []
    skipped_no_history = 0
    skipped_no_bars = 0

    for ev in events:
        symbol_closes = bar_series.get(ev.symbol, pd.Series(dtype=float))
        if symbol_closes.empty:
            skipped_no_bars += 1
            continue
        sector = sector_for(ev.symbol)
        sector_closes = bar_series.get(sector, pd.Series(dtype=float)) if sector else None
        vix_closes = bar_series.get(VIX_SYMBOL, pd.Series(dtype=float))

        # Trim each series to be strictly before this event (the feature builder
        # also enforces this; we trim defensively so the assertion never fires).
        cutoff = pd.Timestamp(ev.earnings_date)
        symbol_closes_trim = symbol_closes[symbol_closes.index < cutoff]
        sector_closes_trim = sector_closes[sector_closes.index < cutoff] if sector_closes is not None else None
        vix_closes_trim = vix_closes[vix_closes.index < cutoff] if vix_closes is not None else pd.Series(dtype=float)

        priors = [
            PriorEarning(
                earnings_date=p.earnings_date,
                abs_move_pct=p.abs_move_pct,
                eps_surprise_pct=p.eps_surprise_pct,
            )
            for p in by_symbol[ev.symbol]
            if p.earnings_date < ev.earnings_date
        ]
        feats = build_features(
            symbol=ev.symbol,
            event_date=ev.earnings_date,
            bmo_amc=ev.bmo_amc,
            symbol_closes=symbol_closes_trim,
            sector_closes=sector_closes_trim,
            vix_closes=vix_closes_trim,
            prior_earnings=priors,
        )
        if feats is None:
            skipped_no_history += 1
            continue
        rows.append(feats)
        targets.append(ev.abs_move_pct)
        dates.append(ev.earnings_date)
        symbols.append(ev.symbol)

    log.info(
        "build_dataset: %d trainable / %d total (%d skipped insufficient history, %d skipped no bars)",
        len(rows), len(events), skipped_no_history, skipped_no_bars,
    )
    if not rows:
        return pd.DataFrame(columns=FEATURE_NAMES), [], [], []
    X, _ = feature_matrix(rows)
    return X, targets, dates, symbols


def walk_forward_metrics(
    X: pd.DataFrame, y: list[float], dates: list[date], symbols: list[str],
    train_months: int = 24, val_months: int = 6, stride_months: int = 6,
) -> dict[str, Any]:
    """Walk-forward CV. Reports per-fold and aggregate MAE/RMSE + per-ticker breakdown."""
    if len(y) < 30:
        return {
            "folds": [],
            "aggregate": {},
            "per_ticker": [],
            "warning": f"too few events ({len(y)}) for meaningful walk-forward CV",
        }

    df = X.copy()
    df["__y"] = y
    df["__date"] = dates
    df["__sym"] = symbols
    df = df.sort_values("__date").reset_index(drop=True)

    earliest = df["__date"].min()
    latest = df["__date"].max()
    fold_start = earliest + timedelta(days=int(train_months * 30.4))

    folds = []
    pred_rows: list[dict[str, Any]] = []
    while fold_start + timedelta(days=int(val_months * 30.4)) <= latest:
        train_cutoff = fold_start
        val_end = fold_start + timedelta(days=int(val_months * 30.4))
        train_mask = df["__date"] < train_cutoff
        val_mask = (df["__date"] >= train_cutoff) & (df["__date"] < val_end)
        if val_mask.sum() == 0 or train_mask.sum() < 20:
            fold_start += timedelta(days=int(stride_months * 30.4))
            continue

        X_train = df.loc[train_mask, FEATURE_NAMES]
        y_train = df.loc[train_mask, "__y"].tolist()
        sym_train = df.loc[train_mask, "__sym"].tolist()
        X_val = df.loc[val_mask, FEATURE_NAMES]
        y_val = df.loc[val_mask, "__y"].tolist()
        sym_val = df.loc[val_mask, "__sym"].tolist()
        date_val = df.loc[val_mask, "__date"].tolist()

        model = make_model()
        model.fit(to_pool(X_train, y_train))
        pred = model.predict(to_pool(X_val))

        baseline = ticker_median_baseline(sym_train, y_train, sym_val)

        for d, s, y_t, p, b in zip(date_val, sym_val, y_val, pred, baseline):
            pred_rows.append({
                "earnings_date": d, "symbol": s, "actual": y_t,
                "model_pred": float(p), "baseline_pred": float(b),
            })
        folds.append({
            "train_cutoff": train_cutoff.isoformat(),
            "val_end": val_end.isoformat(),
            "n_train": int(train_mask.sum()),
            "n_val": int(val_mask.sum()),
            "model_mae": float(np.mean(np.abs(np.array(y_val) - pred))),
            "baseline_mae": float(np.mean(np.abs(np.array(y_val) - np.array(baseline)))),
        })
        fold_start += timedelta(days=int(stride_months * 30.4))

    if not pred_rows:
        return {"folds": [], "aggregate": {}, "per_ticker": [], "warning": "no validation folds produced predictions"}

    pred_df = pd.DataFrame(pred_rows)
    err_model = np.abs(pred_df["actual"] - pred_df["model_pred"])
    err_baseline = np.abs(pred_df["actual"] - pred_df["baseline_pred"])
    aggregate = {
        "model_mae": float(err_model.mean()),
        "model_rmse": float(np.sqrt(((pred_df["actual"] - pred_df["model_pred"]) ** 2).mean())),
        "baseline_mae": float(err_baseline.mean()),
        "improvement": float(err_baseline.mean() - err_model.mean()),
        "n_validation_events": int(len(pred_df)),
        # Outlier conditional MAE — a model that just predicts the mean has
        # great overall MAE but terrible MAE on outsized actual moves. We
        # surface this so we don't fool ourselves.
        "mae_outlier_actuals": float(err_model[pred_df["actual"] > 10].mean()) if (pred_df["actual"] > 10).any() else None,
        "baseline_mae_outlier_actuals": float(err_baseline[pred_df["actual"] > 10].mean()) if (pred_df["actual"] > 10).any() else None,
    }
    per_ticker = []
    for sym, grp in pred_df.groupby("symbol"):
        m_mae = float(np.abs(grp["actual"] - grp["model_pred"]).mean())
        b_mae = float(np.abs(grp["actual"] - grp["baseline_pred"]).mean())
        per_ticker.append({
            "symbol": sym, "n_validation_events": int(len(grp)),
            "model_mae": m_mae, "baseline_mae": b_mae,
            "improvement": b_mae - m_mae,
        })
    per_ticker.sort(key=lambda r: r["improvement"], reverse=True)
    return {
        "folds": folds,
        "aggregate": aggregate,
        "per_ticker": per_ticker,
        "_oos_predictions": pred_rows,  # consumed by _write_catboost_oos_predictions
    }


def _write_catboost_oos_predictions(metrics: dict) -> None:
    """Persist per-fold OOS predictions for the ensemble layer (Phase 7.8)."""
    records = metrics.get("_oos_predictions") or []
    if not records:
        log.warning("no CatBoost OOS predictions to write (likely 0 trainable events)")
        return
    out_path = PROJECT_ROOT / "data" / "models" / "earnings_catboost_oos_predictions.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)[["earnings_date", "symbol", "model_pred"]].rename(
        columns={"model_pred": "predicted_abs_move_pct"}
    )
    df["earnings_date"] = pd.to_datetime(df["earnings_date"])
    df.to_parquet(out_path, index=False)
    log.info("wrote %d CatBoost OOS predictions to %s", len(df), out_path.name)
    # Don't leak the giant list into the on-disk metrics JSON.
    metrics.pop("_oos_predictions", None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="earnings_catboost",
        choices=["earnings_catboost", "lstm_vol", "mlp_trend", "ensemble"],
    )
    args = parser.parse_args()
    init_db()

    if args.model == "lstm_vol":
        from ml.train_lstm import run_lstm_training
        run_lstm_training()
        return
    if args.model == "mlp_trend":
        from ml.train_mlp import run_mlp_training
        run_mlp_training()
        return
    if args.model == "ensemble":
        from ml.train_ensemble import run_ensemble_training
        run_ensemble_training()
        return

    events = _load_all_events()
    log.info("loaded %d historical earnings events", len(events))

    X, y, dates, symbols = build_dataset(events)
    metrics = walk_forward_metrics(X, y, dates, symbols)
    # Phase 7.8 stacking: persist OOS predictions for the ensemble layer.
    _write_catboost_oos_predictions(metrics)

    if len(y) > 0:
        # Final model trained on all trainable data.
        final = make_model()
        final.fit(to_pool(X, y))
    else:
        final = make_model()
        log.warning("no trainable events — saving an untrained model as a stub")

    note = ""
    if len(y) == 0:
        note = "Insufficient data: zero events met the ≥4-prior-earnings requirement. Free-tier Finnhub historical earnings is limited; recommend wiring yfinance for historical dates."
    elif len(y) < 500:
        note = f"Low-confidence model: trained on {len(y)} events (< 500 threshold)."

    save_model(
        final,
        TrainingMetadata(
            n_total_events=len(events),
            n_trainable_events=len(y),
            n_features=len(FEATURE_NAMES),
            notes=note,
        ),
        metrics,
    )
    log.info("training complete. metrics + model artifact written.")
    if metrics.get("aggregate"):
        log.info("aggregate: %s", metrics["aggregate"])


if __name__ == "__main__":
    main()
