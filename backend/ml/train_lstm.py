"""Walk-forward CV for the LSTM vol forecast.

Loads daily bars for all training tickers, builds the per-ticker dataframes,
iterates training windows globally sorted by prediction_date, runs walk-forward
CV with both trailing-RV and HAR-RV baselines. baseline_beaten=True only when
LSTM beats BOTH baselines on aggregate MAE.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from config import settings
from ml.baselines_vol import HarRvModel, build_har_features
from ml.lstm_vol import LstmVolMetadata, predict_lstm, save_lstm, train_lstm
from ml.vol_features import (
    ALL_FEATURES,
    DOW_NAMES,
    NUMERIC_FEATURES,
    TickerData,
    build_ticker_dataframe,
    iter_training_windows,
)
from services.alpaca_client import get_daily_bars_history
from services.fred_client import vix_history

log = logging.getLogger("train_lstm")


def _bars_to_ohlcv(bars) -> dict[str, pd.Series] | None:
    if not bars:
        return None
    closes, highs, lows, volumes = {}, {}, {}, {}
    for b in bars:
        d = pd.Timestamp(b.timestamp.date())
        closes[d] = float(b.close)
        highs[d] = float(b.high)
        lows[d] = float(b.low)
        volumes[d] = float(b.volume or 0)
    return {
        "closes": pd.Series(closes).sort_index(),
        "highs": pd.Series(highs).sort_index(),
        "lows": pd.Series(lows).sort_index(),
        "volumes": pd.Series(volumes).sort_index(),
    }


def _load_all_ticker_data(symbols: list[str], vix_by_date) -> dict[str, TickerData]:
    out: dict[str, TickerData] = {}
    for sym in symbols:
        bars = get_daily_bars_history(sym, years_back=5)
        ohlcv = _bars_to_ohlcv(bars)
        if ohlcv is None:
            log.warning("no bars for %s; skipping", sym)
            continue
        td = build_ticker_dataframe(
            symbol=sym,
            closes=ohlcv["closes"],
            highs=ohlcv["highs"],
            lows=ohlcv["lows"],
            volumes=ohlcv["volumes"],
            vix_by_date=vix_by_date,
        )
        out[sym] = td
    return out


def _flatten_windows(ticker_data: dict[str, TickerData], use_vix: bool):
    """Yield TrainingWindow objects globally sorted by prediction_date."""
    rows: list = []
    for sym, td in ticker_data.items():
        for w in iter_training_windows(td, use_vix=use_vix):
            rows.append(w)
    rows.sort(key=lambda w: w.prediction_date)
    return rows


def _walk_forward(
    rows: list,
    use_vix: bool,
    n_features: int,
    train_months: int = 24,
    val_months: int = 6,
    stride_months: int = 6,
) -> tuple[dict, list[dict], list[dict]]:
    """Returns (aggregate_metrics, per_ticker_metrics, oos_predictions).

    oos_predictions is the raw per-(date, symbol) prediction record list —
    used by the ensemble layer for stacking. Same structure already
    accumulated in `pred_records`; we just return it now."""
    if not rows:
        return {}, [], []

    dates = [w.prediction_date for w in rows]
    earliest, latest = dates[0], dates[-1]
    fold_start = earliest + timedelta(days=int(train_months * 30.4))

    pred_records: list[dict] = []
    fold_summaries: list[dict] = []

    while fold_start + timedelta(days=int(val_months * 30.4)) <= latest:
        train_cutoff = fold_start
        val_end = fold_start + timedelta(days=int(val_months * 30.4))
        train_rows = [w for w in rows if w.prediction_date < train_cutoff]
        val_rows = [w for w in rows if train_cutoff <= w.prediction_date < val_end]
        if len(val_rows) == 0 or len(train_rows) < 200:
            fold_start += timedelta(days=int(stride_months * 30.4))
            continue

        X_train = np.stack([w.features for w in train_rows])
        y_train = np.array([w.target for w in train_rows], dtype=np.float32)
        X_val = np.stack([w.features for w in val_rows])
        y_val_norm = np.array([w.target for w in val_rows], dtype=np.float32)

        log.info(
            "fold cutoff=%s: training on %d rows, validating on %d",
            train_cutoff, len(train_rows), len(val_rows),
        )
        model, _ = train_lstm(
            X_train, y_train, X_val, y_val_norm,
            n_features=n_features,
            progress_callback=lambda e, tl, vl: log.info(
                "  epoch %d  train_loss=%.4f  val_loss=%.4f", e, tl, vl,
            ),
        )

        # Per-row denormalization using the (mu, sigma) captured at PIT
        # for each window. pred_raw = pred_norm * sigma + mu.
        pred_norm = predict_lstm(model, X_val)
        sigmas = np.array([w.target_sigma for w in val_rows])
        mus = np.array([w.target_mu for w in val_rows])
        pred_raw = pred_norm * sigmas + mus

        # Baselines — both predict 7-DAY forward RV (matching LSTM target).
        trailing_pred = np.array([w.trailing_rv_7d for w in val_rows])
        har_pred = _har_rv_baseline(train_rows, val_rows)

        for w, p, t_pred, h_pred in zip(val_rows, pred_raw, trailing_pred, har_pred):
            pred_records.append({
                "date": w.prediction_date,
                "symbol": w.symbol,
                "actual": float(w.target_raw),
                "model_pred": float(p),
                "trailing_rv_pred": float(t_pred),
                "har_rv_pred": float(h_pred),
            })

        last_block = pred_records[-len(val_rows):]
        fold_mae = float(
            np.mean(np.abs(
                np.array([r["actual"] for r in last_block])
                - np.array([r["model_pred"] for r in last_block])
            ))
        )
        fold_summaries.append({
            "train_cutoff": train_cutoff.isoformat(),
            "val_end": val_end.isoformat(),
            "n_train": len(train_rows),
            "n_val": len(val_rows),
            "model_mae": fold_mae,
        })
        fold_start += timedelta(days=int(stride_months * 30.4))

    if not pred_records:
        return {}, [], []

    pred_df = pd.DataFrame(pred_records)
    err_model = np.abs(pred_df["actual"] - pred_df["model_pred"])
    err_trailing = np.abs(pred_df["actual"] - pred_df["trailing_rv_pred"])
    err_har = np.abs(pred_df["actual"] - pred_df["har_rv_pred"])

    aggregate = {
        "n_validation_windows": int(len(pred_df)),
        "model_mae": float(err_model.mean()),
        "model_rmse": float(np.sqrt(((pred_df["actual"] - pred_df["model_pred"]) ** 2).mean())),
        "trailing_rv_baseline_mae": float(err_trailing.mean()),
        "har_rv_baseline_mae": float(err_har.mean()),
        "improvement_vs_trailing": float(err_trailing.mean() - err_model.mean()),
        "improvement_vs_har": float(err_har.mean() - err_model.mean()),
        # baseline_beaten: TRUE only when LSTM beats BOTH baselines, per spec.
        "baseline_beaten": bool(
            err_model.mean() < err_trailing.mean() and err_model.mean() < err_har.mean()
        ),
        "folds": fold_summaries,
    }
    per_ticker: list[dict] = []
    for sym, grp in pred_df.groupby("symbol"):
        per_ticker.append({
            "symbol": sym, "n_validation_windows": int(len(grp)),
            "model_mae": float(np.abs(grp["actual"] - grp["model_pred"]).mean()),
            "trailing_rv_baseline_mae": float(np.abs(grp["actual"] - grp["trailing_rv_pred"]).mean()),
            "har_rv_baseline_mae": float(np.abs(grp["actual"] - grp["har_rv_pred"]).mean()),
            "improvement_vs_har": float(
                np.abs(grp["actual"] - grp["har_rv_pred"]).mean()
                - np.abs(grp["actual"] - grp["model_pred"]).mean()
            ),
        })
    per_ticker.sort(key=lambda r: r["improvement_vs_har"], reverse=True)
    return aggregate, per_ticker, pred_records


def _write_oos_predictions(records: list[dict]) -> None:
    """Persist per-fold OOS predictions for the ensemble layer (Phase 7.8)."""
    if not records:
        log.warning("no OOS predictions to write")
        return
    from config import PROJECT_ROOT
    out_path = PROJECT_ROOT / "data" / "models" / "lstm_vol_oos_predictions.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)[["date", "symbol", "model_pred"]].rename(
        columns={"model_pred": "lstm_pred_rv"}
    )
    df["date"] = pd.to_datetime(df["date"])
    df.to_parquet(out_path, index=False)
    log.info("wrote %d LSTM OOS predictions to %s", len(df), out_path.name)


def _har_rv_baseline(train_rows: list, val_rows: list) -> np.ndarray:
    """Per-ticker HAR-RV: LinearRegression on (rv_1d, rv_5d, rv_22d) → 7d-fwd RV.

    Targets 7-DAY forward RV (NOT 1-day — that would be the canonical HAR-RV
    formulation but would give HAR an unfair advantage over the LSTM).
    """
    by_ticker_train: dict[str, list] = defaultdict(list)
    for w in train_rows:
        by_ticker_train[w.symbol].append(w)

    models: dict[str, HarRvModel] = {}
    for sym, ws in by_ticker_train.items():
        if len(ws) < 30:
            continue
        try:
            models[sym] = HarRvModel.fit(
                trailing_1d=[w.trailing_rv_1d for w in ws],
                trailing_5d=[w.trailing_rv_5d for w in ws],
                trailing_22d=[w.trailing_rv_22d for w in ws],
                target_7d_fwd=[w.target_raw for w in ws],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("HAR-RV fit failed for %s: %s", sym, exc)

    # Global fallback for tickers without per-ticker training rows in this fold.
    global_median = float(np.median([w.target_raw for w in train_rows])) if train_rows else 20.0

    out = np.zeros(len(val_rows), dtype=np.float64)
    for i, w in enumerate(val_rows):
        m = models.get(w.symbol)
        if m is None:
            out[i] = global_median
        else:
            out[i] = m.predict(w.trailing_rv_1d, w.trailing_rv_5d, w.trailing_rv_22d)
    return out


def run_lstm_training() -> None:
    universe = sorted(set(settings.watchlist_universe) | set(settings.training_universe))
    # SPY/QQQ stay IN the LSTM training universe (Phase 7.5) — index ETFs
    # are exactly the vol regime users want predicted. They're only stripped
    # from the earnings backfill, which is in a separate script.
    log.info("training LSTM vol forecast on %d tickers", len(universe))

    earliest = (datetime.now().date() - timedelta(days=5 * 366))
    today = datetime.now().date()
    vix_by_date = vix_history(earliest, today)
    use_vix = bool(vix_by_date)
    if use_vix:
        log.info("VIX available (%d days from FRED)", len(vix_by_date))
    else:
        log.warning("VIX unavailable — training without vix_level/vix_5d_change")

    ticker_data = _load_all_ticker_data(universe, vix_by_date if use_vix else None)
    feature_names = (
        list(NUMERIC_FEATURES if use_vix else [c for c in NUMERIC_FEATURES if "vix" not in c])
        + DOW_NAMES
    )
    n_features = len(feature_names)

    rows = _flatten_windows(ticker_data, use_vix=use_vix)
    log.info("flattened %d total training windows across %d tickers", len(rows), len(ticker_data))

    aggregate, per_ticker, oos_predictions = _walk_forward(rows, use_vix, n_features)
    _write_oos_predictions(oos_predictions)

    # Final model on ALL trainable windows
    final_model = None
    if rows:
        X_all = np.stack([w.features for w in rows])
        y_all = np.array([w.target for w in rows], dtype=np.float32)
        # Hold out last 5% as a small val for early stopping on the final fit
        split = max(int(len(rows) * 0.95), 1)
        X_tr, y_tr = X_all[:split], y_all[:split]
        X_va, y_va = X_all[split:], y_all[split:]
        final_model, _ = train_lstm(
            X_tr, y_tr, X_va, y_va, n_features=n_features,
            progress_callback=lambda e, tl, vl: log.info(
                "final epoch %d  train=%.4f  val=%.4f", e, tl, vl,
            ),
        )

    # Per-ticker normalization stats for inference
    from ml.vol_features import get_feature_norm_stats, get_target_norm_stats
    norm_stats: dict[str, dict] = {}
    for sym, td in ticker_data.items():
        feats = get_feature_norm_stats(td, use_vix=use_vix)
        if feats is None:
            continue
        t_mu, t_sigma = get_target_norm_stats(td)
        if not (t_sigma > 0):
            continue
        norm_stats[sym] = {
            "features": feats,
            "target_mu": t_mu,
            "target_sigma": t_sigma,
        }

    metadata = LstmVolMetadata(
        n_total_windows=len(rows),
        n_trainable_windows=len(rows),
        n_features=n_features,
        use_vix=use_vix,
        feature_names=feature_names,
        notes="" if rows else "Insufficient data — no training windows produced",
    )
    save_lstm(
        final_model if final_model is not None else _make_stub(n_features),
        metadata,
        {"aggregate": aggregate, "per_ticker": per_ticker},
        norm_stats,
    )
    log.info("training complete. aggregate: %s", aggregate)


def _make_stub(n_features: int):
    from ml.lstm_vol import VolLSTM
    return VolLSTM(input_size=n_features)
