"""Strategies turn bars into a long/flat signal.

Contract: `signal()` returns 1 (long) or 0 (flat) for each bar, and the value at bar t
may only use data up to and including bar t's close. The engine trades on the next open.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

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


REGISTRY: dict[str, type[Strategy]] = {s.name: s for s in (BuyAndHold, SmaCrossover)}


def make_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))
