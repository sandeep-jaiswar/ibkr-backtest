"""Strategies turn bars into a long/flat signal.

Contract: `signal()` returns 1 (long) or 0 (flat) for each bar, and the value at bar t
may only use data up to and including bar t's close. The engine trades on the next open.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from ibbt.indicators import ema as _ema
from ibbt.indicators import rma as _rma


class Strategy(ABC):
    name: ClassVar[str]
    # Pulse strategies emit a one-bar entry signal and exit only through their own levels.
    uses_levels: ClassVar[bool] = False  # True: `levels()` gives a per-trade stop and target
    signal_exits: ClassVar[bool] = True  # False: portfolio runs ignore signal drops as exits

    @abstractmethod
    def signal(self, bars: pd.DataFrame) -> pd.Series:
        """Desired position at each bar's close: 1 = long, 0 = flat."""

    def levels(self, bars: pd.DataFrame) -> pd.DataFrame | None:
        """Optional per-bar stop and target prices (columns `stop`, `target`), known at that bar's close."""
        return None

    def params(self) -> dict[str, Any]:
        return {}

    def rank_score(self, bars: pd.DataFrame) -> pd.Series | None:
        """Optional tie-break for portfolio runs when more signals fire than free slots.

        Lower score = higher priority. Must only use data up to the bar's close.
        """
        return None


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(100.0)


def _source_series(bars: pd.DataFrame, source: str) -> pd.Series:
    """Price series named by `source`: open, high, low, close, hl2, hlc3 or ohlc4, as floats."""
    o, h, lo, c = (bars[k].astype(float) for k in ("open", "high", "low", "close"))
    return {
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "hl2": (h + lo) / 2,
        "hlc3": (h + lo + c) / 3,
        "ohlc4": (o + h + lo + c) / 4,
    }[source]


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


class EmaCrossover(Strategy):
    """Long while the fast exponential moving average is above the slow one (EMA 21 above EMA 50 by default).

    Exponential averages weight recent closes more heavily. Each value uses only closes up to that bar.
    """

    name = "ema_crossover"

    def __init__(self, fast: int = 21, slow: int = 50):
        fast, slow = int(fast), int(slow)
        if fast < 1 or slow <= fast:
            raise ValueError(f"ema_crossover needs 1 <= fast < slow, got fast={fast} slow={slow}")
        self.fast = fast
        self.slow = slow

    def params(self) -> dict[str, Any]:
        return {"fast": self.fast, "slow": self.slow}

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"].astype(float)
        fast_ema = close.ewm(span=self.fast, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow, adjust=False).mean()
        return (fast_ema > slow_ema).astype(int)


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

    def rank_score(self, bars: pd.DataFrame) -> pd.Series:
        # Most oversold first.
        return _rsi(bars["close"].astype(float), self.rsi_period)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"].astype(float)
        rsi = _rsi(close, self.rsi_period).to_numpy()
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


class IbsReversion(Strategy):
    """Internal-bar-strength mean reversion in an uptrend.

    IBS = (close - low) / (high - low), so 0 means the bar closed on its low.
    Enter when the close is above its `trend` SMA and IBS is below `entry_ibs`.
    Exit when IBS rises above `exit_ibs`. Stateful, so it walks the bars in a loop.
    Bars with zero range get IBS 0.5 and never trigger an entry.
    """

    name = "ibs_reversion"

    def __init__(self, trend: int = 200, entry_ibs: float = 0.2, exit_ibs: float = 0.8):
        trend = int(trend)
        if trend < 2:
            raise ValueError("ibs_reversion needs trend >= 2")
        if not 0 <= float(entry_ibs) < float(exit_ibs) <= 1:
            raise ValueError("ibs_reversion needs 0 <= entry_ibs < exit_ibs <= 1")
        self.trend = trend
        self.entry_ibs = float(entry_ibs)
        self.exit_ibs = float(exit_ibs)

    def params(self) -> dict[str, Any]:
        return {"trend": self.trend, "entry_ibs": self.entry_ibs, "exit_ibs": self.exit_ibs}

    def _ibs(self, bars: pd.DataFrame) -> pd.Series:
        rng = (bars["high"] - bars["low"]).replace(0, np.nan)
        return ((bars["close"] - bars["low"]) / rng).fillna(0.5).astype(float)

    def rank_score(self, bars: pd.DataFrame) -> pd.Series:
        return self._ibs(bars)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"].astype(float).to_numpy()
        ibs = self._ibs(bars).to_numpy()
        trend_ma = bars["close"].astype(float).rolling(self.trend).mean().to_numpy()

        out = np.zeros(len(close), dtype=int)
        holding = 0
        for i in range(len(close)):
            # NaN comparisons are False, so the warm-up period stays flat.
            if holding == 0 and close[i] > trend_ma[i] and ibs[i] < self.entry_ibs:
                holding = 1
            elif holding == 1 and ibs[i] > self.exit_ibs:
                holding = 0
            out[i] = holding
        return pd.Series(out, index=bars.index, dtype=int)


class PriceActionBreakout(Strategy):
    """Price-action entries with a predefined stop and a nearest-resistance target.

    Entry (a one-bar pulse, decided at the close, filled at the next open). Either:
      * breakout: close above the prior `breakout_lookback`-bar high and in the upper half of the bar, or
      * support bounce: the bar's low tests the prior `support_lookback`-bar low (within `support_tol`),
        the close reclaims that low, and the candle is bullish (close above open, in the upper 60% of the range).

    Filters:
      * no falling knives: close above SMA(`trend`), and that SMA higher than 20 bars earlier;
      * no lower lows: the lowest low of the last 10 bars is not below the lowest low of the 10 bars before.

    Risk, set on the signal bar:
      * stop = support low minus `stop_buffer`. The stop distance must lie in [`min_risk`, `max_risk`] of the close.
      * target = nearest resistance: the prior `breakout_lookback`-bar high, if it is at least 1% above the close;
        otherwise the measured move (breakout base height added above the breakout level), if at least 1% above;
        otherwise 2R.
      * the engine skips the trade if the open at fill is already at or above the target, or if the risk at the
        fill exceeds `max_risk`.

    Stateless: the signal is a pulse, so exits come only from the stop, target or time stop.
    Ranking when slots are scarce: larger reward-to-risk first.
    """

    name = "price_action_breakout"
    uses_levels = True
    signal_exits = False

    def __init__(
        self,
        breakout_lookback: int = 20,
        support_lookback: int = 20,
        support_tol: float = 0.02,
        trend: int = 200,
        stop_buffer: float = 0.005,
        min_risk: float = 0.02,
        max_risk: float = 0.10,
        leg: str = "both",
        stop_mode: str = "support",
        atr_mult: float = 2.0,
        min_volume_ratio: float = 0.0,
    ):
        if stop_mode not in ("support", "atr"):
            raise ValueError("price_action_breakout stop_mode must be 'support' or 'atr'")
        if atr_mult <= 0 or min_volume_ratio < 0:
            raise ValueError("price_action_breakout needs atr_mult > 0 and min_volume_ratio >= 0")
        self.stop_mode = stop_mode
        self.atr_mult = float(atr_mult)
        self.min_volume_ratio = float(min_volume_ratio)
        if leg not in ("both", "breakout", "bounce"):
            raise ValueError("price_action_breakout leg must be 'both', 'breakout' or 'bounce'")
        self.leg = leg
        self.breakout_lookback = int(breakout_lookback)
        self.support_lookback = int(support_lookback)
        self.trend = int(trend)
        if min(self.breakout_lookback, self.support_lookback) < 20 or self.trend < 50:
            raise ValueError("price_action_breakout needs lookbacks >= 20 and trend >= 50")
        if not 0 <= support_tol < 0.2 or not 0 <= stop_buffer < 0.1:
            raise ValueError("price_action_breakout: support_tol in [0,0.2), stop_buffer in [0,0.1)")
        if not 0 <= min_risk < max_risk < 1:
            raise ValueError("price_action_breakout needs 0 <= min_risk < max_risk < 1")
        self.support_tol = float(support_tol)
        self.stop_buffer = float(stop_buffer)
        self.min_risk = float(min_risk)
        self.max_risk = float(max_risk)

    def params(self) -> dict[str, Any]:
        return {
            "breakout_lookback": self.breakout_lookback,
            "support_lookback": self.support_lookback,
            "support_tol": self.support_tol,
            "trend": self.trend,
            "stop_buffer": self.stop_buffer,
            "min_risk": self.min_risk,
            "max_risk": self.max_risk,
            "leg": self.leg,
            "stop_mode": self.stop_mode,
            "atr_mult": self.atr_mult,
            "min_volume_ratio": self.min_volume_ratio,
        }

    def _frame(self, bars: pd.DataFrame) -> dict[str, pd.Series]:
        o, h, lo, c = (bars[k].astype(float) for k in ("open", "high", "low", "close"))
        support = lo.rolling(self.support_lookback).min().shift(1)  # prior support low
        breakout_level = h.rolling(self.breakout_lookback).max().shift(1)  # prior range high = nearest resistance
        if self.stop_mode == "atr":
            # Wilder ATR(14) from true range; the stop sits atr_mult ATRs below the close, known at that close.
            pc = c.shift(1)
            tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
            stop = c - self.atr_mult * tr.rolling(14).mean()
        else:
            stop = support * (1 - self.stop_buffer)
        return {"o": o, "h": h, "l": lo, "c": c, "support": support, "breakout_level": breakout_level, "stop": stop}

    def levels(self, bars: pd.DataFrame) -> pd.DataFrame:
        f = self._frame(bars)
        c, stop = f["c"], f["stop"]
        measured = f["breakout_level"] + (f["breakout_level"] - f["support"])
        target = f["breakout_level"].where(f["breakout_level"] >= c * 1.01)
        target = target.fillna(measured.where(measured >= c * 1.01))
        target = target.fillna(c + 2 * (c - stop))  # 2R fallback
        return pd.DataFrame({"stop": stop, "target": target}, index=bars.index)

    def rank_score(self, bars: pd.DataFrame) -> pd.Series:
        lv = self.levels(bars)
        c, stop, target = bars["close"].astype(float), lv["stop"], lv["target"]
        return -((target - c) / (c - stop))  # larger reward-to-risk ranks first

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        f = self._frame(bars)
        o, h, lo, c = f["o"], f["h"], f["l"], f["c"]
        rng = (h - lo).replace(0, np.nan)
        upper_half = (c - lo) >= 0.5 * rng
        breakout = (c > f["breakout_level"]) & upper_half
        bullish = (c > o) & ((c - lo) >= 0.6 * rng)
        bounce = (lo <= f["support"] * (1 + self.support_tol)) & (c > f["support"]) & bullish

        sma = c.rolling(self.trend).mean()
        not_falling_knife = (c > sma) & (sma > sma.shift(20))
        low10 = lo.rolling(10).min()
        no_lower_lows = low10 >= low10.shift(10)  # NaN in warm-up compares False

        risk = (c - f["stop"]) / c
        risk_ok = (risk >= self.min_risk) & (risk <= self.max_risk)

        trigger = {"breakout": breakout, "bounce": bounce}.get(self.leg, breakout | bounce)
        if self.min_volume_ratio > 0:
            vol = bars["volume"].astype(float)
            volume_ok = (vol / vol.rolling(20).mean()) >= self.min_volume_ratio  # NaN in warm-up -> False
        else:
            volume_ok = True
        entry = trigger & not_falling_knife & no_lower_lows & risk_ok & volume_ok
        return entry.fillna(False).astype(int)


class HigherHighStructure(Strategy):
    """Higher-high structure, entered on second confirmation, exited on structure break.

    Stateful. The signal is 1 while the trade is in force, so the portfolio engine enters on the bar after
    the signal and exits when the signal drops to 0 (the next open after the structure breaks).

    Entry (all evaluated on the close of bar t, filled at t+1 open):
      * first confirmation C1 at t-1: a higher high (high above the prior `lookback`-bar high),
        with the close in the upper half of that bar's range;
      * second confirmation at t: another higher high (high above C1's high) with a higher close than C1;
      * no falling knife: close above SMA(`trend`) and that SMA rising over 20 bars;
      * no lower lows: the 10-bar low is not below the low of the 10 bars before it.

    Structure trail (dynamic stop, no fixed price stop):
      * the trail starts at the lowest low of the 5 bars up to entry, and only ratchets up:
        trail = max(previous trail, lowest low of the last `trail_bars` bars);
      * exit when the close falls below the trail set on the previous bar (structure disturbed).

    Ranking when slots are scarce: smaller distance from close to trail first (tighter structure).
    """

    name = "higher_high_structure"
    uses_levels = False
    signal_exits = True

    def __init__(self, lookback: int = 20, trail_bars: int = 5, trend: int = 200):
        self.lookback = int(lookback)
        self.trail_bars = int(trail_bars)
        self.trend = int(trend)
        if self.lookback < 5 or self.trail_bars < 2 or self.trend < 50:
            raise ValueError("higher_high_structure needs lookback >= 5, trail_bars >= 2, trend >= 50")

    def params(self) -> dict[str, Any]:
        return {"lookback": self.lookback, "trail_bars": self.trail_bars, "trend": self.trend}

    def _setup(self, bars: pd.DataFrame) -> dict[str, np.ndarray]:
        h = bars["high"].astype(float)
        lo = bars["low"].astype(float)
        c = bars["close"].astype(float)
        prior_high = h.rolling(self.lookback).max().shift(1)
        rng = (h - lo).replace(0, np.nan)
        upper_half = (c - lo) >= 0.5 * rng
        c1 = (h > prior_high) & upper_half  # first confirmation, on its own bar
        c1_prev = c1.shift(1, fill_value=False).astype(bool)
        h_prev, c_prev = h.shift(1), c.shift(1)
        second = c1_prev & (h > h_prev) & (c > c_prev)  # second higher high after C1, with a higher close
        sma = c.rolling(self.trend).mean()
        not_falling_knife = (c > sma) & (sma > sma.shift(20))
        low10 = lo.rolling(10).min()
        no_lower_lows = low10 >= low10.shift(10)
        entry = (second & not_falling_knife & no_lower_lows).fillna(False).to_numpy()
        trail_low = lo.rolling(self.trail_bars).min().to_numpy(dtype=float)
        return {"entry": entry, "trail_low": trail_low, "c": c.to_numpy(dtype=float), "lo": lo.to_numpy(dtype=float)}

    def rank_score(self, bars: pd.DataFrame) -> pd.Series:
        # Distance from close to the structure trail, as a fraction of close, using the same trail rule.
        s = self._setup(bars)
        trail = self._trail_series(s)
        c = s["c"]
        dist = (c - trail) / c
        return pd.Series(dist, index=bars.index)

    def _trail_series(self, s: dict[str, np.ndarray]) -> np.ndarray:
        """Trail as if held from the bar where the trail is first set (it is only meaningful while holding)."""
        trail = np.full(len(s["c"]), np.nan)
        t = np.nan
        for i in range(len(trail)):
            t = s["trail_low"][i] if np.isnan(t) else max(t, s["trail_low"][i])
            trail[i] = t
        return trail

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        s = self._setup(bars)
        n = len(s["c"])
        out = np.zeros(n, dtype=int)
        holding = False
        trail = np.nan
        for i in range(n):
            if not holding:
                if s["entry"][i]:
                    holding = True
                    trail = s["trail_low"][i]  # initial structure level: lowest low of the last trail_bars bars
            else:
                # Structure check uses the trail known at the previous close; only then ratchet the trail up.
                if s["c"][i] < trail:
                    holding = False
                    trail = np.nan
                else:
                    trail = max(trail, s["trail_low"][i])
            out[i] = int(holding)
        return pd.Series(out, index=bars.index, dtype=int)


class ChampionDailySetup(Strategy):
    """Chartink 'champion-daily-setup-29' entry, implemented as a daily pulse.

    Entry on bar t when all hold (evaluated on the close of t, filled at t+1 open):
      * close above the close 1 bar ago;
      * close above SMA(200) and above SMA(50);
      * 50-bar and 100-bar averages of daily traded value (volume * close) both above 5 crore;
      * today's true range above 1x ATR(20) or above 1x ATR(100) (ATR = simple average of true range);
      * volume above its 20-bar or 100-bar average;
      * close in the top 40% of the day's range (close > low + 0.6 * (high - low)).
    The clause's market-cap filter (<= 80,000 crore) is NOT applied: the stored bars carry no market cap.
    The clause has no exit, so exits are supplied by the test harness (time stops).
    """

    name = "champion_daily_setup"
    uses_levels = False  # no fixed stop unless stop_atr_mult is set; the harness passes levels via the strategy
    signal_exits = False
    RANKINGS = ("none", "volume_surge", "trend_distance", "liquidity", "range_expansion", "close_strength")

    def __init__(self, rank_by: str = "none", min_traded_value: float = 5e7, stop_atr_mult: float | None = None):
        if rank_by not in self.RANKINGS:
            raise ValueError(f"champion_daily_setup rank_by must be one of {self.RANKINGS}")
        if min_traded_value <= 0:
            raise ValueError("min_traded_value must be positive")
        self.rank_by = rank_by
        self.min_traded_value = float(min_traded_value)
        if stop_atr_mult is not None and stop_atr_mult <= 0:
            raise ValueError("stop_atr_mult must be positive or None")
        self.stop_atr_mult = None if stop_atr_mult is None else float(stop_atr_mult)

    def params(self) -> dict[str, Any]:
        return {"rank_by": self.rank_by, "min_traded_value": self.min_traded_value, "stop_atr_mult": self.stop_atr_mult}

    def levels(self, bars: pd.DataFrame) -> pd.DataFrame | None:
        """Protective stop: close minus stop_atr_mult x ATR(20), fixed at entry. No target (NaN)."""
        if self.stop_atr_mult is None:
            return None
        h, lo, c = (bars[k].astype(float) for k in ("high", "low", "close"))
        pc = c.shift(1)
        tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        stop = c - self.stop_atr_mult * tr.rolling(20).mean()
        return pd.DataFrame({"stop": stop, "target": np.nan}, index=bars.index)

    def rank_score(self, bars: pd.DataFrame) -> pd.Series | None:
        """Lower score = taken first when slots are scarce. Every value uses only bars up to that close."""
        if self.rank_by == "none":
            return None
        h, lo, c, v = (bars[k].astype(float) for k in ("high", "low", "close", "volume"))
        pc = c.shift(1)
        tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        if self.rank_by == "volume_surge":
            score = -(v / v.rolling(20).mean())
        elif self.rank_by == "trend_distance":
            score = -(c / c.rolling(50).mean() - 1)
        elif self.rank_by == "liquidity":
            score = -((v * c).rolling(50).mean())
        elif self.rank_by == "range_expansion":
            score = -(tr / tr.rolling(20).mean())
        else:  # close_strength: close near the top of the day's range
            score = -((c - lo) / (h - lo).replace(0, np.nan))
        return score.fillna(0.0)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        h, lo, c, v = (bars[k].astype(float) for k in ("high", "low", "close", "volume"))
        pc = c.shift(1)
        tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        tv = v * c
        cond = (
            (c > pc)
            & (c > c.rolling(200).mean())
            & (c > c.rolling(50).mean())
            & (tv.rolling(50).mean() > self.min_traded_value)
            & (tv.rolling(100).mean() > self.min_traded_value)
            & ((tr > tr.rolling(20).mean()) | (tr > tr.rolling(100).mean()))
            & ((v > v.rolling(20).mean()) | (v > v.rolling(100).mean()))
            & (c > lo + 0.6 * (h - lo))
        )
        return cond.fillna(False).astype(int).rename("signal")


class RmaAtrBands(Strategy):
    """Port of the Pine script "RMA ATR Bands" (SchizoQuant), as a long/flat strategy.

    Bands: MA = RMA(source, `ma_length`), with source = high by default.
      upper = MA + ATR(`atr_length`) * upper_mult,  lower = MA - ATR(`atr_length`) * lower_mult,
      ATR = RMA of the true range.
    Trend latch (as in the script): close above the upper band sets trend to +1 (long), close below
    the lower band sets trend to -1 (short). Between signals the trend holds its last value.
    Long while trend == +1, flat otherwise. The script's short signal is the exit, and the engine trades the
    next open. Every value uses only bars up to its own close.
    """

    name = "rma_atr_bands"

    def __init__(
        self,
        source: str = "high",
        ma_length: int = 14,
        atr_length: int = 13,
        upper_mult: float = 0.4,
        lower_mult: float = 1.6,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("rma_atr_bands source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        ma_length, atr_length = int(ma_length), int(atr_length)
        if ma_length < 1 or atr_length < 1:
            raise ValueError("rma_atr_bands needs ma_length and atr_length >= 1")
        if float(upper_mult) < 0 or float(lower_mult) < 0:
            raise ValueError("rma_atr_bands needs non-negative ATR multipliers")
        self.source = source
        self.ma_length = ma_length
        self.atr_length = atr_length
        self.upper_mult = float(upper_mult)
        self.lower_mult = float(lower_mult)

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ma_length": self.ma_length,
            "atr_length": self.atr_length,
            "upper_mult": self.upper_mult,
            "lower_mult": self.lower_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def bands(self, bars: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Return (ma, upper, lower) as arrays aligned with bars."""
        h, lo, c = (bars[k].astype(float) for k in ("high", "low", "close"))
        pc = c.shift(1)
        tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)  # first bar: high - low
        ma = _rma(self._source(bars).to_numpy(), self.ma_length)
        atr = _rma(tr.to_numpy(), self.atr_length)
        upper = ma + atr * self.upper_mult
        lower = ma - atr * self.lower_mult
        return (
            pd.Series(ma, index=bars.index),
            pd.Series(upper, index=bars.index),
            pd.Series(lower, index=bars.index),
        )

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        _, upper, lower = self.bands(bars)
        close = bars["close"].astype(float).to_numpy()
        up = upper.to_numpy()
        dn = lower.to_numpy()

        out = np.zeros(len(close), dtype=int)
        trend = 0
        for i in range(len(close)):
            # NaN comparisons are False, so the warm-up period keeps the trend at 0 (flat).
            if close[i] > up[i]:
                trend = 1
            if close[i] < dn[i]:
                trend = -1
            out[i] = int(trend == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class ProjectedCrossover(Strategy):
    """Port of the Pine script "Projected Crossover Trend" (SchizoQuant), as a long/flat strategy.

    fastMA = EMA(src, fast_len), slowMA = SMA(src, slow_len). projected = fast_len * (fastMA - slowMA).
    MDI = EMA(100 * (projected - projected_prev) / close, smooth_len).
    Trend latch (as in the script): MDI > 0 and close > close[slow_len] sets the trend to +1 (long);
    MDI < 0 and close < close[slow_len] sets it to -1 (short). Between signals the trend holds its last value.
    Long while the trend is +1, flat otherwise. The short signal is the exit. The engine trades the next open.
    Every value uses only bars up to its own close.
    """

    name = "projected_crossover"

    def __init__(
        self,
        source: str = "close",
        fast_len: int = 10,
        slow_len: int = 30,
        smooth_len: int = 5,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("projected_crossover source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        fast_len, slow_len, smooth_len = int(fast_len), int(slow_len), int(smooth_len)
        if fast_len < 2 or slow_len < 3 or smooth_len < 1:
            raise ValueError("projected_crossover needs fast_len >= 2, slow_len >= 3, smooth_len >= 1")
        self.source = source
        self.fast_len = fast_len
        self.slow_len = slow_len
        self.smooth_len = smooth_len

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fast_len": self.fast_len,
            "slow_len": self.slow_len,
            "smooth_len": self.smooth_len,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def mdi(self, bars: pd.DataFrame) -> pd.Series:
        """Market Direction Indicator, aligned with bars."""
        src = self._source(bars)
        close = bars["close"].astype(float)
        fast_ma = _ema(src.to_numpy(), self.fast_len)
        slow_ma = src.rolling(self.slow_len).mean().to_numpy()
        projected = self.fast_len * (fast_ma - slow_ma)
        raw = 100 * (projected - pd.Series(projected, index=bars.index).shift(1).to_numpy()) / close.to_numpy()
        return pd.Series(_ema(raw, self.smooth_len), index=bars.index)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        mdi = self.mdi(bars).to_numpy()
        close = bars["close"].astype(float).to_numpy()
        past = bars["close"].astype(float).shift(self.slow_len).to_numpy()  # close[slow_len]

        out = np.zeros(len(close), dtype=int)
        trend = 0
        for i in range(len(close)):
            # NaN comparisons are False, so the warm-up period keeps the trend at 0 (flat).
            if mdi[i] > 0 and close[i] > past[i]:
                trend = 1
            if mdi[i] < 0 and close[i] < past[i]:
                trend = -1
            out[i] = int(trend == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class DualMaSdOscillator(Strategy):
    """Port of the Pine script "Dual MA SD Oscillator" (SchizoQuant), as a long/flat strategy.

    spread = EMA(src, fast_len) - EMA(src, slow_len); osc = EMA(spread, smooth_len).
    Upper band = stdev(osc, upper_sd_len); lower band = -stdev(osc, lower_sd_len). stdev is the population
    standard deviation, as in Pine's `ta.stdev`.
    Trend latch (as in the script): osc > upper band sets the trend to +1 (long); osc < lower band sets it to -1.
    Between signals the trend holds its last value. Long while the trend is +1, flat otherwise.
    The short signal is the exit. The engine trades the next open. Every value uses only bars up to its own close.
    """

    name = "dual_ma_sd_oscillator"

    def __init__(
        self,
        source: str = "close",
        fast_len: int = 1,
        slow_len: int = 30,
        smooth_len: int = 1,
        upper_sd_len: int = 25,
        lower_sd_len: int = 25,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("dual_ma_sd_oscillator source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        lengths = [int(fast_len), int(slow_len), int(smooth_len), int(upper_sd_len), int(lower_sd_len)]
        if min(lengths) < 1:
            raise ValueError("dual_ma_sd_oscillator needs every length >= 1")
        self.source = source
        self.fast_len, self.slow_len, self.smooth_len = lengths[0], lengths[1], lengths[2]
        self.upper_sd_len, self.lower_sd_len = lengths[3], lengths[4]

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fast_len": self.fast_len,
            "slow_len": self.slow_len,
            "smooth_len": self.smooth_len,
            "upper_sd_len": self.upper_sd_len,
            "lower_sd_len": self.lower_sd_len,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def oscillator(self, bars: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Return (osc, upper, lower) aligned with bars."""
        src = self._source(bars).to_numpy()
        spread = _ema(src, self.fast_len) - _ema(src, self.slow_len)
        osc = _ema(spread, self.smooth_len)
        osc_s = pd.Series(osc)
        upper = osc_s.rolling(self.upper_sd_len).std(ddof=0).to_numpy()
        lower = -osc_s.rolling(self.lower_sd_len).std(ddof=0).to_numpy()
        idx = bars.index
        return pd.Series(osc, index=idx), pd.Series(upper, index=idx), pd.Series(lower, index=idx)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        osc, upper, lower = (x.to_numpy() for x in self.oscillator(bars))

        out = np.zeros(len(osc), dtype=int)
        trend = 0
        for i in range(len(osc)):
            # NaN comparisons are False, so the warm-up period keeps the trend at 0 (flat).
            if osc[i] > upper[i]:
                trend = 1
            if osc[i] < lower[i]:
                trend = -1
            out[i] = int(trend == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class DoubleSmoothedMadTrend(Strategy):
    """Port of the Pine script "Double-Smoothed Momentum MAD Trend" (SchizoQuant), as a long/flat strategy.

    momentum = src - src[momentum_len]. tsi = 100 * EMA(EMA(momentum, smooth1), smooth2)
                                             / EMA(EMA(|momentum|, smooth1), smooth2)  (0 when the denominator is 0).
    basis = SMA(tsi, mad_len); madValue = SMA(|tsi - basis|, mad_len) (mean absolute deviation, not stdev).
    Upper threshold = mad_mult * madValue, lower = -mad_mult * madValue.
    Trend latch (as in the script): tsi > upper sets the trend to +1 (long); tsi < lower sets it to -1 (short).
    The script starts with trend = +1 (`var int SQ = 1`), so the strategy is long from its first bar until the
    first short signal. This port keeps that initial state. The signal line is only a plot and is not used.
    Long while the trend is +1, flat otherwise. The engine trades the next open.
    Every value uses only bars up to its own close.
    """

    name = "double_smoothed_mad"

    def __init__(
        self,
        source: str = "close",
        momentum_len: int = 1,
        smooth1: int = 1,
        smooth2: int = 20,
        mad_len: int = 29,
        mad_mult: float = 1.0,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("double_smoothed_mad source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.momentum_len = int(momentum_len)
        self.smooth1 = int(smooth1)
        self.smooth2 = int(smooth2)
        self.mad_len = int(mad_len)
        self.mad_mult = float(mad_mult)
        if min(self.momentum_len, self.smooth1, self.smooth2) < 1 or self.mad_len < 2:
            raise ValueError("double_smoothed_mad needs momentum_len, smooth1, smooth2 >= 1 and mad_len >= 2")
        if self.mad_mult < 0.1:
            raise ValueError("double_smoothed_mad needs mad_mult >= 0.1")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "momentum_len": self.momentum_len,
            "smooth1": self.smooth1,
            "smooth2": self.smooth2,
            "mad_len": self.mad_len,
            "mad_mult": self.mad_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def tsi(self, bars: pd.DataFrame) -> pd.Series:
        src = self._source(bars)
        momentum = (src - src.shift(self.momentum_len)).to_numpy()
        num = _ema(_ema(momentum, self.smooth1), self.smooth2)
        den = _ema(_ema(np.abs(momentum), self.smooth1), self.smooth2)
        with np.errstate(divide="ignore", invalid="ignore"):
            # Pine: den != 0 ? 100 * num / den : 0. A NaN denominator (warm-up) stays NaN.
            tsi = np.where(den != 0.0, 100.0 * num / den, 0.0)
        return pd.Series(tsi, index=bars.index)

    def bands(self, bars: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Return (upper, lower) MAD thresholds aligned with bars."""
        tsi = self.tsi(bars)
        basis = tsi.rolling(self.mad_len).mean()
        mad = (tsi - basis).abs().rolling(self.mad_len).mean()
        return self.mad_mult * mad, -self.mad_mult * mad

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        tsi = self.tsi(bars).to_numpy()
        upper, lower = (x.to_numpy() for x in self.bands(bars))

        out = np.zeros(len(tsi), dtype=int)
        trend = 1  # `var int SQ = 1` in the script
        for i in range(len(tsi)):
            # NaN comparisons are False, so the trend holds through warm-up.
            if tsi[i] > upper[i]:
                trend = 1
            if tsi[i] < lower[i]:
                trend = -1
            out[i] = int(trend == 1)
        return pd.Series(out, index=bars.index, dtype=int)


def _percentile_nearest_rank(x: np.ndarray, n: int, pct: float) -> np.ndarray:
    """Rolling nearest-rank percentile over the last `n` values (Pine `ta.percentile_nearest_rank`).

    Rank k = ceil(pct / 100 * n), clamped to [1, n], taken from the ascending sort of the window.
    A window containing NaN gives NaN.
    """
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(x, n)
    ordered = np.sort(windows, axis=1)  # NaN sorts last
    k = min(max(int(np.ceil(pct / 100.0 * n)), 1), n)
    vals = ordered[:, k - 1]
    vals = np.where(np.isnan(windows).any(axis=1), np.nan, vals)
    out[n - 1 :] = vals
    return out


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    """x shifted forward by k bars: out[t] = x[t - k], NaN where t < k."""
    out = np.full(len(x), np.nan)
    if k == 0:
        return x.astype(float).copy()
    out[k:] = x[:-k]
    return out


class AdaptiveEhlersPercentile(Strategy):
    """Port of the Pine script "Adaptive Ehlers Filtered Percentile" (SchizoQuant), as a long/flat strategy.

    Adaptive MA: s = stdev(src - src[1], vol_len) (population); s_avg = SMA(s, vol_len); the adaptive length moves
    linearly from ma_max (calm, s <= 0.25 s_avg) to ma_min (volatile, s >= 1.75 s_avg). alpha = 2 / (length + 1).
    The average re-seeds from src whenever its previous value is NaN, as in the script.
    Ehlers filter (trend): over the last filter_len values, weight |a[i] - a[i + momentum_len]| times a[i];
    trend = sum(weight * a) / sum(weight), falling back to SMA(a, filter_len) when the weights sum to 0.
    Band distance: nearest-rank percentile(percentile_level) of |src - trend| over percentile_len bars.
    Upper = trend + distance * upper_mult, lower = trend - distance * lower_mult.
    Regime latch (as in the script, starting flat): src > upper sets +1 (long); src < lower sets -1 (flat).
    Long while the regime is +1, flat otherwise. The engine trades the next open. Every value uses only past
    and present bars.
    """

    name = "adaptive_ehlers_percentile"

    def __init__(
        self,
        source: str = "close",
        ma_min: int = 3,
        ma_max: int = 30,
        vol_len: int = 9,
        filter_len: int = 9,
        momentum_len: int = 15,
        percentile_len: int = 50,
        percentile_level: float = 75.0,
        upper_mult: float = 0.7,
        lower_mult: float = 0.7,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError(
                "adaptive_ehlers_percentile source must be one of open, high, low, close, hl2, hlc3, ohlc4"
            )
        self.source = source
        self.ma_min = int(ma_min)
        self.ma_max = int(ma_max)
        self.vol_len = int(vol_len)
        self.filter_len = int(filter_len)
        self.momentum_len = int(momentum_len)
        self.percentile_len = int(percentile_len)
        self.percentile_level = float(percentile_level)
        self.upper_mult = float(upper_mult)
        self.lower_mult = float(lower_mult)
        if self.ma_min < 1 or self.ma_max < 2 or self.ma_min > self.ma_max:
            raise ValueError("adaptive_ehlers_percentile needs 1 <= ma_min <= ma_max, ma_max >= 2")
        if self.vol_len < 2 or self.filter_len < 2 or self.momentum_len < 1 or self.percentile_len < 2:
            raise ValueError(
                "adaptive_ehlers_percentile: vol_len, filter_len >= 2, momentum_len >= 1, percentile_len >= 2"
            )
        if not 1.0 <= self.percentile_level <= 99.0:
            raise ValueError("adaptive_ehlers_percentile percentile_level must be in [1, 99]")
        if self.upper_mult < 0.1 or self.lower_mult < 0.1:
            raise ValueError("adaptive_ehlers_percentile multipliers must be >= 0.1")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ma_min": self.ma_min,
            "ma_max": self.ma_max,
            "vol_len": self.vol_len,
            "filter_len": self.filter_len,
            "momentum_len": self.momentum_len,
            "percentile_len": self.percentile_len,
            "percentile_level": self.percentile_level,
            "upper_mult": self.upper_mult,
            "lower_mult": self.lower_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def bands(self, bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (trend, upper, lower) arrays aligned with bars."""
        src = self._source(bars)
        delta = src - src.shift(1)
        s = delta.rolling(self.vol_len).std(ddof=0).to_numpy()
        s_avg = pd.Series(s).rolling(self.vol_len).mean().to_numpy()
        s_min = s_avg * 0.25
        s_max = s_avg * 1.75
        vol_range = s_max - s_min
        with np.errstate(invalid="ignore", divide="ignore"):
            # Pine: na comparisons are false, so a NaN volatility gives NaN and a NaN range falls to ma_max.
            length = np.where(
                vol_range > 0.0,
                np.where(
                    s <= s_min,
                    self.ma_max,
                    np.where(
                        s >= s_max,
                        self.ma_min,
                        self.ma_max - (self.ma_max - self.ma_min) * (s - s_min) / vol_range,
                    ),
                ),
                self.ma_max,
            )
            alpha = 2.0 / (length + 1.0)

        x = src.to_numpy()
        ama = np.full(len(x), np.nan)
        prev = np.nan
        for t in range(len(x)):
            if np.isnan(prev):  # na(adaptiveMA[1]): re-seed from the source
                cur = x[t]
            else:
                cur = prev + alpha[t] * (x[t] - prev)
            ama[t] = cur
            prev = cur

        num = np.zeros(len(ama))
        den = np.zeros(len(ama))
        for i in range(self.filter_len):
            cur_s = _shift(ama, i)
            ref_s = _shift(ama, i + self.momentum_len)
            valid = np.isfinite(cur_s) & np.isfinite(ref_s)
            coef = np.where(valid, np.abs(cur_s - ref_s), 0.0)
            num += np.where(valid, coef * np.where(valid, cur_s, 0.0), 0.0)
            den += coef
        fallback = pd.Series(ama).rolling(self.filter_len).mean().to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            trend = np.where(den > 0.0, num / den, fallback)

        dist = _percentile_nearest_rank(np.abs(x - trend), self.percentile_len, self.percentile_level)
        return trend, trend + dist * self.upper_mult, trend - dist * self.lower_mult

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        _, upper, lower = self.bands(bars)
        x = self._source(bars).to_numpy()

        out = np.zeros(len(x), dtype=int)
        regime = 0  # `var int SQ = 0`
        for i in range(len(x)):
            # NaN comparisons are False, so the warm-up period stays flat.
            if x[i] > upper[i]:
                regime = 1
            elif x[i] < lower[i]:
                regime = -1
            out[i] = int(regime == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class VolatilityAdaptiveTrend(Strategy):
    """Port of the Pine script "Volatility Adaptive Filtered Trend" (SchizoQuant), as a long/flat strategy.

    Adaptive smoothing: atr = Wilder ATR(vol_len); change = |src - src[vol_len]|;
    factors = atr / SMA(atr, norm_len) and change / SMA(change, norm_len) (1 when the baseline is 0);
    normalized = clamp((atr_factor + change_factor) / 2 / 2, 0, 1); sc = min_sc + (max_sc - min_sc) * normalized.
    adaptive_t = adaptive_t[1] + sc * (src - adaptive_t[1]), re-seeded from src when the previous value is NaN.
    emaT = EMA(adaptive_t, ema_len). Ehlers filter on emaT over filter_len bars with momentum_len spacing, weighted
    by |a[i] - a[i + momentum_len]|, falling back to SMA(emaT, filter_len) when the weights sum to 0.
    Volatility = population stdev of simple returns over band_vol_len bars, taken one bar late, as in the script.
    Upper = trend + upper_mult * volatility * trend; lower = trend - lower_mult * volatility * trend.
    Regime latch (starts flat): close > upper sets +1 (long); close < lower sets -1 (flat).
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    """

    name = "volatility_adaptive_trend"

    def __init__(
        self,
        source: str = "hlc3",
        vol_len: int = 15,
        norm_len: int = 30,
        min_sc: float = 0.084,
        max_sc: float = 0.330,
        ema_len: int = 5,
        filter_len: int = 9,
        momentum_len: int = 2,
        band_vol_len: int = 22,
        upper_mult: float = 2.0,
        lower_mult: float = 2.0,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("volatility_adaptive_trend source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.vol_len = int(vol_len)
        self.norm_len = int(norm_len)
        self.min_sc = float(min_sc)
        self.max_sc = float(max_sc)
        self.ema_len = int(ema_len)
        self.filter_len = int(filter_len)
        self.momentum_len = int(momentum_len)
        self.band_vol_len = int(band_vol_len)
        self.upper_mult = float(upper_mult)
        self.lower_mult = float(lower_mult)
        if self.vol_len < 2 or self.norm_len < 5 or self.ema_len < 1 or self.band_vol_len < 2:
            raise ValueError("volatility_adaptive_trend: vol_len >= 2, norm_len >= 5, ema_len >= 1, band_vol_len >= 2")
        if self.filter_len < 2 or self.momentum_len < 1:
            raise ValueError("volatility_adaptive_trend: filter_len >= 2 and momentum_len >= 1")
        if not 0.001 <= self.min_sc <= 1 or not 0.001 <= self.max_sc <= 1:
            raise ValueError("volatility_adaptive_trend smoothing limits must be in [0.001, 1]")
        if self.upper_mult < 0.1 or self.lower_mult < 0.1:
            raise ValueError("volatility_adaptive_trend multipliers must be >= 0.1")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "vol_len": self.vol_len,
            "norm_len": self.norm_len,
            "min_sc": self.min_sc,
            "max_sc": self.max_sc,
            "ema_len": self.ema_len,
            "filter_len": self.filter_len,
            "momentum_len": self.momentum_len,
            "band_vol_len": self.band_vol_len,
            "upper_mult": self.upper_mult,
            "lower_mult": self.lower_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def bands(self, bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (trend, upper, lower) arrays aligned with bars."""
        h, lo, c = (bars[k].astype(float) for k in ("high", "low", "close"))
        src_s = self._source(bars)
        src = src_s.to_numpy()

        pc = c.shift(1)
        tr = pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
        atr = _rma(tr.to_numpy(), self.vol_len)
        change = np.abs(src - src_s.shift(self.vol_len).to_numpy())
        atr_base = pd.Series(atr).rolling(self.norm_len).mean().to_numpy()
        change_base = pd.Series(change).rolling(self.norm_len).mean().to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            # Pine: baseline != 0 ? x / baseline : 1. A NaN baseline is != 0, so it gives NaN.
            atr_f = np.where(atr_base != 0.0, atr / atr_base, 1.0)
            chg_f = np.where(change_base != 0.0, change / change_base, 1.0)
            combined = (atr_f + chg_f) * 0.5
            normalized = np.maximum(0.0, np.minimum(1.0, combined / 2.0))  # NaN propagates, as math.min/max do
        sc = self.min_sc + (self.max_sc - self.min_sc) * normalized

        adaptive = np.full(len(src), np.nan)
        prev = np.nan
        for t in range(len(src)):
            cur = src[t] if np.isnan(prev) else prev + sc[t] * (src[t] - prev)
            adaptive[t] = cur
            prev = cur

        ema_t = _ema(adaptive, self.ema_len)

        num = np.zeros(len(ema_t))
        den = np.zeros(len(ema_t))
        for i in range(self.filter_len):
            cur_s = _shift(ema_t, i)
            ref_s = _shift(ema_t, i + self.momentum_len)
            valid = np.isfinite(cur_s) & np.isfinite(ref_s)
            coef = np.where(valid, np.abs(cur_s - ref_s), 0.0)
            num += np.where(valid, coef * np.where(valid, cur_s, 0.0), 0.0)
            den += coef
        fallback = pd.Series(ema_t).rolling(self.filter_len).mean().to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            trend = np.where(den > 0.0, num / den, fallback)

        prev_c = _shift(src, 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.where(prev_c != 0.0, (src - prev_c) / prev_c, 0.0)
        vol = pd.Series(ret).rolling(self.band_vol_len).std(ddof=0).shift(1).to_numpy()

        upper = trend + self.upper_mult * vol * trend
        lower = trend - self.lower_mult * vol * trend
        return trend, upper, lower

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        _, upper, lower = self.bands(bars)
        close = bars["close"].astype(float).to_numpy()

        out = np.zeros(len(close), dtype=int)
        regime = 0  # `var int SQ = 0`
        for i in range(len(close)):
            # NaN comparisons are False, so the warm-up period stays flat.
            if close[i] > upper[i]:
                regime = 1
            elif close[i] < lower[i]:
                regime = -1
            out[i] = int(regime == 1)
        return pd.Series(out, index=bars.index, dtype=int)


def _mesa_phase_activity(src: np.ndarray, fast_limit: float, slow_limit: float) -> np.ndarray:
    """Hilbert-transform phase activity, following the Pine script line by line (Ehlers MESA style).

    Each stage feeds the next bar. Pine's nz(x) is x with NaN replaced by 0, and nz(x, d) uses d.
    phase uses math.atan without quadrant correction, as the script does.
    Returns phaseActivity in [0, 1] for each bar.
    """
    import math

    def nan_to(v: float, d: float) -> float:
        return d if v != v else v

    def mn(a: float, b: float) -> float:  # Pine math.min: NaN propagates
        return float("nan") if (a != a or b != b) else min(a, b)

    def mx(a: float, b: float) -> float:  # Pine math.max: NaN propagates
        return float("nan") if (a != a or b != b) else max(a, b)

    n = len(src)
    nan = float("nan")
    smooth = [nan] * n
    det = [nan] * n
    q1 = [nan] * n
    i1 = [nan] * n
    i2 = [nan] * n
    q2 = [nan] * n
    re = [nan] * n
    im = [nan] * n
    period = [nan] * n
    phase = [nan] * n
    activity = np.zeros(n)

    def back(arr: list, k: int, default: float) -> float:
        """arr[t - k] with Pine's nz default; the caller's t is the loop index."""
        j = t - k
        if j < 0:
            return default
        return nan_to(arr[j], default)

    def hilbert(x: list, t_val: float, pf: float) -> float:
        return (0.0962 * t_val + 0.5769 * back(x, 2, 0.0) - 0.5769 * back(x, 4, 0.0) - 0.0962 * back(x, 6, 0.0)) * pf

    for t in range(n):
        s0 = float(src[t])
        smooth_t = (
            4.0 * s0
            + 3.0 * (float(src[t - 1]) if t >= 1 and src[t - 1] == src[t - 1] else s0)
            + 2.0 * (float(src[t - 2]) if t >= 2 and src[t - 2] == src[t - 2] else s0)
            + (float(src[t - 3]) if t >= 3 and src[t - 3] == src[t - 3] else s0)
        ) / 10.0
        smooth[t] = smooth_t

        prev_period = back(period, 1, 10.0)
        pf = 0.075 * prev_period + 0.54

        det_t = hilbert(smooth, smooth_t, pf)
        det[t] = det_t
        q1_t = hilbert(det, det_t, pf)
        q1[t] = q1_t
        i1_t = back(det, 3, 0.0)
        i1[t] = i1_t
        ji = hilbert(i1, i1_t, pf)
        jq = hilbert(q1, q1_t, pf)

        i2_t = 0.2 * (i1_t - jq) + 0.8 * back(i2, 1, 0.0)
        q2_t = 0.2 * (q1_t + ji) + 0.8 * back(q2, 1, 0.0)
        i2[t] = i2_t
        q2[t] = q2_t

        re_raw = i2_t * back(i2, 1, 0.0) + q2_t * back(q2, 1, 0.0)
        im_raw = i2_t * back(q2, 1, 0.0) - q2_t * back(i2, 1, 0.0)
        re_t = 0.2 * re_raw + 0.8 * back(re, 1, 0.0)
        im_t = 0.2 * im_raw + 0.8 * back(im, 1, 0.0)
        re[t] = re_t
        im[t] = im_t

        angle = math.degrees(math.atan(im_t / re_t)) if re_t != 0.0 else 0.0
        raw = abs(360.0 / angle) if angle != 0.0 else prev_period
        lim = mn(raw, 1.5 * prev_period)
        lim = mx(lim, 0.67 * prev_period)
        lim = mx(6.0, mn(50.0, lim))
        period_t = 0.2 * lim + 0.8 * prev_period
        period[t] = period_t

        phase_t = math.degrees(math.atan(q1_t / i1_t)) if i1_t != 0.0 else back(phase, 1, 0.0)
        phase[t] = phase_t
        delta = mx(back(phase, 1, 0.0) - phase_t, 1.0)
        alpha = mx(fast_limit / delta, slow_limit)
        phase_range = mx(fast_limit - slow_limit, 0.0001)
        activity[t] = mx(0.0, mn(1.0, (alpha - slow_limit) / phase_range))
    return activity


class MesaPhaseBandTrend(Strategy):
    """Port of the Pine script "MESA Phase-Adaptive Band Trend" (SchizoQuant), as a long/flat strategy.

    Phase activity: the Ehlers MESA Hilbert-transform phase, turned into an activity measure in [0, 1]
    (see `_mesa_phase_activity`). A stateful Pine-line port.
    Trend = EMA(src, trend_len). Volatility = population stdev of simple returns over vol_len, taken one bar late.
    Band multiplier = slow_mult - (slow_mult - active_mult) * activity, so the band is narrow when phase is active.
    Upper = trend + mult * volatility * trend; lower = trend - mult * volatility * trend.
    Regime latch (starts flat): close > upper sets +1 (long); close < lower sets -1 (flat).
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    """

    name = "mesa_phase_band"

    def __init__(
        self,
        source: str = "hl2",
        fast_limit: float = 0.50,
        slow_limit: float = 0.05,
        trend_len: int = 20,
        vol_len: int = 20,
        active_mult: float = 1.5,
        slow_mult: float = 3.0,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("mesa_phase_band source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.fast_limit = float(fast_limit)
        self.slow_limit = float(slow_limit)
        self.trend_len = int(trend_len)
        self.vol_len = int(vol_len)
        self.active_mult = float(active_mult)
        self.slow_mult = float(slow_mult)
        if not 0.01 <= self.fast_limit <= 1.0 or not 0.001 <= self.slow_limit <= 1.0:
            raise ValueError("mesa_phase_band limits must be in [0.01, 1] (fast) and [0.001, 1] (slow)")
        if self.trend_len < 2 or self.vol_len < 2:
            raise ValueError("mesa_phase_band needs trend_len >= 2 and vol_len >= 2")
        if self.active_mult < 0.1 or self.slow_mult < 0.1:
            raise ValueError("mesa_phase_band multipliers must be >= 0.1")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "fast_limit": self.fast_limit,
            "slow_limit": self.slow_limit,
            "trend_len": self.trend_len,
            "vol_len": self.vol_len,
            "active_mult": self.active_mult,
            "slow_mult": self.slow_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def bands(self, bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        src_s = self._source(bars)
        src = src_s.to_numpy()
        activity = _mesa_phase_activity(src, self.fast_limit, self.slow_limit)

        trend = _ema(src, self.trend_len)
        prev = src_s.shift(1).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.where(prev != 0.0, (src - prev) / prev, 0.0)
        vol = pd.Series(ret).rolling(self.vol_len).std(ddof=0).shift(1).to_numpy()

        mult = self.slow_mult - (self.slow_mult - self.active_mult) * activity
        upper = trend + mult * vol * trend
        lower = trend - mult * vol * trend
        return trend, upper, lower

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        _, upper, lower = self.bands(bars)
        close = bars["close"].astype(float).to_numpy()

        out = np.zeros(len(close), dtype=int)
        regime = 0  # `var int SQ = 0`
        for i in range(len(close)):
            # NaN comparisons are False, so the warm-up period stays flat.
            if close[i] > upper[i]:
                regime = 1
            elif close[i] < lower[i]:
                regime = -1
            out[i] = int(regime == 1)
        return pd.Series(out, index=bars.index, dtype=int)


def _nmax(a: float, b: float) -> float:
    """Pine math.max: NaN propagates."""
    return float("nan") if (a != a or b != b) else max(a, b)


def _nmin(a: float, b: float) -> float:
    """Pine math.min: NaN propagates."""
    return float("nan") if (a != a or b != b) else min(a, b)


class AdaptivePersistenceTrail(Strategy):
    """Port of the Pine script "Adaptive Persistence Trail" (SchizoQuant), as a long/flat strategy.

    Persistence: over the last `persistence_len` bars, sum the up-moves (bullish travel) and down-moves (bearish
    travel) of the source, with Pine's nz fallback to the current bar.
    persistence = (bull - bear) / (bull + bear), clamped to [-1, 1]; clarity = |persistence|.
    Acceleration = min_acc + clarity * (max_acc - min_acc).
    Reset distance = max(ATR(atr_len), mintick) * reset_mult.
    Recent low/high = lowest low / highest high over `protection_len` bars, including the current bar.
    Regime state (as in the script; it starts bullish because persistence is 0 on the first bar):
      * bullish: extreme = max(extreme, high); trail = max(trail, min(trail + acc * (extreme - trail), recent low));
        long to short when src < trail;
      * bearish: the mirror image, with min(extreme, low) and max(..., recent high); short to long when src > trail.
      * a flip resets the extreme (high or low) and places the trail reset_distance away from src.
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    `mintick` stands in for Pine's syminfo.mintick, which is not available outside TradingView.
    """

    name = "adaptive_persistence_trail"

    def __init__(
        self,
        source: str = "close",
        persistence_len: int = 20,
        min_acc: float = 0.5,
        max_acc: float = 1.0,
        protection_len: int = 21,
        atr_len: int = 14,
        reset_mult: float = 2.0,
        mintick: float = 0.01,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError(
                "adaptive_persistence_trail source must be one of open, high, low, close, hl2, hlc3, ohlc4"
            )
        self.source = source
        self.persistence_len = int(persistence_len)
        self.min_acc = float(min_acc)
        self.max_acc = float(max_acc)
        self.protection_len = int(protection_len)
        self.atr_len = int(atr_len)
        self.reset_mult = float(reset_mult)
        self.mintick = float(mintick)
        if self.persistence_len < 2 or self.protection_len < 1 or self.atr_len < 1:
            raise ValueError("adaptive_persistence_trail needs persistence_len >= 2, protection_len >= 1, atr_len >= 1")
        if not 0 < self.min_acc <= 1 or not 0 < self.max_acc <= 1:
            raise ValueError("adaptive_persistence_trail accelerations must be in (0, 1]")
        if self.reset_mult < 0.1 or self.mintick <= 0:
            raise ValueError("adaptive_persistence_trail needs reset_mult >= 0.1 and mintick > 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "persistence_len": self.persistence_len,
            "min_acc": self.min_acc,
            "max_acc": self.max_acc,
            "protection_len": self.protection_len,
            "atr_len": self.atr_len,
            "reset_mult": self.reset_mult,
            "mintick": self.mintick,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        h = bars["high"].astype(float).to_numpy()
        lo = bars["low"].astype(float).to_numpy()
        c = bars["close"].astype(float)
        src_s = self._source(bars)
        s = src_s.to_numpy()
        n = len(s)

        def filled(k: int) -> np.ndarray:
            """src[t - k], with Pine's nz(src[k], src): the current bar's source where that value is NaN."""
            arr = _shift(s, k)
            return np.where(np.isnan(arr), s, arr)

        bull = np.zeros(n)
        bear = np.zeros(n)
        for i in range(self.persistence_len):
            pc = filled(i) - filled(i + 1)
            bull += np.where(pc > 0.0, pc, 0.0)
            bear += np.where(pc < 0.0, -pc, 0.0)
        total = bull + bear
        with np.errstate(invalid="ignore", divide="ignore"):
            pers = np.where(total > 0.0, (bull - bear) / total, 0.0)
        pers = np.maximum(-1.0, np.minimum(1.0, pers))
        clarity = np.abs(pers)
        lo_acc, up_acc = min(self.min_acc, self.max_acc), max(self.min_acc, self.max_acc)
        acc = lo_acc + clarity * (up_acc - lo_acc)

        pc_close = _shift(c.to_numpy(), 1)
        tr = np.nanmax(np.vstack([h - lo, np.abs(h - pc_close), np.abs(lo - pc_close)]), axis=0)
        tr[0] = h[0] - lo[0]  # no previous close on the first bar
        atr = np.maximum(_rma(tr, self.atr_len), self.mintick)
        reset = atr * self.reset_mult

        recent_low = pd.Series(lo).rolling(self.protection_len).min().to_numpy()
        recent_high = pd.Series(h).rolling(self.protection_len).max().to_numpy()

        out = np.zeros(n, dtype=int)
        sq = 1 if pers[0] >= 0.0 else -1  # `var int SQ = persistence >= 0 ? 1 : -1`
        extreme = s[0]  # `var float regimeExtreme = src`
        trail = np.nan  # `var float trendTrail = na`
        for t in range(n):
            prev_sq = sq
            prev_ext = extreme if extreme == extreme else s[t]
            if trail == trail:
                prev_trail = trail
            else:
                prev_trail = s[t] - reset[t] if prev_sq == 1 else s[t] + reset[t]

            if prev_sq == 1:
                ext_t = _nmax(prev_ext, h[t])
                accel = prev_trail + acc[t] * (ext_t - prev_trail)
                protected = _nmin(accel, recent_low[t])
                trail_t = _nmax(prev_trail, protected)
            else:
                ext_t = _nmin(prev_ext, lo[t])
                accel = prev_trail + acc[t] * (ext_t - prev_trail)
                protected = _nmax(accel, recent_high[t])
                trail_t = _nmin(prev_trail, protected)
            extreme, trail = ext_t, trail_t

            is_long = prev_sq == -1 and s[t] > trail_t  # NaN comparisons are false
            is_short = prev_sq == 1 and s[t] < trail_t
            if is_long:
                sq = 1
                extreme = h[t]
                trail = s[t] - reset[t]
            elif is_short:
                sq = -1
                extreme = lo[t]
                trail = s[t] + reset[t]
            else:
                sq = prev_sq
            out[t] = int(sq == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class AdaptiveVidya(Strategy):
    """Port of the Pine script "Adaptive VIDYA Trend" (SchizoQuant), as a long/flat strategy.

    k = stdev(src, short_len) / stdev(src, long_len) (0 when the long deviation is not positive), so NaN warm-up
    gives k = 0. alpha = clamp(k * base_smoothing, 0, 1).
    VIDYA = alpha * src + (1 - alpha) * VIDYA[1], re-seeded from src when the previous value is NaN.
    Residual = src - VIDYA; residual deviation = stdev(residual, band_len) (population).
    Upper = VIDYA + upper_mult * deviation; lower = VIDYA - lower_mult * deviation.
    Regime latch (starts bullish: `var int SQ = src >= vidya ? 1 : -1`, true on the first bar):
    src > upper sets +1 (long); src < lower sets -1 (flat). Long while the regime is +1, flat otherwise.
    The engine trades the next open. Only past and present bars are used.
    """

    name = "adaptive_vidya"

    def __init__(
        self,
        source: str = "close",
        short_len: int = 10,
        long_len: int = 30,
        base_smoothing: float = 0.20,
        band_len: int = 20,
        upper_mult: float = 1.5,
        lower_mult: float = 1.5,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("adaptive_vidya source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.short_len = int(short_len)
        self.long_len = int(long_len)
        self.base_smoothing = float(base_smoothing)
        self.band_len = int(band_len)
        self.upper_mult = float(upper_mult)
        self.lower_mult = float(lower_mult)
        if self.short_len < 2 or self.long_len < 3 or self.band_len < 2:
            raise ValueError("adaptive_vidya needs short_len >= 2, long_len >= 3, band_len >= 2")
        if not 0.01 <= self.base_smoothing <= 1.0:
            raise ValueError("adaptive_vidya base_smoothing must be in [0.01, 1]")
        if self.upper_mult < 0.1 or self.lower_mult < 0.1:
            raise ValueError("adaptive_vidya multipliers must be >= 0.1")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "short_len": self.short_len,
            "long_len": self.long_len,
            "base_smoothing": self.base_smoothing,
            "band_len": self.band_len,
            "upper_mult": self.upper_mult,
            "lower_mult": self.lower_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def bands(self, bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (vidya, upper, lower) arrays aligned with bars."""
        src_s = self._source(bars)
        src = src_s.to_numpy()

        short_dev = src_s.rolling(self.short_len).std(ddof=0).to_numpy()
        long_dev = src_s.rolling(self.long_len).std(ddof=0).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            k = np.where(long_dev > 0.0, short_dev / long_dev, 0.0)
        alpha = np.maximum(0.0, np.minimum(1.0, k * self.base_smoothing))

        vidya = np.full(len(src), np.nan)
        prev = np.nan
        for t in range(len(src)):
            cur = src[t] if np.isnan(prev) else alpha[t] * src[t] + (1.0 - alpha[t]) * prev
            vidya[t] = cur
            prev = cur

        residual = src - vidya
        resid_dev = pd.Series(residual).rolling(self.band_len).std(ddof=0).to_numpy()
        upper = vidya + resid_dev * self.upper_mult
        lower = vidya - resid_dev * self.lower_mult
        return vidya, upper, lower

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        vidya, upper, lower = self.bands(bars)
        src = self._source(bars).to_numpy()

        out = np.zeros(len(src), dtype=int)
        regime = 1 if src[0] >= vidya[0] else -1  # `var int SQ = src >= vidya ? 1 : -1`
        for i in range(len(src)):
            # NaN comparisons are False, so the warm-up period keeps the regime.
            if src[i] > upper[i]:
                regime = 1
            elif src[i] < lower[i]:
                regime = -1
            out[i] = int(regime == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class AdaptiveSuperSmoother(Strategy):
    """Port of the Pine script "Adaptive SuperSmoother" (SchizoQuant), as a long/flat strategy.

    Adaptive MA: s = stdev(src - src[1], vol_len); sMean = SMA(s, vol_len); the volatility position
    clamps (s - 0.25 sMean) / (1.5 sMean) to [0, 1]. The period moves from ma_max (calm) to ma_min (volatile),
    alpha = 2 / (period + 1), and the average re-seeds from src when its previous value is NaN.
    SuperSmoother (Ehlers, 2-pole) on the adaptive MA with `smooth_len`; re-seeded from the adaptive MA in warm-up.
    Efficiency = |src - src[er_len]| / sum of |src[i] - src[i+1]| over er_len bars, clamped to [0, 1].
    fastWeight = fast_bias + (1 - fast_bias) * efficiency; trend = adaptiveMA * fastWeight + smooth * (1 - fastWeight).
    Slope = trend - trend[1]; threshold = RMA(|slope|, noise_len) * noise_mult.
    Regime latch (starts flat): slope > threshold sets +1 (long); slope < -threshold sets -1 (flat).
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    """

    name = "adaptive_supersmoother"

    def __init__(
        self,
        source: str = "close",
        ma_min: int = 14,
        ma_max: int = 50,
        vol_len: int = 9,
        smooth_len: int = 3,
        er_len: int = 10,
        fast_bias: float = 0.30,
        noise_len: int = 20,
        noise_mult: float = 0.60,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("adaptive_supersmoother source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.ma_min = int(ma_min)
        self.ma_max = int(ma_max)
        self.vol_len = int(vol_len)
        self.smooth_len = int(smooth_len)
        self.er_len = int(er_len)
        self.fast_bias = float(fast_bias)
        self.noise_len = int(noise_len)
        self.noise_mult = float(noise_mult)
        if self.ma_min < 1 or self.ma_max < 2 or self.ma_min > self.ma_max:
            raise ValueError("adaptive_supersmoother needs 1 <= ma_min <= ma_max and ma_max >= 2")
        if self.vol_len < 2 or self.smooth_len < 3 or self.er_len < 2 or self.noise_len < 2:
            raise ValueError("adaptive_supersmoother: vol_len >= 2, smooth_len >= 3, er_len >= 2, noise_len >= 2")
        if not 0.0 <= self.fast_bias <= 1.0 or self.noise_mult < 0.0:
            raise ValueError("adaptive_supersmoother: fast_bias in [0, 1] and noise_mult >= 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "ma_min": self.ma_min,
            "ma_max": self.ma_max,
            "vol_len": self.vol_len,
            "smooth_len": self.smooth_len,
            "er_len": self.er_len,
            "fast_bias": self.fast_bias,
            "noise_len": self.noise_len,
            "noise_mult": self.noise_mult,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def trend(self, bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Return (trend, efficiency) arrays aligned with bars."""
        src_s = self._source(bars)
        s_src = src_s.to_numpy()
        n = len(s_src)

        def filled(k: int) -> np.ndarray:
            """src[t - k], with nz(src[k], src): the current source where that value is NaN."""
            arr = _shift(s_src, k)
            return np.where(np.isnan(arr), s_src, arr)

        delta = s_src - _shift(s_src, 1)
        sd = pd.Series(delta).rolling(self.vol_len).std(ddof=0).to_numpy()
        s_mean = pd.Series(sd).rolling(self.vol_len).mean().to_numpy()
        s_min = s_mean * 0.25
        s_max = s_mean * 1.75
        vol_range = s_max - s_min
        with np.errstate(invalid="ignore", divide="ignore"):
            vol_pos = np.where(vol_range > 0.0, np.maximum(0.0, np.minimum(1.0, (sd - s_min) / vol_range)), 0.0)
            length = np.where(
                sd <= s_min,
                self.ma_max,
                np.where(sd >= s_max, self.ma_min, self.ma_max - (self.ma_max - self.ma_min) * vol_pos),
            )
            alpha = 2.0 / (length + 1.0)

        adaptive = np.full(n, np.nan)
        prev = np.nan
        for t in range(n):
            cur = s_src[t] if np.isnan(prev) else prev + alpha[t] * (s_src[t] - prev)
            adaptive[t] = cur
            prev = cur

        # SuperSmoother coefficients, as in the script (fixed for the whole run).
        a1 = np.exp(-1.414 * np.pi / self.smooth_len)
        b1 = 2.0 * a1 * np.cos(1.414 * np.pi / self.smooth_len)
        c2 = b1
        c3 = -a1 * a1
        c1 = 1.0 - c2 - c3

        smooth = np.full(n, np.nan)
        for t in range(n):
            p1 = smooth[t - 1] if t >= 1 else np.nan
            p2 = smooth[t - 2] if t >= 2 else np.nan
            if np.isnan(p1) or np.isnan(p2):
                smooth[t] = adaptive[t]
            else:
                a_prev = adaptive[t - 1] if t >= 1 and not np.isnan(adaptive[t - 1]) else adaptive[t]
                smooth[t] = c1 * (adaptive[t] + a_prev) * 0.5 + c2 * p1 + c3 * p2

        direction = np.abs(s_src - filled(self.er_len))
        noise = np.zeros(n)
        for i in range(self.er_len):
            noise += np.abs(filled(i) - filled(i + 1))
        with np.errstate(invalid="ignore", divide="ignore"):
            eff = np.where(noise > 0.0, direction / noise, 0.0)
        eff = np.maximum(0.0, np.minimum(1.0, eff))

        fast_w = self.fast_bias + (1.0 - self.fast_bias) * eff
        slow_w = 1.0 - fast_w
        return adaptive * fast_w + smooth * slow_w, eff

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        trend, _ = self.trend(bars)
        slope = trend - _shift(trend, 1)
        slope_noise = _rma(np.abs(slope), self.noise_len)
        threshold = slope_noise * self.noise_mult

        out = np.zeros(len(trend), dtype=int)
        regime = 0  # `var int SQ = 0`
        for i in range(len(trend)):
            # NaN comparisons are false, so warm-up keeps the regime flat.
            if slope[i] > threshold[i]:
                regime = 1
            elif slope[i] < -threshold[i]:
                regime = -1
            out[i] = int(regime == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class AdxLifecycleTrail(Strategy):
    """Port of the Pine script "ADX Lifecycle Trail" (SchizoQuant), as a long/flat strategy.

    DMI: +DM/-DM from the bar-to-bar high and low moves; +DI/-DI = 100 * RMA(DM, dmi_len) / max(RMA(TR), mintick).
    Dominance = (+DI - -DI) / (+DI + -DI), 0 when the DI sum is not positive (so NaN warm-up gives 0).
    ADX = RMA(DX, dmi_len), DX = 100 * |+DI - -DI| / (+DI + -DI).
    Lifecycle = clamp((ADX - ADX[lifecycle_len]) / lifecycle_scale, -1, 1).
    Defence levels: three completed horizons (short, medium, long) of the prior bars' lows (highs).
    When the lifecycle is positive, the bullish defence moves from the medium low towards the long low;
    when negative, towards the short low. The bearish defence is the mirror image, on highs.
    Trail (starts bullish: dominance is 0 on the first bar): bullish regime trail = max(previous trail,
    bullish defence); bearish = min(previous trail, bearish defence). Flip to bullish when src > trail and
    dominance > dominance_level; flip to bearish when src < trail and dominance < -dominance_level.
    A flip resets the trail to src -/+ reset distance,
    where reset = max(ATR(atr_len), mintick) * reset_mult.
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    `mintick` stands in for Pine's syminfo.mintick.
    """

    name = "adx_lifecycle_trail"

    def __init__(
        self,
        source: str = "close",
        dmi_len: int = 17,
        dominance_level: float = 0.10,
        lifecycle_len: int = 4,
        lifecycle_scale: float = 8.0,
        short_len: int = 5,
        medium_len: int = 12,
        long_len: int = 24,
        atr_len: int = 14,
        reset_mult: float = 2.5,
        mintick: float = 0.01,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("adx_lifecycle_trail source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.dmi_len = int(dmi_len)
        self.dominance_level = float(dominance_level)
        self.lifecycle_len = int(lifecycle_len)
        self.lifecycle_scale = float(lifecycle_scale)
        self.short_len = int(short_len)
        self.medium_len = int(medium_len)
        self.long_len = int(long_len)
        self.atr_len = int(atr_len)
        self.reset_mult = float(reset_mult)
        self.mintick = float(mintick)
        if self.dmi_len < 2 or self.lifecycle_len < 1 or self.atr_len < 1:
            raise ValueError("adx_lifecycle_trail needs dmi_len >= 2, lifecycle_len >= 1, atr_len >= 1")
        if not 0.0 <= self.dominance_level <= 0.8 or self.lifecycle_scale < 0.5:
            raise ValueError("adx_lifecycle_trail: dominance_level in [0, 0.8], lifecycle_scale >= 0.5")
        if not 2 <= self.short_len < self.medium_len < self.long_len:
            raise ValueError("adx_lifecycle_trail needs 2 <= short_len < medium_len < long_len")
        if self.reset_mult < 0.1 or self.mintick <= 0:
            raise ValueError("adx_lifecycle_trail needs reset_mult >= 0.1 and mintick > 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "dmi_len": self.dmi_len,
            "dominance_level": self.dominance_level,
            "lifecycle_len": self.lifecycle_len,
            "lifecycle_scale": self.lifecycle_scale,
            "short_len": self.short_len,
            "medium_len": self.medium_len,
            "long_len": self.long_len,
            "atr_len": self.atr_len,
            "reset_mult": self.reset_mult,
            "mintick": self.mintick,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def _levels(self, bars: pd.DataFrame) -> dict[str, np.ndarray]:
        h = bars["high"].astype(float)
        lo = bars["low"].astype(float)
        c = bars["close"].astype(float)
        hv, lv = h.to_numpy(), lo.to_numpy()

        up_move = (h - h.shift(1).fillna(h)).to_numpy()
        down_move = (lo.shift(1).fillna(lo) - lo).to_numpy()
        plus_dm = np.where((up_move > down_move) & (up_move > 0.0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0.0), down_move, 0.0)

        pc = c.shift(1)
        tr = np.array(pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1), dtype=float)
        tr[0] = hv[0] - lv[0]
        smoothed_tr = np.maximum(_rma(tr, self.dmi_len), self.mintick)
        plus_di = 100.0 * _rma(plus_dm, self.dmi_len) / smoothed_tr
        minus_di = 100.0 * _rma(minus_dm, self.dmi_len) / smoothed_tr

        di_sum = plus_di + minus_di
        with np.errstate(invalid="ignore", divide="ignore"):
            dominance = np.where(di_sum > 0.0, (plus_di - minus_di) / di_sum, 0.0)
            dx = np.where(di_sum > 0.0, 100.0 * np.abs(plus_di - minus_di) / di_sum, 0.0)
        adx = _rma(dx, self.dmi_len)

        prev_adx = _shift(adx, self.lifecycle_len)
        adx_change = adx - np.where(np.isnan(prev_adx), adx, prev_adx)
        lifecycle = np.maximum(-1.0, np.minimum(1.0, adx_change / self.lifecycle_scale))

        def prior_extreme(arr: np.ndarray, length: int, fn: str) -> np.ndarray:
            """ta.lowest/highest(arr, length)[1], with nz fallback to the current bar."""
            roll = pd.Series(arr).rolling(length)
            prior = (roll.min() if fn == "min" else roll.max()).shift(1).to_numpy()
            return np.where(np.isnan(prior), arr, prior)

        short_low = prior_extreme(lv, self.short_len, "min")
        medium_low = prior_extreme(lv, self.medium_len, "min")
        long_low = prior_extreme(lv, self.long_len, "min")
        short_high = prior_extreme(hv, self.short_len, "max")
        medium_high = prior_extreme(hv, self.medium_len, "max")
        long_high = prior_extreme(hv, self.long_len, "max")

        pos = lifecycle >= 0.0
        bull_def = np.where(
            pos, medium_low + lifecycle * (long_low - medium_low), medium_low + (-lifecycle) * (short_low - medium_low)
        )
        bear_def = np.where(
            pos,
            medium_high + lifecycle * (long_high - medium_high),
            medium_high + (-lifecycle) * (short_high - medium_high),
        )

        atr = np.maximum(_rma(tr, self.atr_len), self.mintick)
        return {
            "dominance": dominance,
            "bull_def": bull_def,
            "bear_def": bear_def,
            "reset": atr * self.reset_mult,
            "close": c.to_numpy(),
            "high": hv,
            "low": lv,
        }

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        lv = self._levels(bars)
        src = self._source(bars).to_numpy()
        dom, bull_def, bear_def, reset = lv["dominance"], lv["bull_def"], lv["bear_def"], lv["reset"]
        n = len(src)

        out = np.zeros(n, dtype=int)
        sq = 1 if dom[0] >= 0.0 else -1  # `var int SQ = dominance >= 0 ? 1 : -1`
        trail = np.nan  # `var float trendTrail = na`
        for t in range(n):
            prev_sq = sq
            if trail == trail:
                prev_trail = trail
            else:
                prev_trail = src[t] - reset[t] if prev_sq == 1 else src[t] + reset[t]

            if prev_sq == 1:
                trail_t = _nmax(prev_trail, bull_def[t])
            else:
                trail_t = _nmin(prev_trail, bear_def[t])
            trail = trail_t

            is_long = prev_sq == -1 and src[t] > trail_t and dom[t] > self.dominance_level
            is_short = prev_sq == 1 and src[t] < trail_t and dom[t] < -self.dominance_level
            if is_long:
                sq = 1
                trail = src[t] - reset[t]
            elif is_short:
                sq = -1
                trail = src[t] + reset[t]
            else:
                sq = prev_sq
            out[t] = int(sq == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class KaufmanAdaptiveChannel(Strategy):
    """Port of the Pine script "Kaufman Adaptive Channel Trend" (SchizoQuant), as a long/flat strategy.

    Efficiency ratio ER = |src - src[er_len]| / sum of |src[i] - src[i+1]| over er_len bars, clamped to [0, 1].
    SC = (ER * (fast_sc - slow_sc) + slow_sc)^2, with fast_sc = 2/(fast+1) and slow_sc = 2/(slow+1)
    (the two lengths are sorted first). KAMA = KAMA[1] + SC * (src - KAMA[1]), re-seeded from src when NaN.
    Band distance = max(RMS(src - KAMA, band_len) * band_mult, ATR(atr_len) * band_floor), with RMA of the squared
    residual; NaN warm-up falls back to the current residual and current true range.
    Price channel: highest high / lowest low over channel_len bars, one bar late (nz falls back to the current bar).
    Structure weight = min(ER * structure_influence, 1); defence = (1 - w) * band + w * channel.
    Bullish defence = (1 - w) * lower band + w * channel low; bearish = (1 - w) * upper band + w * channel high.
    Trail: bullish regime trail = max(previous trail, bullish defence); bearish = min(previous trail, bearish defence).
    Flip: src > trail sets bullish; src < trail sets bearish. A flip resets the trail to src -/+ reset distance,
    where reset = max(ATR * reset_atr, band distance).
    Regime starts bullish (`var int SQ = src >= kama ? 1 : -1` on the first bar).
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    `mintick` stands in for Pine's syminfo.mintick.
    """

    name = "kaufman_adaptive_channel"

    def __init__(
        self,
        source: str = "close",
        er_len: int = 14,
        fast_len: int = 2,
        slow_len: int = 30,
        band_len: int = 20,
        band_mult: float = 2.0,
        band_floor: float = 0.7,
        channel_len: int = 22,
        structure_influence: float = 1.25,
        atr_len: int = 14,
        reset_atr: float = 1.5,
        mintick: float = 0.01,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("kaufman_adaptive_channel source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.er_len = int(er_len)
        self.fast_len = int(fast_len)
        self.slow_len = int(slow_len)
        self.band_len = int(band_len)
        self.band_mult = float(band_mult)
        self.band_floor = float(band_floor)
        self.channel_len = int(channel_len)
        self.structure_influence = float(structure_influence)
        self.atr_len = int(atr_len)
        self.reset_atr = float(reset_atr)
        self.mintick = float(mintick)
        if self.er_len < 2 or self.fast_len < 1 or self.slow_len < 2 or self.band_len < 2:
            raise ValueError("kaufman_adaptive_channel: er_len >= 2, fast_len >= 1, slow_len >= 2, band_len >= 2")
        if self.channel_len < 2 or self.atr_len < 1:
            raise ValueError("kaufman_adaptive_channel: channel_len >= 2 and atr_len >= 1")
        if self.band_mult < 0.1 or self.band_floor < 0.0 or self.reset_atr < 0.1:
            raise ValueError("kaufman_adaptive_channel: band_mult >= 0.1, band_floor >= 0, reset_atr >= 0.1")
        if not 0.0 <= self.structure_influence <= 2.0 or self.mintick <= 0:
            raise ValueError("kaufman_adaptive_channel: structure_influence in [0, 2] and mintick > 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "er_len": self.er_len,
            "fast_len": self.fast_len,
            "slow_len": self.slow_len,
            "band_len": self.band_len,
            "band_mult": self.band_mult,
            "band_floor": self.band_floor,
            "channel_len": self.channel_len,
            "structure_influence": self.structure_influence,
            "atr_len": self.atr_len,
            "reset_atr": self.reset_atr,
            "mintick": self.mintick,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def _levels(self, bars: pd.DataFrame) -> dict[str, np.ndarray]:
        src_s = self._source(bars)
        s = src_s.to_numpy()
        h = bars["high"].astype(float)
        lo = bars["low"].astype(float)
        c = bars["close"].astype(float)
        hv, lv = h.to_numpy(), lo.to_numpy()
        n = len(s)

        def filled(k: int) -> np.ndarray:
            arr = _shift(s, k)
            return np.where(np.isnan(arr), s, arr)

        net = np.abs(s - filled(self.er_len))
        total = np.zeros(n)
        for i in range(self.er_len):
            total += np.abs(filled(i) - filled(i + 1))
        with np.errstate(invalid="ignore", divide="ignore"):
            er = np.where(total > 0.0, net / total, 0.0)
        er = np.maximum(0.0, np.minimum(1.0, er))

        eff_fast, eff_slow = min(self.fast_len, self.slow_len), max(self.fast_len, self.slow_len)
        fast_sc = 2.0 / (eff_fast + 1.0)
        slow_sc = 2.0 / (eff_slow + 1.0)
        adaptive_sc = er * (fast_sc - slow_sc) + slow_sc
        sc = adaptive_sc * adaptive_sc

        kama = np.full(n, np.nan)
        prev = np.nan
        for t in range(n):
            cur = s[t] if np.isnan(prev) else prev + sc[t] * (s[t] - prev)
            kama[t] = cur
            prev = cur

        pc = c.shift(1)
        tr = np.array(pd.concat([h - lo, (h - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1), dtype=float)
        tr[0] = hv[0] - lv[0]
        atr_raw = _rma(tr, self.atr_len)
        atr = np.maximum(np.where(np.isnan(atr_raw), tr, atr_raw), self.mintick)

        resid = s - kama
        resid_sq = resid * resid
        power = _rma(resid_sq, self.band_len)
        rms = np.sqrt(np.maximum(np.where(np.isnan(power), resid_sq, power), 0.0))
        band_dist = np.maximum(rms * self.band_mult, atr * self.band_floor)
        upper = kama + band_dist
        lower = kama - band_dist

        ch_hi = pd.Series(hv).rolling(self.channel_len).max().shift(1).to_numpy()
        ch_lo = pd.Series(lv).rolling(self.channel_len).min().shift(1).to_numpy()
        channel_upper = np.where(np.isnan(ch_hi), hv, ch_hi)
        channel_lower = np.where(np.isnan(ch_lo), lv, ch_lo)

        struct_w = np.minimum(er * self.structure_influence, 1.0)
        band_w = 1.0 - struct_w
        return {
            "src": s,
            "kama": kama,
            "er": er,
            "struct_w": struct_w,
            "band_w": band_w,
            "band_dist": band_dist,
            "atr": atr,
            "upper": upper,
            "lower": lower,
            "channel_upper": channel_upper,
            "channel_lower": channel_lower,
        }

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        lv = self._levels(bars)
        s = lv["src"]
        bull_def = lv["band_w"] * lv["lower"] + lv["struct_w"] * lv["channel_lower"]
        bear_def = lv["band_w"] * lv["upper"] + lv["struct_w"] * lv["channel_upper"]
        reset = np.maximum(lv["atr"] * self.reset_atr, lv["band_dist"])
        n = len(s)

        out = np.zeros(n, dtype=int)
        sq = 1 if s[0] >= lv["kama"][0] else -1  # `var int SQ`, set on the first bar
        trail = np.nan
        for t in range(n):
            prev_sq = sq
            if trail == trail:
                prev_trail = trail
            else:
                prev_trail = s[t] - reset[t] if prev_sq == 1 else s[t] + reset[t]

            if prev_sq == 1:
                trail_t = _nmax(prev_trail, bull_def[t])
            else:
                trail_t = _nmin(prev_trail, bear_def[t])
            trail = trail_t

            is_long = prev_sq == -1 and s[t] > trail_t
            is_short = prev_sq == 1 and s[t] < trail_t
            if is_long:
                sq = 1
                trail = s[t] - reset[t]
            elif is_short:
                sq = -1
                trail = s[t] + reset[t]
            else:
                sq = prev_sq
            out[t] = int(sq == 1)
        return pd.Series(out, index=bars.index, dtype=int)


def _breakout_pressure(src: np.ndarray, upper: np.ndarray, lower: np.ndarray, tick: float) -> np.ndarray:
    """Pine `breakoutPressure`: position of src inside the channel, in [-1, 1] inside, saturating outside."""
    width = np.maximum(upper - lower, tick)
    mid = (upper + lower) * 0.5
    half = np.maximum(width * 0.5, tick)
    pos = (src - mid) / half
    with np.errstate(invalid="ignore", divide="ignore"):
        exc_hi = pos - 1.0
        exc_lo = pos + 1.0
        hi = 0.5 + 0.5 * (exc_hi / (1.0 + np.abs(exc_hi)))
        lo = -0.5 + 0.5 * (exc_lo / (1.0 + np.abs(exc_lo)))
    return np.where(pos > 1.0, hi, np.where(pos < -1.0, lo, pos * 0.5))


class AdaptiveBreakoutOscillator(Strategy):
    """Port of the Pine script "Adaptive Breakout Oscillator" (SchizoQuant), as a long/flat strategy.

    Three completed channels (highest high / lowest low over the prior short, medium and long lengths, one bar late).
    Each channel's breakout pressure is the position of src inside it, mapped to [-1, 1] and saturating outside.
    Compression = ratio / (1 + ratio) where ratio = RMA(width, comp_len) / width, clamped to [0, 1].
    Urgency = 0.5 + 0.5 |pressure|. Weight = min_weight + (1 - min_weight) * compression * urgency.
    Consensus = weighted mean of the pressures, clamped to [-1, 1].
    Dispersion = weighted mean absolute gap to consensus.
    Threshold = clamp(base_threshold + dispersion * adaptation, base_threshold, max_threshold).
    Oscillator = 100 * consensus; the bands are +/- 100 * threshold.
    Regime latch (starts from oscillator >= 0 on the first bar): oscillator > upper sets +1 (long);
    oscillator < lower sets -1 (flat). Warm-up NaN weights give consensus 0, as in the script.
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    `mintick` stands in for Pine's syminfo.mintick.
    """

    name = "adaptive_breakout_osc"

    def __init__(
        self,
        source: str = "close",
        short_len: int = 10,
        medium_len: int = 20,
        long_len: int = 40,
        comp_len: int = 50,
        min_weight: float = 0.15,
        base_threshold: float = 0.30,
        adaptation: float = 0.40,
        max_threshold: float = 0.65,
        mintick: float = 0.01,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("adaptive_breakout_osc source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.short_len = int(short_len)
        self.medium_len = int(medium_len)
        self.long_len = int(long_len)
        self.comp_len = int(comp_len)
        self.min_weight = float(min_weight)
        self.base_threshold = float(base_threshold)
        self.adaptation = float(adaptation)
        self.max_threshold = float(max_threshold)
        self.mintick = float(mintick)
        if not 2 <= self.short_len < self.medium_len < self.long_len or self.long_len < 4:
            raise ValueError("adaptive_breakout_osc needs 2 <= short_len < medium_len < long_len")
        if self.comp_len < 5:
            raise ValueError("adaptive_breakout_osc needs comp_len >= 5")
        if not 0.0 <= self.min_weight <= 1.0 or not 0.05 <= self.base_threshold <= 0.9:
            raise ValueError("adaptive_breakout_osc: min_weight in [0, 1], base_threshold in [0.05, 0.9]")
        if not 0.0 <= self.adaptation <= 1.0 or not 0.10 <= self.max_threshold <= 0.95 or self.mintick <= 0:
            raise ValueError("adaptive_breakout_osc: adaptation in [0, 1], max_threshold in [0.1, 0.95], mintick > 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "short_len": self.short_len,
            "medium_len": self.medium_len,
            "long_len": self.long_len,
            "comp_len": self.comp_len,
            "min_weight": self.min_weight,
            "base_threshold": self.base_threshold,
            "adaptation": self.adaptation,
            "max_threshold": self.max_threshold,
            "mintick": self.mintick,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def oscillator(self, bars: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (oscillator, upper, lower) arrays aligned with bars, on the script's 0-100 scale."""
        src = self._source(bars).to_numpy()
        h = bars["high"].astype(float)
        lo = bars["low"].astype(float)
        hv, lv = h.to_numpy(), lo.to_numpy()
        tick = self.mintick

        def channel(length: int) -> tuple[np.ndarray, np.ndarray]:
            hi_p = pd.Series(hv).rolling(length).max().shift(1).to_numpy()
            lo_p = pd.Series(lv).rolling(length).min().shift(1).to_numpy()
            return np.where(np.isnan(hi_p), hv, hi_p), np.where(np.isnan(lo_p), lv, lo_p)

        pressures, widths = [], []
        for length in (self.short_len, self.medium_len, self.long_len):
            hi_c, lo_c = channel(length)
            widths.append(np.maximum(hi_c - lo_c, tick))
            pressures.append(_breakout_pressure(src, hi_c, lo_c, tick))

        weights = []
        for width, pressure in zip(widths, pressures, strict=True):
            base = _rma(width, self.comp_len)  # NaN until seeded, as in the script
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio = np.where(width > 0.0, base / width, 1.0)
                comp = np.maximum(0.0, np.minimum(1.0, ratio / (1.0 + ratio)))
            urgency = 0.5 + 0.5 * np.abs(pressure)
            weights.append(self.min_weight + (1.0 - self.min_weight) * comp * urgency)

        total = weights[0] + weights[1] + weights[2]
        with np.errstate(invalid="ignore", divide="ignore"):
            consensus = np.where(
                total > 0.0,
                (pressures[0] * weights[0] + pressures[1] * weights[1] + pressures[2] * weights[2]) / total,
                0.0,
            )
            consensus = np.maximum(-1.0, np.minimum(1.0, consensus))
            disp = np.where(
                total > 0.0,
                (
                    np.abs(pressures[0] - consensus) * weights[0]
                    + np.abs(pressures[1] - consensus) * weights[1]
                    + np.abs(pressures[2] - consensus) * weights[2]
                )
                / total,
                0.0,
            )
        disp = np.maximum(0.0, np.minimum(1.0, disp))

        thr = self.base_threshold + disp * self.adaptation
        thr = np.maximum(self.base_threshold, np.minimum(self.max_threshold, thr))
        return consensus * 100.0, thr * 100.0, -thr * 100.0

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        osc, upper, lower = self.oscillator(bars)

        out = np.zeros(len(osc), dtype=int)
        regime = 1 if osc[0] >= 0.0 else -1  # `var int SQ = oscillator >= 0 ? 1 : -1`
        for i in range(len(osc)):
            # NaN comparisons are false, so an undefined oscillator keeps the regime.
            if osc[i] > upper[i]:
                regime = 1
            elif osc[i] < lower[i]:
                regime = -1
            out[i] = int(regime == 1)
        return pd.Series(out, index=bars.index, dtype=int)


class EhlersInstantTrend(Strategy):
    """Port of the Pine script "Ehlers Instant Trend" (SchizoQuant), as a long/flat strategy.

    Instantaneous trendline (Ehlers, 2-pole): for bars 0-6 it equals the seed (src + 2 src[1] + src[2]) / 4;
    after that, it = c0 src + c1 src[1] + c2 src[2] + c3 it[1] + c4 it[2] with the alpha-dependent coefficients
    from the script. Trigger = 2 it - it[2]; momentum = trigger - it.
    Defence distance = max(RMS(src - it, noise_len) * band_mult, ATR(atr_len) * min_atr).
    Bullish boundary = it - distance; bearish boundary = it + distance.
    Trail: bullish = max(previous trail, bullish boundary); bearish = min(previous trail, bearish boundary).
    Bullish flip: prior regime bearish, src > trail, and (momentum > 0 or src > it + ATR * reversal).
    Bearish flip: prior regime bullish, src < trail, and (momentum < 0 or src < it - ATR * reversal).
    On a flip the trail is set to min(bullish boundary, src - min distance)
    or max(bearish boundary, src + min distance).
    Regime starts bullish when src >= it on the first bar. Long while the regime is +1, flat otherwise.
    The engine trades the next open. Only past and present bars are used. `mintick` stands in for syminfo.mintick.
    """

    name = "ehlers_instant_trend"

    def __init__(
        self,
        source: str = "close",
        alpha: float = 0.12,
        noise_len: int = 20,
        band_mult: float = 2.7,
        atr_len: int = 14,
        min_atr: float = 0.8,
        reversal: float = 0.5,
        mintick: float = 0.01,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("ehlers_instant_trend source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.alpha = float(alpha)
        self.noise_len = int(noise_len)
        self.band_mult = float(band_mult)
        self.atr_len = int(atr_len)
        self.min_atr = float(min_atr)
        self.reversal = float(reversal)
        self.mintick = float(mintick)
        if not 0.02 <= self.alpha <= 0.5:
            raise ValueError("ehlers_instant_trend alpha must be in [0.02, 0.5]")
        if self.noise_len < 2 or self.atr_len < 1:
            raise ValueError("ehlers_instant_trend needs noise_len >= 2 and atr_len >= 1")
        if self.band_mult < 0.2 or self.min_atr < 0.1 or self.reversal < 0.0 or self.mintick <= 0:
            raise ValueError("ehlers_instant_trend: band_mult >= 0.2, min_atr >= 0.1, reversal >= 0, mintick > 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "alpha": self.alpha,
            "noise_len": self.noise_len,
            "band_mult": self.band_mult,
            "atr_len": self.atr_len,
            "min_atr": self.min_atr,
            "reversal": self.reversal,
            "mintick": self.mintick,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def _levels(self, bars: pd.DataFrame) -> dict[str, np.ndarray]:
        src_s = self._source(bars)
        s = src_s.to_numpy()
        n = len(s)

        def filled(k: int) -> np.ndarray:
            arr = _shift(s, k)
            return np.where(np.isnan(arr), s, arr)

        a = self.alpha
        a2 = a * a
        c0 = a - 0.25 * a2
        c1 = 0.50 * a2
        c2 = -(a - 0.75 * a2)
        c3 = 2.0 * (1.0 - a)
        c4 = -(1.0 - a) * (1.0 - a)

        seed = (s + 2.0 * filled(1) + filled(2)) / 4.0
        it = np.full(n, np.nan)
        for t in range(n):
            if t < 7:  # `if bar_index < 7`
                it[t] = seed[t]
            else:
                p1 = it[t - 1] if not np.isnan(it[t - 1]) else seed[t]
                p2 = it[t - 2] if not np.isnan(it[t - 2]) else seed[t]
                it[t] = c0 * s[t] + c1 * filled(1)[t] + c2 * filled(2)[t] + c3 * p1 + c4 * p2

        trigger = 2.0 * it - np.where(np.isnan(_shift(it, 2)), it, _shift(it, 2))
        momentum = trigger - it

        resid = s - it
        resid_sq = resid * resid
        power = _rma(resid_sq, self.noise_len)
        rms = np.sqrt(np.maximum(np.where(np.isnan(power), resid_sq, power), 0.0))

        bars_h = bars["high"].astype(float).to_numpy()
        bars_l = bars["low"].astype(float).to_numpy()
        prev_c = _shift(bars["close"].astype(float).to_numpy(), 1)
        tr = np.fmax(bars_h - bars_l, np.fmax(np.abs(bars_h - prev_c), np.abs(bars_l - prev_c)))
        tr[0] = bars_h[0] - bars_l[0]  # no previous close on the first bar
        atr_raw = _rma(tr, self.atr_len)
        atr = np.maximum(np.where(np.isnan(atr_raw), tr, atr_raw), self.mintick)

        defense = np.maximum(rms * self.band_mult, atr * self.min_atr)
        return {
            "src": s,
            "it": it,
            "momentum": momentum,
            "atr": atr,
            "defense": defense,
            "bull_b": it - defense,
            "bear_b": it + defense,
            "min_dist": atr * self.min_atr,
        }

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        lv = self._levels(bars)
        s, it, mom, atr = lv["src"], lv["it"], lv["momentum"], lv["atr"]
        defense, bull_b, bear_b, min_dist = lv["defense"], lv["bull_b"], lv["bear_b"], lv["min_dist"]
        n = len(s)

        out = np.zeros(n, dtype=int)
        sq = 1 if s[0] >= it[0] else -1  # `var int SQ = src >= instantTrend ? 1 : -1`
        trail = np.nan
        for t in range(n):
            prev_sq = sq
            if trail == trail:
                prev_trail = trail
            else:
                prev_trail = s[t] - defense[t] if prev_sq == 1 else s[t] + defense[t]

            if prev_sq == 1:
                trail = _nmax(prev_trail, bull_b[t])
            else:
                trail = _nmin(prev_trail, bear_b[t])

            bearish_mom = mom[t] < 0.0
            bullish_mom = mom[t] > 0.0
            strong_bear = s[t] < it[t] - atr[t] * self.reversal
            strong_bull = s[t] > it[t] + atr[t] * self.reversal
            is_short = prev_sq == 1 and s[t] < trail and (bearish_mom or strong_bear)
            is_long = prev_sq == -1 and s[t] > trail and (bullish_mom or strong_bull)

            if is_long:
                sq = 1
                trail = min(bull_b[t], s[t] - min_dist[t])
            elif is_short:
                sq = -1
                trail = max(bear_b[t], s[t] + min_dist[t])
            else:
                sq = prev_sq
            out[t] = int(sq == 1)
        return pd.Series(out, index=bars.index, dtype=int)


def _decycler(price: np.ndarray, period: int) -> np.ndarray:
    """Ehlers two-pole decycler, as in the script: price minus its high-pass part.

    The high-pass uses the script's own coefficients and is zero for bars 0 and 1 (bar_index >= 2 guard).
    """
    angle = 0.707 * 2.0 * np.pi / period
    alpha = (np.cos(angle) + np.sin(angle) - 1.0) / np.cos(angle)
    decay = 1.0 - alpha
    gain = (1.0 - alpha * 0.5) ** 2
    n = len(price)
    hp = np.zeros(n)
    out = np.zeros(n)
    for t in range(n):
        if t >= 2:
            h1 = hp[t - 1]
            h2 = hp[t - 2]
            hp[t] = gain * (price[t] - 2.0 * price[t - 1] + price[t - 2]) + 2.0 * decay * h1 - decay * decay * h2
        out[t] = price[t] - hp[t]
    return out


class DecyclerHighLowBreakout(Strategy):
    """Port of the Pine script "Decycler High-Low Breakout" (SchizoQuant), as a long/flat strategy.

    Decycler applied to high, low and close (two-pole high-pass, `period` cutoff). Channel = [min, max] of the three.
    ATR(atr_len) falls back to the tick size while NaN (as safeATR does, not the true range).
    Normalized slope = (decycler close - its value slope_len bars ago) / (safeATR * sqrt(slope_len)).
    Padding = safeATR * padding * (1 + breathing * strength), strength = clamp(+/- slope, 0, 2) on each side.
    Lower defence = channel low - bullish padding; upper defence = channel high + bearish padding.
    Breakouts: close below the lower defence, with a negative slope beyond slope_conf or a close below
    lower defence - override * ATR, flips bearish. Mirror image flips bullish.
    The regime is flat (SQ = 0) until the warm-up of max(period, atr_len, slope_len) bars is complete and
    ATR and the slope are defined. The first ready bar sets it from close vs the decycler close.
    Long while the regime is +1, flat otherwise. The engine trades the next open. Only past and present bars are used.
    `mintick` stands in for syminfo.mintick.
    """

    name = "decycler_hl_breakout"

    def __init__(
        self,
        source: str = "close",
        period: int = 115,
        atr_len: int = 14,
        padding: float = 0.1,
        slope_len: int = 3,
        slope_conf: float = 0.05,
        breathing: float = 0.5,
        override: float = 0.45,
        mintick: float = 0.01,
    ):
        if source not in ("open", "high", "low", "close", "hl2", "hlc3", "ohlc4"):
            raise ValueError("decycler_hl_breakout source must be one of open, high, low, close, hl2, hlc3, ohlc4")
        self.source = source
        self.period = int(period)
        self.atr_len = int(atr_len)
        self.padding = float(padding)
        self.slope_len = int(slope_len)
        self.slope_conf = float(slope_conf)
        self.breathing = float(breathing)
        self.override = float(override)
        self.mintick = float(mintick)
        if self.period < 6 or self.atr_len < 1 or self.slope_len < 1:
            raise ValueError("decycler_hl_breakout needs period >= 6, atr_len >= 1, slope_len >= 1")
        if not 0.0 <= self.padding <= 3.0 or not 0.0 <= self.slope_conf <= 1.0:
            raise ValueError("decycler_hl_breakout: padding in [0, 3], slope_conf in [0, 1]")
        if not 0.0 <= self.breathing <= 2.0 or not 0.0 <= self.override <= 3.0 or self.mintick <= 0:
            raise ValueError("decycler_hl_breakout: breathing in [0, 2], override in [0, 3], mintick > 0")

    def params(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "period": self.period,
            "atr_len": self.atr_len,
            "padding": self.padding,
            "slope_len": self.slope_len,
            "slope_conf": self.slope_conf,
            "breathing": self.breathing,
            "override": self.override,
            "mintick": self.mintick,
        }

    def _source(self, bars: pd.DataFrame) -> pd.Series:
        return _source_series(bars, self.source)

    def _levels(self, bars: pd.DataFrame) -> dict[str, np.ndarray]:
        hv = bars["high"].astype(float).to_numpy()
        lv = bars["low"].astype(float).to_numpy()
        cv = bars["close"].astype(float).to_numpy()
        n = len(cv)
        tick = self.mintick

        d_h = _decycler(hv, self.period)
        d_l = _decycler(lv, self.period)
        d_c = _decycler(cv, self.period)
        upper_ch = np.maximum(d_h, np.maximum(d_l, d_c))
        lower_ch = np.minimum(d_h, np.minimum(d_l, d_c))

        prev_c = _shift(cv, 1)
        tr = np.fmax(hv - lv, np.fmax(np.abs(hv - prev_c), np.abs(lv - prev_c)))
        tr[0] = hv[0] - lv[0]
        atr = _rma(tr, self.atr_len)  # NaN until seeded, as ta.atr is
        safe_atr = np.maximum(np.where(np.isnan(atr), tick, atr), tick)

        slope = d_c - _shift(d_c, self.slope_len)
        norm = slope / (safe_atr * np.sqrt(float(self.slope_len)))
        bull_s = np.minimum(np.maximum(norm, 0.0), 2.0)
        bear_s = np.minimum(np.maximum(-norm, 0.0), 2.0)

        bull_pad = safe_atr * self.padding * (1.0 + self.breathing * bull_s)
        bear_pad = safe_atr * self.padding * (1.0 + self.breathing * bear_s)
        lower_def = lower_ch - bull_pad
        upper_def = upper_ch + bear_pad
        bear_brk_lvl = lower_def - safe_atr * self.override
        bull_brk_lvl = upper_def + safe_atr * self.override

        bearish_slope = norm < -self.slope_conf
        bullish_slope = norm > self.slope_conf
        bearish_break = (cv < lower_def) & (bearish_slope | (cv < bear_brk_lvl))
        bullish_break = (cv > upper_def) & (bullish_slope | (cv > bull_brk_lvl))

        warmup = max(self.period, self.atr_len, self.slope_len)
        ready = (np.arange(n) >= warmup) & ~np.isnan(atr) & ~np.isnan(norm)
        return {
            "close": cv,
            "d_c": d_c,
            "bearish_break": bearish_break,
            "bullish_break": bullish_break,
            "ready": ready,
        }

    def signal(self, bars: pd.DataFrame) -> pd.Series:
        lv = self._levels(bars)
        cv, d_c = lv["close"], lv["d_c"]
        brk_bear, brk_bull, ready = lv["bearish_break"], lv["bullish_break"], lv["ready"]

        out = np.zeros(len(cv), dtype=int)
        sq = 0  # `var int SQ = 0`
        for t in range(len(cv)):
            if ready[t]:
                if sq == 0:
                    sq = 1 if cv[t] >= d_c[t] else -1
                elif sq == -1 and brk_bull[t]:
                    sq = 1
                elif sq == 1 and brk_bear[t]:
                    sq = -1
            out[t] = int(sq == 1)
        return pd.Series(out, index=bars.index, dtype=int)


REGISTRY: dict[str, type[Strategy]] = {
    s.name: s
    for s in (
        BuyAndHold,
        SmaCrossover,
        EmaCrossover,
        DonchianBreakout,
        RsiPullback,
        IbsReversion,
        PriceActionBreakout,
        HigherHighStructure,
        ChampionDailySetup,
        RmaAtrBands,
        ProjectedCrossover,
        DualMaSdOscillator,
        DoubleSmoothedMadTrend,
        AdaptiveEhlersPercentile,
        VolatilityAdaptiveTrend,
        MesaPhaseBandTrend,
        AdaptivePersistenceTrail,
        AdaptiveVidya,
        AdaptiveSuperSmoother,
        AdxLifecycleTrail,
        KaufmanAdaptiveChannel,
        AdaptiveBreakoutOscillator,
        EhlersInstantTrend,
        DecyclerHighLowBreakout,
    )
}


def make_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}")
    cls = REGISTRY[name]
    params = dict(params or {})
    accepted = list(inspect.signature(cls).parameters)
    bad = sorted(k for k in params if k not in accepted)
    if bad:
        raise ValueError(f"strategy {name!r}: unknown parameter(s) {bad}; accepted parameters: {accepted}")
    try:
        inspect.signature(cls).bind(**params)
    except TypeError as exc:
        raise ValueError(
            f"strategy {name!r}: invalid parameters {params}: {exc}; accepted parameters: {accepted}"
        ) from exc
    return cls(**params)
