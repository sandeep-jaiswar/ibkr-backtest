"""Standard indicators, delegated to `pandas-ta-classic`, with Pine-compatible seeding.

Only the smoothed averages (EMA, RMA/Wilder) come from the library: they are the ones with
subtle conventions, and the library reproduces the Pine-style results exactly.

Specialised indicators (Ehlers, MESA, Kaufman, VIDYA and similar) stay in `strategies.py`
because no library covers them. Plain rolling mean, max, min and std are already pandas
primitives, so they stay as pandas calls in the strategies.

Interior NaN gaps are not handled identically by the library, so those inputs use the original
Pine-style routine below. Leading NaNs (from `.shift()`) go to the library, which matches exactly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta_classic as ta


def _seeded_average(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Pine-style recursive average, seeded with the simple average of the first `n` finite values.

    NaN inputs are skipped and leave the average unchanged. Used only when the input has interior gaps.
    """
    out = np.full(len(x), np.nan)
    finite = np.flatnonzero(np.isfinite(x))
    if len(finite) < n:
        return out
    seed_pos = finite[n - 1]
    prev = float(np.mean(x[finite[:n]]))
    out[seed_pos] = prev
    for i in range(seed_pos + 1, len(x)):
        if np.isfinite(x[i]):
            prev = alpha * x[i] + (1 - alpha) * prev
            out[i] = prev
    return out


def _has_interior_gap(x: np.ndarray) -> bool:
    finite = np.isfinite(x)
    if not finite.any():
        return False
    first = int(np.argmax(finite))
    last = len(x) - 1 - int(np.argmax(finite[::-1]))
    return not finite[first : last + 1].all()


def _smoothed(x: np.ndarray, n: int, library_fn, alpha: float) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if _has_interior_gap(x):
        return _seeded_average(x, n, alpha)
    finite = np.isfinite(x)
    if not finite.any():
        return np.full(len(x), np.nan)
    first = int(np.argmax(finite))
    # The library seeds from its first n values, so start it at the first finite bar.
    tail = pd.Series(x[first:])
    out = np.full(len(x), np.nan)
    out[first:] = np.asarray(library_fn(tail, n), dtype=float)
    return out


def ema(x: np.ndarray | pd.Series, n: int) -> np.ndarray:
    """Exponential moving average, Pine `ta.ema` (alpha = 2/(n+1)), seeded with an SMA of the first `n` values."""
    arr = np.asarray(x, dtype=float)
    return _smoothed(arr, n, lambda s, k: ta.ema(s, k, sma=True), 2.0 / (n + 1))


def rma(x: np.ndarray | pd.Series, n: int) -> np.ndarray:
    """Wilder's moving average, Pine `ta.rma` (alpha = 1/n), seeded with an SMA of the first `n` values."""
    arr = np.asarray(x, dtype=float)
    return _smoothed(arr, n, lambda s, k: ta.rma(s, k), 1.0 / n)
