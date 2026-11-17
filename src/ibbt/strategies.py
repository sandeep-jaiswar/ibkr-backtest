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
        c1_prev = c1.shift(1).infer_objects(copy=False).fillna(False).astype(bool)
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


def _rma(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's moving average, matching Pine's `ta.rma` (alpha = 1/n)."""
    return _seeded_average(x, n, 1.0 / n)


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    """Exponential moving average, matching Pine's `ta.ema` (alpha = 2/(n+1)), seeded like `_rma`."""
    return _seeded_average(x, n, 2.0 / (n + 1))


def _seeded_average(x: np.ndarray, n: int, alpha: float) -> np.ndarray:
    """Pine-style recursive average.

    Seeded with the simple average of the first `n` finite values, then
    avg_t = avg_{t-1} + alpha * (x_t - avg_{t-1}). NaN inputs are skipped and leave the average unchanged.
    """
    out = np.full(len(x), np.nan)
    finite = np.flatnonzero(np.isfinite(x))
    if len(finite) < n:
        return out
    seed_pos = finite[n - 1]  # the bar where n finite values are available
    prev = float(np.mean(x[finite[:n]]))
    out[seed_pos] = prev
    for i in range(seed_pos + 1, len(x)):
        if np.isfinite(x[i]):
            prev = alpha * x[i] + (1 - alpha) * prev
            out[i] = prev
    return out


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
        o, h, lo, c = (bars[k].astype(float) for k in ("open", "high", "low", "close"))
        return {
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "hl2": (h + lo) / 2,
            "hlc3": (h + lo + c) / 3,
            "ohlc4": (o + h + lo + c) / 4,
        }[self.source]

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
        o, h, lo, c = (bars[k].astype(float) for k in ("open", "high", "low", "close"))
        return {
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "hl2": (h + lo) / 2,
            "hlc3": (h + lo + c) / 3,
            "ohlc4": (o + h + lo + c) / 4,
        }[self.source]

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
        o, h, lo, c = (bars[k].astype(float) for k in ("open", "high", "low", "close"))
        return {
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "hl2": (h + lo) / 2,
            "hlc3": (h + lo + c) / 3,
            "ohlc4": (o + h + lo + c) / 4,
        }[self.source]

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
    )
}


def make_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))
