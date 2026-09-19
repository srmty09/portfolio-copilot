import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# Shared with training/train_lstm.py so both sides agree on architecture and
# input shape without duplicating the class definition.
SEQUENCE_LENGTH = 30
VOLATILITY_WINDOW = 10
DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parents[3] / "training" / "lstm_weights.pt"


class VolatilityLSTM(nn.Module):
    def __init__(self, input_size: int = 1, hidden_size: int = 32, num_layers: int = 2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        output, _ = self.lstm(x)
        last_step = output[:, -1, :]
        return self.fc(last_step)


_model = None
_model_load_attempted = False


def get_model(weights_path: Path = DEFAULT_WEIGHTS_PATH) -> VolatilityLSTM | None:
    """
    Lazily loads the trained LSTM. Returns None (cached, checked only once per
    process) if training/train_lstm.py hasn't been run yet to produce weights --
    callers should fall back to a historical-volatility estimate in that case.
    """
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True

    if not weights_path.exists():
        logger.info("No trained LSTM weights at %s; falling back to historical volatility", weights_path)
        return None

    model = VolatilityLSTM()
    model.load_state_dict(torch.load(weights_path, map_location="cpu"))
    model.eval()
    _model = model
    logger.info("Loaded LSTM volatility model from %s", weights_path)
    return _model


def forecast_daily_volatility(model: VolatilityLSTM, recent_log_returns: np.ndarray) -> float | None:
    """
    recent_log_returns: a ticker's daily log returns, most recent last. Returns the
    model's forecasted next-period daily (not annualized) volatility, or None if
    there isn't enough history for a full input window.
    """
    if len(recent_log_returns) < SEQUENCE_LENGTH:
        return None
    window = recent_log_returns[-SEQUENCE_LENGTH:].astype(np.float32).reshape(1, SEQUENCE_LENGTH, 1)
    with torch.no_grad():
        prediction = model(torch.from_numpy(window))
    return float(prediction.item())
