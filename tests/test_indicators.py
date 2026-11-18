"""The library-backed EMA/RMA must match the Pine-style reference on clean, leading-NaN and gapped input."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ibbt.indicators import _seeded_average, ema, rma


def _series(seed: int = 1, n: int = 400) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 + np.cumsum(rng.normal(0, 1, n))


def _reference_ema(x: np.ndarray, n: int) -> np.ndarray:
    return _seeded_average(x, n, 2.0 / (n + 1))


def _reference_rma(x: np.ndarray, n: int) -> np.ndarray:
    return _seeded_average(x, n, 1.0 / n)


def test_ema_and_rma_match_reference_on_clean_data():
    x = _series()
    for n in (5, 14, 50):
        np.testing.assert_allclose(ema(x, n), _reference_ema(x, n), rtol=0, atol=1e-12, equal_nan=True)
        np.testing.assert_allclose(rma(x, n), _reference_rma(x, n), rtol=0, atol=1e-12, equal_nan=True)


def test_leading_nans_from_shift_match_reference():
    x = _series()
    x[:3] = np.nan
    np.testing.assert_allclose(ema(x, 14), _reference_ema(x, 14), rtol=0, atol=1e-12, equal_nan=True)
    np.testing.assert_allclose(rma(x, 14), _reference_rma(x, 14), rtol=0, atol=1e-12, equal_nan=True)


def test_interior_gap_uses_reference_behaviour():
    x = _series()
    x[100] = np.nan
    np.testing.assert_allclose(ema(x, 14), _reference_ema(x, 14), rtol=0, atol=1e-12, equal_nan=True)
    np.testing.assert_allclose(rma(x, 14), _reference_rma(x, 14), rtol=0, atol=1e-12, equal_nan=True)


def test_accepts_pandas_series_and_all_nan():
    s = pd.Series(_series())
    np.testing.assert_allclose(ema(s, 10), _reference_ema(s.to_numpy(), 10), atol=1e-12, equal_nan=True)
    assert np.isnan(ema(np.full(20, np.nan), 5)).all()
