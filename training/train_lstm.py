import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import yfinance as yf
from torch.utils.data import DataLoader, TensorDataset

# The backend (app/services/volatility_model.py) loads these same weights at
# inference time, so the architecture is shared from one place rather than
# duplicated -- only app.services.volatility_model itself gets imported here
# (torch/numpy only), not the rest of the backend's FastAPI/DB dependencies.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.volatility_model import SEQUENCE_LENGTH, VOLATILITY_WINDOW, VolatilityLSTM  # noqa: E402


def build_sequences(ticker: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Input: 30-day rolling window of daily log returns.
    Label: trailing realized volatility (std of log returns over VOLATILITY_WINDOW
    days) as of the day right after the input window ends.
    """
    history = yf.Ticker(ticker).history(period="5y", auto_adjust=True)
    if history.empty:
        print(f"Skipping {ticker}: no price history found")
        return np.empty((0, SEQUENCE_LENGTH, 1), dtype=np.float32), np.empty((0, 1), dtype=np.float32)

    log_returns = np.log(history["Close"] / history["Close"].shift(1)).dropna()
    rolling_vol = log_returns.rolling(VOLATILITY_WINDOW).std().dropna()

    returns = log_returns.to_numpy()
    vol = rolling_vol.to_numpy()
    vol_start = len(returns) - len(vol)  # index into `returns` that vol[0] corresponds to

    sequences = []
    labels = []
    for day in range(SEQUENCE_LENGTH, len(returns)):
        vol_index = day - vol_start
        if vol_index < 0 or vol_index >= len(vol):
            continue
        sequences.append(returns[day - SEQUENCE_LENGTH : day])
        labels.append(vol[vol_index])

    if not sequences:
        return np.empty((0, SEQUENCE_LENGTH, 1), dtype=np.float32), np.empty((0, 1), dtype=np.float32)

    x = np.array(sequences, dtype=np.float32).reshape(-1, SEQUENCE_LENGTH, 1)
    y = np.array(labels, dtype=np.float32).reshape(-1, 1)
    return x, y


def load_dataset(tickers: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x_parts = []
    y_parts = []
    for ticker in tickers:
        x, y = build_sequences(ticker)
        if len(x) == 0:
            continue
        x_parts.append(x)
        y_parts.append(y)
        print(f"{ticker}: {len(x)} sequences")

    if not x_parts:
        raise SystemExit("No training data could be built for the given tickers")

    return np.concatenate(x_parts), np.concatenate(y_parts)


def train_val_split(x: np.ndarray, y: np.ndarray, val_fraction: float = 0.2, seed: int = 42):
    rng = np.random.default_rng(seed)
    indices = rng.permutation(len(x))
    split = int(len(x) * (1 - val_fraction))
    train_idx, val_idx = indices[:split], indices[split:]
    return x[train_idx], y[train_idx], x[val_idx], y[val_idx]


def train(tickers: list[str], epochs: int, batch_size: int, learning_rate: float) -> None:
    x, y = load_dataset(tickers)
    x_train, y_train, x_val, y_val = train_val_split(x, y)

    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
        batch_size=batch_size,
        shuffle=True,
    )
    x_val_t = torch.from_numpy(x_val)
    y_val_t = torch.from_numpy(y_val)

    model = VolatilityLSTM()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.MSELoss()

    for epoch in range(1, epochs + 1):
        model.train()
        train_loss = 0.0
        for batch_x, batch_y in train_loader:
            optimizer.zero_grad()
            predictions = model(batch_x)
            loss = loss_fn(predictions, batch_y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(batch_x)
        train_loss /= len(train_loader.dataset)

        model.eval()
        with torch.no_grad():
            val_predictions = model(x_val_t)
            val_loss = loss_fn(val_predictions, y_val_t).item()

        print(f"Epoch {epoch}/{epochs}: train_loss={train_loss:.6f} val_loss={val_loss:.6f}")

    weights_path = Path(__file__).parent / "lstm_weights.pt"
    torch.save(model.state_dict(), weights_path)
    print(f"Saved model weights to {weights_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Train an LSTM to forecast stock volatility")
    parser.add_argument("--tickers", type=str, default="AAPL,MSFT,GOOGL,AMZN,SPY")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    train(tickers, args.epochs, args.batch_size, args.learning_rate)
