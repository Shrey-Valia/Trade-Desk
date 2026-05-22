"""sklearn MLPRegressor for the Phase 7.8 ensemble + finite-difference
attribution for the components tooltip.

Component attribution:
- Continuous features (lstm_pred_rv, catboost_value, mlp_prob_up): use
  δ = 0.25 × per-feature training std → finite-difference per feature.
- Regime one-hot block: perturb to uniform [0.2, 0.2, 0.2, 0.2, 0.2]
  (a valid "no-regime-info" baseline) and use the SINGLE delta f(current) −
  f(uniform_regime) as `regime_contribution`. This avoids invalid one-hot
  states that piecewise perturbation would create.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from config import PROJECT_ROOT
from ml.ensemble_features import (
    FEATURE_NAMES_ABLATED,
    FEATURE_NAMES_FULL,
    REGIME_FEATURE_NAMES,
)

MODEL_DIR = PROJECT_ROOT / "data" / "models"
MODEL_PATH = MODEL_DIR / "ensemble.pkl"
METRICS_PATH = MODEL_DIR / "ensemble_metrics.json"


@dataclass
class EnsembleMetadata:
    n_total_windows: int
    n_trainable_windows: int
    feature_names: list[str]
    target_mean: float           # for z-score conversion at inference
    target_std: float
    notes: str = ""


def make_ensemble() -> MLPRegressor:
    """Per README §9.5: small MLP (8 hidden units, single layer) to avoid
    overfitting 9 inputs. relu, adam, max_iter=200."""
    return MLPRegressor(
        hidden_layer_sizes=(8,),
        activation="relu",
        solver="adam",
        max_iter=200,
        random_state=42,
    )


def train_ensemble(X_train: np.ndarray, y_train: np.ndarray) -> tuple[MLPRegressor, StandardScaler]:
    scaler = StandardScaler().fit(X_train)
    model = make_ensemble().fit(scaler.transform(X_train), y_train)
    return model, scaler


def predict_ensemble(model: MLPRegressor, scaler: StandardScaler, X: np.ndarray) -> np.ndarray:
    return model.predict(scaler.transform(X))


def attribute(
    model: MLPRegressor,
    scaler: StandardScaler,
    feature_names: list[str],
    x_row: np.ndarray,                    # shape (n_features,)
    feature_training_stds: np.ndarray,    # shape (n_features,)
) -> dict[str, float | None]:
    """Component contributions for ONE row.

    Continuous features: δ = 0.25 * training_std; signed contribution =
    f(x + δ*e_i) - f(x). Direction tells the user whether this feature
    pushed the prediction up or down vs. the slightly-perturbed baseline.

    Regime (5 one-hot slots): single contribution = f(x) - f(x_uniform),
    where x_uniform replaces the 5 slots with [0.2]*5. Sums regime info
    into one number for the tooltip.

    Returns dict of named contributions. CatBoost contribution is None
    when earnings_active == 0 — the value at the row is just the imputed
    median and carries no real signal.
    """
    x = x_row.astype(np.float64).reshape(1, -1)
    f_x = float(model.predict(scaler.transform(x))[0])
    contributions: dict[str, float | None] = {}

    earnings_active_idx = feature_names.index("earnings_active") if "earnings_active" in feature_names else None
    earnings_active = (
        bool(x[0, earnings_active_idx]) if earnings_active_idx is not None else True
    )

    continuous = [
        ("lstm_contribution", "lstm_pred_rv"),
        ("catboost_contribution", "catboost_value"),
        ("mlp_contribution", "mlp_prob_up"),
    ]
    for label, fname in continuous:
        if fname not in feature_names:
            contributions[label] = None
            continue
        if fname == "catboost_value" and not earnings_active:
            contributions[label] = None
            continue
        idx = feature_names.index(fname)
        delta = 0.25 * float(feature_training_stds[idx])
        if delta == 0:
            contributions[label] = 0.0
            continue
        x_perturbed = x.copy()
        x_perturbed[0, idx] += delta
        f_perturbed = float(model.predict(scaler.transform(x_perturbed))[0])
        contributions[label] = f_perturbed - f_x

    # Regime: uniform baseline
    regime_indices = [feature_names.index(r) for r in REGIME_FEATURE_NAMES if r in feature_names]
    if regime_indices:
        x_uniform = x.copy()
        for i in regime_indices:
            x_uniform[0, i] = 0.2
        f_uniform = float(model.predict(scaler.transform(x_uniform))[0])
        contributions["regime_contribution"] = f_x - f_uniform
    else:
        contributions["regime_contribution"] = None

    return contributions


def save_ensemble(
    model: MLPRegressor | None,
    scaler: StandardScaler | None,
    feature_training_stds: np.ndarray,
    metadata: EnsembleMetadata,
    metrics: dict,
) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if model is not None and scaler is not None and metadata.n_trainable_windows > 0:
        with MODEL_PATH.open("wb") as f:
            pickle.dump({
                "model": model,
                "scaler": scaler,
                "feature_training_stds": feature_training_stds.tolist(),
                "feature_names": metadata.feature_names,
            }, f)
    METRICS_PATH.write_text(
        json.dumps({"metadata": asdict(metadata), "metrics": metrics}, indent=2, default=str)
    )


def load_ensemble() -> dict | None:
    if not MODEL_PATH.exists():
        return None
    with MODEL_PATH.open("rb") as f:
        payload = pickle.load(f)
    payload["feature_training_stds"] = np.asarray(payload["feature_training_stds"])
    return payload


def load_ensemble_metadata() -> dict | None:
    if not METRICS_PATH.exists():
        return None
    return json.loads(METRICS_PATH.read_text())
