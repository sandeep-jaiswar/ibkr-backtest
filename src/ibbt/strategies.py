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
            raise ValueError("adaptive_ehlers_percentile source must be one of open, high, low, close, hl2, hlc3, ohlc4")
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
            raise ValueError("adaptive_ehlers_percentile: vol_len, filter_len >= 2, momentum_len >= 1, percentile_len >= 2")
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
        ji = (0.0962 * i1_t + 0.5769 * back(i1, 2, 0.0) - 0.5769 * back(i1, 4, 0.0) - 0.0962 * back(i1, 6, 0.0)) * pf
        jq = (0.0962 * q1_t + 0.5769 * back(q1, 2, 0.0) - 0.5769 * back(q1, 4, 0.0) - 0.0962 * back(q1, 6, 0.0)) * pf

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
            raise ValueError("adaptive_persistence_trail source must be one of open, high, low, close, hl2, hlc3, ohlc4")
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
    )
}


def make_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(REGISTRY)}")
    return REGISTRY[name](**(params or {}))
