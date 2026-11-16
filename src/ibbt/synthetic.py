"""Deterministic synthetic price data, for demos and tests without an IB connection."""

from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_bars(
    start: str,
    end: str,
    seed: int = 7,
    start_price: float = 100.0,
    drift: float = 0.0003,
    vol: float = 0.012,
) -> pd.DataFrame:
    """Geometric random walk with plausible open/high/low/volume. Columns: ts, open, ..., volume."""
    dates = pd.bdate_range(start, end)
    n = len(dates)
    rng = np.random.default_rng(seed)

    close = start_price * np.cumprod(1 + rng.normal(drift, vol, n))
    prev_close = np.concatenate([[start_price], close[:-1]])
    open_ = prev_close * (1 + rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)

    return pd.DataFrame({"ts": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
