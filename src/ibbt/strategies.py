"""Strategies turn bars into a long/flat signal.

Contract: `signal()` returns 1 (long) or 0 (flat) for each bar, and the value at bar t
may only use data up to and including bar t's close. The engine trades on the next open.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
import pandas as pd


class Strategy(ABC):
    name: ClassVar[str]

    @abstractmethod
    def signal(self, bars: pd.DataFrame) -> pd.Series:
        """Desired position at each bar's close: 1 = long, 0 = flat."""

    def params(self) -> dict[str, Any]:
        return {}


class BuyAndHold(Strategy):
    name = "buy_and_hold"

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=bars.index, dtype=int)


class SmaCrossover(Strategy):
    """Long while the fast simple moving average is above the slow one."""

    name = "sma_crossover"

    def __init__(self, fast: int = 20, slow: int = 100):
        fast, slow = int(fast), int(slow)
        if fast < 1 or slow <= fast:
            raise ValueError(f"sma_crossover needs 1 <= fast < slow, got fast={fast} slow={slow}")
        self.fast = fast
        self.slow = slow

    def params(self) -> dict[str, Any]:
        return {"fast": self.fast, "slow": self.slow}

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        # NaN comparisons are False, so the warm-up period stays flat.
        return (fast_ma > slow_ma).astype(int)


class DonchianBreakout(Strategy):
    """Donchian channel breakout.

    Enter long when the close exceeds the highest high of the prior `lookback` bars.
    Exit when the close falls below the lowest low of the prior `exit_lookback` bars.
    The channel is shifted by one bar, so the current bar never widens its own channel.
    Stateful (the exit depends on whether we are already long), so it walks the bars in a loop.
    """

    name = "donchian_breakout"

    def __init__(self, lookback: int = 55, exit_lookback: int = 20):
        lookback, exit_lookback = int(lookback), int(exit_lookback)
        if exit_lookback < 1 or exit_lookback >= lookback:
            raise ValueError(
                "donchian_breakout needs 1 <= exit_lookback < lookback, "
                f"got lookback={lookback} exit_lookback={exit_lookback}"
            )
        self.lookback = lookback
        self.exit_lookback = exit_lookback

    def params(self) -> dict[str, Any]:
        return {"lookback": self.lookback, "exit_lookback": self.exit_lookback}

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"].to_numpy(dtype=float)
        upper = bars["high"].rolling(self.lookback).max().shift(1).to_numpy(dtype=float)
        lower = bars["low"].rolling(self.exit_lookback).min().shift(1).to_numpy(dtype=float)

        out = np.zeros(len(close), dtype=int)
        holding = 0
        for i in range(len(close)):
            # NaN comparisons are False, so the warm-up period stays flat.
            if holding == 0 and close[i] > upper[i]:
                holding = 1
            elif holding == 1 and close[i] < lower[i]:
                holding = 0
            out[i] = holding
        return pd.Series(out, index=bars.index, dtype=int)


class RsiPullback(Strategy):
    """Connors-style RSI(2) pullback in an uptrend.

    Enter long when the close is above its `trend` SMA and RSI(`rsi_period`) is below `entry_rsi`.
    Exit when the close rises above its `exit_sma` SMA or RSI exceeds `exit_rsi`.
    Stateful, so it walks the bars in a loop. RSI uses simple averages of gains and losses.
    """

    name = "rsi_pullback"

    def __init__(
        self,
        rsi_period: int = 2,
        entry_rsi: float = 10.0,
        exit_rsi: float = 70.0,
        trend: int = 200,
        exit_sma: int = 5,
    ):
        rsi_period, trend, exit_sma = int(rsi_period), int(trend), int(exit_sma)
        if rsi_period < 1 or trend < 2 or exit_sma < 1:
            raise ValueError("rsi_pullback needs rsi_period, trend and exit_sma to be positive")
        self.rsi_period = rsi_period
        self.entry_rsi = float(entry_rsi)
        self.exit_rsi = float(exit_rsi)
        self.trend = trend
        self.exit_sma = exit_sma

    def params(self) -> dict[str, Any]:
        return {
            "rsi_period": self.rsi_period,
            "entry_rsi": self.entry_rsi,
            "exit_rsi": self.exit_rsi,
            "trend": self.trend,
            "exit_sma": self.exit_sma,
        }

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"].astype(float)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.rsi_period).mean()
        rsi = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(100.0).to_numpy()
        trend_ma = close.rolling(self.trend).mean().to_numpy()
        exit_ma = close.rolling(self.exit_sma).mean().to_numpy()
        c = close.to_numpy()

        out = np.zeros(len(c), dtype=int)
        holding = 0
        for i in range(len(c)):
            # NaN comparisons are False, so the warm-up period stays flat.
            if holding == 0 and c[i] > trend_ma[i] and rsi[i] < self.entry_rsi:
                holding = 1
            elif holding == 1 and (c[i] > exit_ma[i] or rsi[i] > self.exit_rsi):
                holding = 0
            out[i] = holding
        return pd.Series(out, index=bars.index, dtype=int)


REGISTRY: dict[str, type[Strategy]] = {
    s.name: s for s in (BuyAndHold, SmaCrossover, DonchianBreakout, RsiPullback)
}


def make_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))
