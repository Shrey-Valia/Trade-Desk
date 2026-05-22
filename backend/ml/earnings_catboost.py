"""CatBoost wrapper for the earnings-move regression model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from catboost import CatBoostRegressor, Pool

from config import PROJECT_ROOT
from ml.features import CATEGORICAL_FEATURES, FEATURE_NAMES

MODEL_DIR = PROJECT_ROOT / "data" / "models"
MODEL_PATH = MODEL_DIR / "earnings_catboost.cbm"
METRICS_PATH = MODEL_DIR / "earnings_catboost_metrics.json"


@dataclass
class TrainingMetadata:
    n_total_events: int
    n_trainable_events: int
    n_features: int
    notes: str = ""


def make_model() -> CatBoostRegressor:
    return CatBoostRegressor(
        iterations=500,
        learning_rate=0.05,
        depth=6,
        loss_function="MAE",
        eval_metric="MAE",
        early_stopping_rounds=30,
        random_seed=42,
        verbose=0,
    )


def to_pool(df: pd.DataFrame, y: list[float] | None = None) -> Pool:
    return Pool(
        data=df[FEATURE_NAMES],
        label=y,
        cat_features=CATEGORICAL_FEATURES,
    )


def save_model(model: CatBoostRegressor, metadata: TrainingMetadata, metrics: dict) -> None:
    """Persist artifact + metrics. Skips the .cbm write when the model is
    untrained (n_trainable_events == 0) — CatBoost raises on save of an
    unfit instance. The metrics JSON is still written so the inference
    endpoint can surface 'Insufficient training data' honestly."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if metadata.n_trainable_events > 0:
        model.save_model(str(MODEL_PATH))
    payload = {
        "metadata": asdict(metadata),
        "metrics": metrics,
    }
    METRICS_PATH.write_text(json.dumps(payload, indent=2, default=str))


def load_model() -> CatBoostRegressor | None:
    if not MODEL_PATH.exists():
        return None
    m = CatBoostRegressor()
    m.load_model(str(MODEL_PATH))
    return m


def load_metadata() -> dict | None:
    if not METRICS_PATH.exists():
        return None
    return json.loads(METRICS_PATH.read_text())
