"""Walk-forward CV for the MLP trend model.

Same scaffold as Phase 7 LSTM. Plus per-fold disagreement metrics:
when MLP and conditional-momentum baseline disagree on direction, who
was right more often? If MLP wins on disagreements, it's doing real work.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

from config import settings
from ml.baselines_trend import ConditionalMomentumBaseline, fifty_fifty_predict
from ml.mlp_trend import (
    MlpTrendMetadata,
    predict_proba_up,
    save_mlp,
    train_mlp,
)
from ml.trend_features import (
    FEATURE_NAMES,
    TickerTrendData,
    build_ticker_trend_dataframe,
    iter_trend_windows,
    sector_for,
)
from services.alpaca_client import get_daily_bars_history

log = logging.getLogger("train_mlp")


def _bars_to_ohlcv(bars) -> dict[str, pd.Series] | None:
    if not bars:
        return None
    closes, volumes = {}, {}
    for b in bars:
        d = pd.Timestamp(b.timestamp.date())
        closes[d] = float(b.close)
        volumes[d] = float(b.volume or 0)
    return {
        "closes": pd.Series(closes).sort_index(),
        "volumes": pd.Series(volumes).sort_index(),
    }


def _load_ticker_data(symbols: list[str]) -> dict[str, TickerTrendData]:
    out: dict[str, TickerTrendData] = {}
    # Pre-cache sector ETF bars once (shared across all tickers in that sector).
    sector_cache: dict[str, pd.Series] = {}

    for sym in symbols:
        ohlcv = _bars_to_ohlcv(get_daily_bars_history(sym, years_back=5))
        if ohlcv is None:
            log.warning("no bars for %s; skipping", sym)
            continue
        sector_etf = sector_for(sym)
        sector_closes = None
        if sector_etf is not None:
            if sector_etf not in sector_cache:
                sec_ohlcv = _bars_to_ohlcv(get_daily_bars_history(sector_etf, years_back=5))
                sector_cache[sector_etf] = sec_ohlcv["closes"] if sec_ohlcv else pd.Series(dtype=float)
            sector_closes = sector_cache[sector_etf] if not sector_cache[sector_etf].empty else None
        td = build_ticker_trend_dataframe(
            symbol=sym,
            closes=ohlcv["closes"],
            volumes=ohlcv["volumes"],
            sector_closes=sector_closes,
        )
        out[sym] = td
    return out


def _flatten_windows(ticker_data: dict[str, TickerTrendData]) -> list:
    rows: list = []
    for sym, td in ticker_data.items():
        for w in iter_trend_windows(td):
            rows.append(w)
    rows.sort(key=lambda w: w.prediction_date)
    return rows


def _walk_forward(
    rows: list,
    train_months: int = 24,
    val_months: int = 6,
    stride_months: int = 6,
) -> tuple[dict, list[dict], list[dict]]:
    """Returns (aggregate, per_ticker, oos_predictions)."""
    if not rows:
        return {}, [], []
    earliest = rows[0].prediction_date
    latest = rows[-1].prediction_date
    fold_start = earliest + timedelta(days=int(train_months * 30.4))

    pred_records: list[dict] = []
    fold_summaries: list[dict] = []

    while fold_start + timedelta(days=int(val_months * 30.4)) <= latest:
        train_cutoff = fold_start
        val_end = fold_start + timedelta(days=int(val_months * 30.4))
        train_rows = [w for w in rows if w.prediction_date < train_cutoff]
        val_rows = [w for w in rows if train_cutoff <= w.prediction_date < val_end]
        if len(val_rows) == 0 or len(train_rows) < 500:
            fold_start += timedelta(days=int(stride_months * 30.4))
            continue

        X_train = np.stack([w.features for w in train_rows])
        y_train = np.array([w.target for w in train_rows], dtype=np.int64)
        X_val = np.stack([w.features for w in val_rows])
        y_val = np.array([w.target for w in val_rows], dtype=np.int64)
        mom_train = [w.mom_20d_raw for w in train_rows]
        mom_val = [w.mom_20d_raw for w in val_rows]

        log.info(
            "fold cutoff=%s: training on %d rows, validating on %d",
            train_cutoff, len(train_rows), len(val_rows),
        )
        model, scaler = train_mlp(X_train, y_train)
        mlp_proba = predict_proba_up(model, scaler, X_val)

        # Baselines
        baseline_5050 = fifty_fifty_predict(len(val_rows))
        baseline_mom = ConditionalMomentumBaseline.fit(mom_train, y_train.tolist())
        mom_proba = baseline_mom.predict(mom_val)

        # Disagreement metrics — see Phase 7.7 spec
        mlp_dir = (mlp_proba > 0.5).astype(int)
        mom_dir = (mom_proba > 0.5).astype(int)
        disagree_mask = mlp_dir != mom_dir
        n_disagree = int(disagree_mask.sum())
        if n_disagree > 0:
            mlp_correct_on_disagreements = float((mlp_dir[disagree_mask] == y_val[disagree_mask]).mean())
            mom_correct_on_disagreements = float((mom_dir[disagree_mask] == y_val[disagree_mask]).mean())
        else:
            mlp_correct_on_disagreements = None
            mom_correct_on_disagreements = None

        for w, p_mlp, p_mom in zip(val_rows, mlp_proba, mom_proba):
            pred_records.append({
                "date": w.prediction_date, "symbol": w.symbol, "actual": int(w.target),
                "mlp_proba": float(p_mlp), "mom_proba": float(p_mom),
            })

        fold_summaries.append({
            "train_cutoff": train_cutoff.isoformat(),
            "val_end": val_end.isoformat(),
            "n_train": len(train_rows),
            "n_val": len(val_rows),
            "base_rate_up": float(y_val.mean()),
            "mlp_auc": float(roc_auc_score(y_val, mlp_proba)) if len(set(y_val.tolist())) > 1 else None,
            "mlp_brier": float(brier_score_loss(y_val, mlp_proba)),
            "mlp_accuracy": float(accuracy_score(y_val, mlp_dir)),
            "mom_auc": float(roc_auc_score(y_val, mom_proba)) if len(set(y_val.tolist())) > 1 else None,
            "mom_brier": float(brier_score_loss(y_val, mom_proba)),
            "fiftyfifty_brier": float(brier_score_loss(y_val, baseline_5050)),
            # Disagreement metrics
            "pct_disagreement": float(n_disagree / len(val_rows)),
            "mlp_correct_on_disagreements": mlp_correct_on_disagreements,
            "momentum_correct_on_disagreements": mom_correct_on_disagreements,
        })
        fold_start += timedelta(days=int(stride_months * 30.4))

    if not pred_records:
        return {}, [], []

    pred_df = pd.DataFrame(pred_records)
    actual = pred_df["actual"].to_numpy()
    mlp_p = pred_df["mlp_proba"].to_numpy()
    mom_p = pred_df["mom_proba"].to_numpy()
    fifty = np.full(len(pred_df), 0.5)

    aggregate = {
        "n_validation_windows": int(len(pred_df)),
        "base_rate_up": float(actual.mean()),
        "mlp_auc": float(roc_auc_score(actual, mlp_p)),
        "mlp_brier": float(brier_score_loss(actual, mlp_p)),
        "mlp_accuracy": float(accuracy_score(actual, (mlp_p > 0.5).astype(int))),
        "momentum_baseline_auc": float(roc_auc_score(actual, mom_p)),
        "momentum_baseline_brier": float(brier_score_loss(actual, mom_p)),
        "fiftyfifty_baseline_brier": float(brier_score_loss(actual, fifty)),
        # baseline_beaten only when MLP beats BOTH baselines on AUC. 50/50
        # baseline has AUC = 0.5 by definition (no ranking signal), so the
        # binding comparison is vs. conditional momentum.
        "baseline_beaten": bool(
            roc_auc_score(actual, mlp_p) > roc_auc_score(actual, mom_p)
            and roc_auc_score(actual, mlp_p) > 0.5
        ),
        "folds": fold_summaries,
    }
    per_ticker: list[dict] = []
    for sym, grp in pred_df.groupby("symbol"):
        y = grp["actual"].to_numpy()
        if len(set(y.tolist())) < 2:
            continue
        per_ticker.append({
            "symbol": sym,
            "n_validation_windows": int(len(grp)),
            "base_rate_up": float(y.mean()),
            "mlp_auc": float(roc_auc_score(y, grp["mlp_proba"])),
            "mom_auc": float(roc_auc_score(y, grp["mom_proba"])),
            "auc_improvement_vs_mom": float(
                roc_auc_score(y, grp["mlp_proba"]) - roc_auc_score(y, grp["mom_proba"])
            ),
        })
    per_ticker.sort(key=lambda r: r["auc_improvement_vs_mom"], reverse=True)
    return aggregate, per_ticker, pred_records


def _write_oos_predictions(records: list[dict]) -> None:
    """Persist per-fold OOS predictions for the ensemble layer (Phase 7.8)."""
    if not records:
        log.warning("no MLP OOS predictions to write")
        return
    from config import PROJECT_ROOT
    out_path = PROJECT_ROOT / "data" / "models" / "mlp_trend_oos_predictions.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)[["date", "symbol", "mlp_proba"]]
    df["date"] = pd.to_datetime(df["date"])
    df.to_parquet(out_path, index=False)
    log.info("wrote %d MLP OOS predictions to %s", len(df), out_path.name)


def run_mlp_training() -> None:
    universe = sorted(set(settings.watchlist_universe) | set(settings.training_universe))
    # Index ETFs DON'T have a defined sector — would all map to themselves
    # which breaks sector_etf_5d_return as a meaningful feature. Exclude.
    universe = [t for t in universe if t not in ("QQQ", "SPY")]
    log.info("training MLP trend on %d tickers", len(universe))

    ticker_data = _load_ticker_data(universe)
    rows = _flatten_windows(ticker_data)
    log.info("flattened %d total training windows across %d tickers", len(rows), len(ticker_data))

    aggregate, per_ticker, oos_predictions = _walk_forward(rows)
    _write_oos_predictions(oos_predictions)

    # Final model on ALL trainable windows
    final_model = None
    final_scaler = None
    if rows:
        X_all = np.stack([w.features for w in rows])
        y_all = np.array([w.target for w in rows], dtype=np.int64)
        final_model, final_scaler = train_mlp(X_all, y_all)

    metadata = MlpTrendMetadata(
        n_total_windows=len(rows),
        n_trainable_windows=len(rows),
        n_features=len(FEATURE_NAMES),
        feature_names=FEATURE_NAMES,
    )
    save_mlp(
        final_model,
        final_scaler,
        metadata,
        {"aggregate": aggregate, "per_ticker": per_ticker},
    )
    log.info("training complete. aggregate: %s", aggregate)
