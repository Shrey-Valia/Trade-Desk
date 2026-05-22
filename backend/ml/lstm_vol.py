"""PyTorch LSTM for 7-day forward realized vol forecasting.

2-layer LSTM(hidden=64, dropout=0.2) → linear → scalar. MSE loss, Adam.
Inputs are normalized; output is a normalized scalar that the inference
endpoint denormalizes using the per-ticker stats saved alongside the
model artifact.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from config import PROJECT_ROOT

MODEL_DIR = PROJECT_ROOT / "data" / "models"
MODEL_PATH = MODEL_DIR / "lstm_vol.pt"
METRICS_PATH = MODEL_DIR / "lstm_vol_metrics.json"
NORM_STATS_PATH = MODEL_DIR / "lstm_vol_norm_stats.json"


@dataclass
class LstmVolMetadata:
    n_total_windows: int
    n_trainable_windows: int
    n_features: int
    use_vix: bool
    feature_names: list[str]
    notes: str = ""


class VolLSTM(nn.Module):
    def __init__(self, input_size: int, hidden_size: int = 64, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.2,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :]).squeeze(-1)


def train_lstm(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    *,
    n_features: int,
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 1e-3,
    patience: int = 5,
    log_every: int = 1,
    progress_callback=None,
) -> tuple[VolLSTM, dict]:
    """Train with early stopping. Returns (model, history)."""
    device = torch.device("cpu")
    model = VolLSTM(input_size=n_features).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train)),
        batch_size=batch_size,
        shuffle=True,
    )
    X_val_t = torch.from_numpy(X_val).to(device)
    y_val_t = torch.from_numpy(y_val).to(device)

    best_val_loss = float("inf")
    best_state = None
    epochs_without_improvement = 0
    history: list[dict] = []

    for epoch in range(epochs):
        model.train()
        epoch_train_loss = 0.0
        n_batches = 0
        for xb, yb in train_loader:
            xb = xb.to(device)
            yb = yb.to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            optimizer.step()
            epoch_train_loss += loss.item()
            n_batches += 1

        model.eval()
        with torch.no_grad():
            val_pred = model(X_val_t)
            val_loss = loss_fn(val_pred, y_val_t).item()

        avg_train_loss = epoch_train_loss / max(n_batches, 1)
        history.append(
            {"epoch": epoch + 1, "train_loss": avg_train_loss, "val_loss": val_loss}
        )
        if progress_callback is not None and (epoch % log_every == 0 or epoch == epochs - 1):
            progress_callback(epoch + 1, avg_train_loss, val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, {"history": history, "best_val_loss": best_val_loss}


def predict_lstm(model: VolLSTM, X: np.ndarray) -> np.ndarray:
    model.eval()
    with torch.no_grad():
        out = model(torch.from_numpy(X)).numpy()
    return out


def save_lstm(
    model: VolLSTM,
    metadata: LstmVolMetadata,
    metrics: dict,
    per_ticker_norm_stats: dict[str, dict],
) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if metadata.n_trainable_windows > 0:
        torch.save(
            {
                "state_dict": model.state_dict(),
                "input_size": metadata.n_features,
            },
            MODEL_PATH,
        )
    METRICS_PATH.write_text(
        json.dumps({"metadata": asdict(metadata), "metrics": metrics}, indent=2, default=str)
    )
    NORM_STATS_PATH.write_text(json.dumps(per_ticker_norm_stats, indent=2, default=str))


def load_lstm() -> VolLSTM | None:
    if not MODEL_PATH.exists():
        return None
    payload = torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
    model = VolLSTM(input_size=payload["input_size"])
    model.load_state_dict(payload["state_dict"])
    model.eval()
    return model


def load_lstm_metadata() -> dict | None:
    if not METRICS_PATH.exists():
        return None
    return json.loads(METRICS_PATH.read_text())


def load_lstm_norm_stats() -> dict[str, dict] | None:
    if not NORM_STATS_PATH.exists():
        return None
    return json.loads(NORM_STATS_PATH.read_text())
