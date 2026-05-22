"""Walk-forward training for the ensemble. Includes ablation: full vs
ablated (MLP dropped) to measure whether MLP earns its slot."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from ml.baselines_ensemble import LstmOnlyBaseline, naive_zero_predict
from ml.ensemble import (
    EnsembleMetadata,
    predict_ensemble,
    save_ensemble,
    train_ensemble,
)
from ml.ensemble_features import (
    FEATURE_NAMES_ABLATED,
    FEATURE_NAMES_FULL,
    build_ensemble_dataset,
)

log = logging.getLogger("train_ensemble")

ABLATION_IMPROVEMENT_THRESHOLD = 0.05  # 5% fractional MAE improvement


def _walk_forward(
    df: pd.DataFrame,
    feature_cols: list[str],
    train_months: int = 18,    # shortened from 24 — ensemble OOS data spans
    val_months: int = 4,        # only ~29 months (intersection of LSTM+MLP
    stride_months: int = 4,     # validation windows). 18+4 stride 4 → ~3 folds.
) -> tuple[dict, list[dict]]:
    if df.empty:
        return {}, []

    df = df.sort_values("date").reset_index(drop=True)
    earliest = df["date"].iloc[0].date()
    latest = df["date"].iloc[-1].date()
    fold_start = earliest + timedelta(days=int(train_months * 30.4))

    fold_summaries: list[dict] = []
    pred_records: list[dict] = []

    while fold_start + timedelta(days=int(val_months * 30.4)) <= latest:
        train_cutoff = pd.Timestamp(fold_start)
        val_end = pd.Timestamp(fold_start + timedelta(days=int(val_months * 30.4)))
        train_mask = df["date"] < train_cutoff
        val_mask = (df["date"] >= train_cutoff) & (df["date"] < val_end)
        if val_mask.sum() == 0 or train_mask.sum() < 200:
            fold_start += timedelta(days=int(stride_months * 30.4))
            continue

        X_train = df.loc[train_mask, feature_cols].to_numpy(dtype=np.float64)
        y_train = df.loc[train_mask, "target"].to_numpy(dtype=np.float64)
        X_val = df.loc[val_mask, feature_cols].to_numpy(dtype=np.float64)
        y_val = df.loc[val_mask, "target"].to_numpy(dtype=np.float64)

        log.info(
            "fold cutoff=%s: training on %d rows, validating on %d, features=%d",
            train_cutoff.date(), len(X_train), len(X_val), len(feature_cols),
        )

        model, scaler = train_ensemble(X_train, y_train)
        pred = predict_ensemble(model, scaler, X_val)

        # Baselines fit per-fold on the training data
        baseline_zero = naive_zero_predict(len(y_val))
        lstm_only = LstmOnlyBaseline.fit(X_train[:, feature_cols.index("lstm_pred_rv")], y_train)
        baseline_lstm = lstm_only.predict(X_val[:, feature_cols.index("lstm_pred_rv")])

        fold_summaries.append({
            "train_cutoff": train_cutoff.date().isoformat(),
            "val_end": val_end.date().isoformat(),
            "n_train": int(train_mask.sum()),
            "n_val": int(val_mask.sum()),
            "model_mae": float(mean_absolute_error(y_val, pred)),
            "naive_zero_mae": float(mean_absolute_error(y_val, baseline_zero)),
            "lstm_only_mae": float(mean_absolute_error(y_val, baseline_lstm)),
        })
        for actual, p in zip(y_val, pred):
            pred_records.append({"actual": float(actual), "model_pred": float(p)})

        fold_start += timedelta(days=int(stride_months * 30.4))

    if not pred_records:
        return {}, []

    pred_df = pd.DataFrame(pred_records)
    actual = pred_df["actual"].to_numpy()
    model_pred = pred_df["model_pred"].to_numpy()
    aggregate = {
        "n_validation_windows": int(len(pred_df)),
        "model_mae": float(mean_absolute_error(actual, model_pred)),
        "naive_zero_mae": float(np.mean(np.abs(actual))),
        # `lstm_only_mae` aggregated as mean of fold MAEs (per-fold OLS, can't
        # globally re-fit because fold-boundary leakage would distort it).
        "lstm_only_mae": float(np.mean([f["lstm_only_mae"] for f in fold_summaries])),
        "folds": fold_summaries,
    }
    aggregate["baseline_beaten"] = bool(
        aggregate["model_mae"] < aggregate["naive_zero_mae"]
        and aggregate["model_mae"] < aggregate["lstm_only_mae"]
    )
    return aggregate, pred_records


def run_ensemble_training() -> None:
    df, _ = build_ensemble_dataset()
    if df.empty:
        log.error("ensemble dataset empty — re-run base trainings first")
        save_ensemble(
            None, None, np.zeros(len(FEATURE_NAMES_FULL)),
            EnsembleMetadata(
                n_total_windows=0, n_trainable_windows=0,
                feature_names=FEATURE_NAMES_FULL, target_mean=0.0, target_std=1.0,
                notes="No data — base trainings missing OOS predictions",
            ),
            {},
        )
        return

    log.info("ensemble dataset: %d rows, %d features full", len(df), len(FEATURE_NAMES_FULL))

    # === Ablation: full vs ablated (MLP excluded) ===
    full_agg, _ = _walk_forward(df, FEATURE_NAMES_FULL)
    log.info("FULL ensemble:    %s", _summarize(full_agg))
    ablated_agg, _ = _walk_forward(df, FEATURE_NAMES_ABLATED)
    log.info("ABLATED ensemble: %s", _summarize(ablated_agg))

    full_mae = full_agg.get("model_mae", float("inf"))
    ablated_mae = ablated_agg.get("model_mae", float("inf"))
    if ablated_mae > 0:
        improvement = (ablated_mae - full_mae) / ablated_mae
    else:
        improvement = 0.0
    mlp_earns_slot = improvement >= ABLATION_IMPROVEMENT_THRESHOLD
    log.info(
        "ABLATION RESULT: full_mae=%.4f  ablated_mae=%.4f  improvement=%.2f%%  threshold=%.0f%%  decision=%s",
        full_mae, ablated_mae, improvement * 100, ABLATION_IMPROVEMENT_THRESHOLD * 100,
        "KEEP MLP" if mlp_earns_slot else "DROP MLP from production ensemble",
    )

    # Production model uses the WINNING feature set per the ablation rule:
    # if MLP earns its slot, ship the full model; otherwise ship ablated.
    production_features = FEATURE_NAMES_FULL if mlp_earns_slot else FEATURE_NAMES_ABLATED
    log.info("production ensemble uses %d features: %s", len(production_features), production_features)
    X_all = df[production_features].to_numpy(dtype=np.float64)
    y_all = df["target"].to_numpy(dtype=np.float64)
    final_model, final_scaler = train_ensemble(X_all, y_all)
    feature_training_stds = X_all.std(axis=0)

    target_mean = float(y_all.mean())
    target_std = float(y_all.std())

    metrics = {
        "full": full_agg,
        "ablated": ablated_agg,
        "ablation": {
            "improvement_fractional": improvement,
            "threshold": ABLATION_IMPROVEMENT_THRESHOLD,
            "mlp_earns_slot": mlp_earns_slot,
            "decision": "keep_mlp" if mlp_earns_slot else "drop_mlp",
        },
    }
    save_ensemble(
        final_model, final_scaler, feature_training_stds,
        EnsembleMetadata(
            n_total_windows=len(df),
            n_trainable_windows=len(df),
            feature_names=production_features,
            target_mean=target_mean,
            target_std=target_std,
            notes=("Production ensemble uses ABLATED feature set (MLP dropped) "
                   f"per ablation result: {improvement * 100:+.2f}% < 5%."
                   if not mlp_earns_slot else "Full feature set used."),
        ),
        metrics,
    )
    log.info("ensemble training complete.")


def _summarize(agg: dict) -> str:
    if not agg:
        return "<empty>"
    return (
        f"model_mae={agg.get('model_mae', 0):.4f}  "
        f"naive_zero_mae={agg.get('naive_zero_mae', 0):.4f}  "
        f"lstm_only_mae={agg.get('lstm_only_mae', 0):.4f}  "
        f"baseline_beaten={agg.get('baseline_beaten')}"
    )
