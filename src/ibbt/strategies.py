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


REGISTRY: dict[str, type[Strategy]] = {s.name: s for s in (BuyAndHold, SmaCrossover, DonchianBreakout)}


def make_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))
