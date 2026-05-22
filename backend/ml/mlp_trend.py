"""sklearn MLPClassifier wrapper for the 5-day trend-direction model."""

from __future__ import annotations

import json
import pickle
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

from config import PROJECT_ROOT

MODEL_DIR = PROJECT_ROOT / "data" / "models"
MODEL_PATH = MODEL_DIR / "mlp_trend.pkl"
METRICS_PATH = MODEL_DIR / "mlp_trend_metrics.json"


@dataclass
class MlpTrendMetadata:
    n_total_windows: int
    n_trainable_windows: int
    n_features: int
    feature_names: list[str]
    notes: str = ""


def make_mlp() -> MLPClassifier:
    """Per README §9.4: 2 hidden layers (64, 32), relu, adam, lr=1e-3, max_iter=500.
    early_stopping=True uses sklearn's internal 10% validation_fraction split."""
    return MLPClassifier(
        hidden_layer_sizes=(64, 32),
        activation="relu",
        solver="adam",
        learning_rate_init=1e-3,
        max_iter=500,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=42,
    )


def train_mlp(X_train: np.ndarray, y_train: np.ndarray) -> tuple[MLPClassifier, StandardScaler]:
    """MLPs converge faster on standardized features. Scaler fit ONLY on
    training data — never the validation fold."""
    scaler = StandardScaler().fit(X_train)
    model = make_mlp().fit(scaler.transform(X_train), y_train)
    return model, scaler


def predict_proba_up(model: MLPClassifier, scaler: StandardScaler, X: np.ndarray) -> np.ndarray:
    return model.predict_proba(scaler.transform(X))[:, 1]


def save_mlp(
    model: MLPClassifier | None,
    scaler: StandardScaler | None,
    metadata: MlpTrendMetadata,
    metrics: dict,
) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # Pickle is fine here — sklearn models are pickled across all of sklearn's
    # own docs. We control the writer + reader so trust boundary is internal.
    if model is not None and scaler is not None and metadata.n_trainable_windows > 0:
        with MODEL_PATH.open("wb") as f:
            pickle.dump({"model": model, "scaler": scaler}, f)
    METRICS_PATH.write_text(
        json.dumps({"metadata": asdict(metadata), "metrics": metrics}, indent=2, default=str)
    )


def load_mlp() -> tuple[MLPClassifier, StandardScaler] | None:
    if not MODEL_PATH.exists():
        return None
    with MODEL_PATH.open("rb") as f:
        payload = pickle.load(f)
    return payload["model"], payload["scaler"]


def load_mlp_metadata() -> dict | None:
    if not METRICS_PATH.exists():
        return None
    return json.loads(METRICS_PATH.read_text())
