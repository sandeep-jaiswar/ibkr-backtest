import math

import numpy as np
import pandas as pd
import pytest

from ibbt.portfolio import PortfolioConfig, portfolio_metrics, run_portfolio


def _frames(rows: dict[str, list[tuple[float, float, float, float]]], start="2024-01-02"):
    """rows: symbol -> list of (open, high, low, close) per day, all symbols on the same dates."""
    dates = pd.bdate_range(start, periods=len(next(iter(rows.values()))))

    def f(k):
        return pd.DataFrame({s: [r[k] for r in v] for s, v in rows.items()}, index=dates)

    return f(0), f(1), f(2), f(3)


def _signal(columns, dates, longs: dict[str, list[int]]):
    return pd.DataFrame({s: longs.get(s, [0] * len(dates)) for s in columns}, index=dates)


FLAT = (100.0, 100.0, 100.0, 100.0)


def test_config_rejects_slots_that_exceed_cash():
    with pytest.raises(ValueError, match="exceeds initial_cash"):
        PortfolioConfig(initial_cash=10_000, max_positions=6, position_size=2_000)


def test_config_rejects_bad_exit_rules():
    with pytest.raises(ValueError):
        PortfolioConfig(stop_pct=1.5)
    with pytest.raises(ValueError):
        PortfolioConfig(max_hold=0)


def test_at_most_five_positions_and_two_thousand_each():
    symbols = [f"S{i}" for i in range(8)]
    rows = {s: [FLAT] * 6 for s in symbols}
    o, h, lo, c = _frames(rows)
    sig = _signal(symbols, o.index, {s: [1, 1, 1, 1, 1, 1] for s in symbols})
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0)
    res = run_portfolio(o, h, lo, c, sig, cfg)

    assert res.exposure.max() == 5
    assert res.skipped_entries > 0  # three signals per day had no slot
    # Flat prices and no costs: equity never moves from the starting 10k.
    assert np.allclose(res.equity.to_numpy(), 10_000.0)
    assert res.trades.empty or res.trades["pnl"].abs().max() < 1e-9


def test_costs_and_sizing_on_one_round_trip():
    rows = {"A": [(100, 100, 100, 100), (100, 110, 100, 110), (110, 110, 110, 110)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})  # enter at day 1 open, exit at day 2 open
    cfg = PortfolioConfig(commission_bps=10, slippage_bps=10)  # 10 bps per side each
    res = run_portfolio(o, h, lo, c, sig, cfg)

    trade = res.trades.iloc[0]
    entry = 100 * 1.001  # open plus slippage
    exit_fill = 110 * 0.999  # next open is 110, minus slippage
    shares = 2_000 / (entry * 1.001)
    proceeds = shares * exit_fill * 0.999
    assert trade["entry_price"] == pytest.approx(entry)
    assert trade["exit_price"] == pytest.approx(exit_fill)
    assert trade["pnl"] == pytest.approx(proceeds - 2_000)
    assert res.equity.iloc[-1] == pytest.approx(cfg.initial_cash + proceeds - 2_000)


def test_signal_fills_on_next_open_not_same_bar():
    rows = {"A": [(50, 50, 50, 50), (60, 60, 60, 60), (70, 70, 70, 70)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})
    res = run_portfolio(o, h, lo, c, sig, PortfolioConfig(slippage_bps=0, commission_bps=0))
    assert res.trades.iloc[0]["entry_date"] == o.index[1]  # bar 0 signal fills at bar 1 open (60)
    assert res.trades.iloc[0]["entry_price"] == pytest.approx(60)


def test_stop_fills_at_stop_level_and_gap_fills_at_open():
    # Entry at 100 (open of day 1). Stop at -5% = 95. Day 2 trades down to 90 intraday: fill at 95.
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 90, 92), (92, 92, 92, 92)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1, 1]})
    res = run_portfolio(o, h, lo, c, sig, PortfolioConfig(stop_pct=0.05, slippage_bps=0, commission_bps=0))
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop"
    assert t["exit_price"] == pytest.approx(95)
    assert t["exit_date"] == o.index[2]

    # Gap: day 2 opens at 90, below the stop, so the fill is the open, not the stop.
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (90, 91, 89, 90), (90, 90, 90, 90)]}
    o, h, lo, c = _frames(rows)
    res = run_portfolio(
        o,
        h,
        lo,
        c,
        _signal(["A"], o.index, {"A": [1, 1, 1, 1]}),
        PortfolioConfig(stop_pct=0.05, slippage_bps=0, commission_bps=0),
    )
    assert res.trades.iloc[0]["exit_price"] == pytest.approx(90)


def test_stop_and_target_in_same_bar_assume_stop_first():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 120, 90, 100)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1]})
    res = run_portfolio(
        o, h, lo, c, sig, PortfolioConfig(stop_pct=0.05, target_pct=0.10, slippage_bps=0, commission_bps=0)
    )
    assert res.trades.iloc[0]["exit_reason"] == "stop"


def test_target_hit_and_time_stop():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 111, 99, 110), (110, 110, 110, 110)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1, 1]})
    res = run_portfolio(o, h, lo, c, sig, PortfolioConfig(target_pct=0.10, slippage_bps=0, commission_bps=0))
    assert res.trades.iloc[0]["exit_reason"] == "target"
    assert res.trades.iloc[0]["exit_price"] == pytest.approx(110)

    res = run_portfolio(o, h, lo, c, sig, PortfolioConfig(max_hold=2, slippage_bps=0, commission_bps=0))
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "time"
    assert t["bars_held"] == 2


def test_open_position_at_end_is_flagged_and_excluded_from_closed_stats():
    rows = {"A": [(100, 100, 100, 100), (100, 110, 100, 110)]}
    o, h, lo, c = _frames(rows)
    cfg = PortfolioConfig(slippage_bps=0, commission_bps=0)
    res = run_portfolio(o, h, lo, c, _signal(["A"], o.index, {"A": [1, 1]}), cfg)
    assert res.trades["open"].all()
    m = portfolio_metrics(res, cfg)
    assert m["round_trips"] == 0
    assert math.isnan(m["win_rate"])


def test_profit_factor_and_win_rate_on_closed_trades():
    # Trade 1: enter 100 (day 1 open), exit 110 (day 2 open) = +10%.
    # Trade 2: enter 100 (day 3 open), exit 95 (day 4 open) = -5%. Equal size, no costs.
    # Dollar PF = 0.10 / 0.05 = 2, win rate = 1 of 2.
    rows = {
        "A": [
            (100, 100, 100, 100),
            (100, 100, 100, 100),
            (110, 110, 110, 110),
            (100, 100, 100, 100),
            (95, 95, 95, 95),
            (95, 95, 95, 95),
        ]
    }
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 1, 0, 0, 0]})
    cfg = PortfolioConfig(slippage_bps=0, commission_bps=0)
    res = run_portfolio(o, h, lo, c, sig, cfg)
    m = portfolio_metrics(res, cfg)
    assert m["round_trips"] == 2
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["profit_factor"] == pytest.approx(2.0)


def test_unconstrained_takes_every_signal():
    symbols = [f"S{i}" for i in range(8)]
    rows = {s: [FLAT] * 4 for s in symbols}
    o, h, lo, c = _frames(rows)
    sig = _signal(symbols, o.index, {s: [1, 1, 1, 1] for s in symbols})
    res = run_portfolio(o, h, lo, c, sig, PortfolioConfig(max_positions=None))
    assert res.exposure.max() == 8
    assert res.skipped_entries == 0


def test_ranking_decides_who_gets_the_free_slot():
    symbols = ["A", "B"]
    rows = {s: [FLAT] * 3 for s in symbols}
    o, h, lo, c = _frames(rows)
    sig = _signal(symbols, o.index, {"A": [1, 1, 1], "B": [1, 1, 1]})
    cfg = PortfolioConfig(max_positions=1, position_size=2_000, min_position_size=1_000)
    rank = pd.DataFrame({"A": [5.0, 5.0, 5.0], "B": [1.0, 1.0, 1.0]}, index=o.index)
    res = run_portfolio(o, h, lo, c, sig, cfg, rank=rank)
    assert list(res.trades["symbol"]) == ["B"]  # lower score wins


def test_cash_check_skips_underfunded_entries():
    # Five 2k positions fill 10k. S0 is then stopped out at half its price: the 1k loss leaves 1k cash,
    # which is below min_position_size=1500, so S5 (ready on day 2) must be skipped, not sized down.
    names = ["S0", "S1", "S2", "S3", "S4", "S5"]
    rows = {s: [FLAT] * 4 for s in names}
    rows["S0"] = [(100, 100, 100, 100), (100, 100, 100, 100), (50, 50, 50, 50), (50, 50, 50, 50)]
    o, h, lo, c = _frames(rows)
    sig = _signal(
        names,
        o.index,
        {"S0": [1, 0, 0, 0], "S1": [1] * 4, "S2": [1] * 4, "S3": [1] * 4, "S4": [1] * 4, "S5": [0, 1, 1, 1]},
    )
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0, min_position_size=1_500)
    res = run_portfolio(o, h, lo, c, sig, cfg)
    assert "S5" not in set(res.trades["symbol"])
    assert res.skipped_entries == 2  # S5 wanted a slot on day 2 and again on day 3; both refused
    s0 = res.trades[res.trades["symbol"] == "S0"].iloc[0]
    assert s0["pnl"] == pytest.approx(-1_000)


def test_nan_bars_are_not_traded_and_close_carries_forward():
    rows = {"A": [(100, 100, 100, 100), (np.nan, np.nan, np.nan, np.nan), (105, 105, 105, 105)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1]})
    res = run_portfolio(o, h, lo, c, sig, PortfolioConfig(commission_bps=0, slippage_bps=0))
    assert res.trades.empty or res.trades["exit_price"].isna().sum() == 0
    assert np.isfinite(res.equity).all()


def test_level_based_stop_and_target_come_from_the_signal_bar():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 130, 99, 120)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})  # pulse on day 0 -> entry at day 1 open
    stop = pd.DataFrame({"A": [95.0, np.nan, np.nan]}, index=o.index)
    target = pd.DataFrame({"A": [115.0, np.nan, np.nan]}, index=o.index)
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0, signal_exit=False)
    res = run_portfolio(o, h, lo, c, sig, cfg, stop_levels=stop, target_levels=target)
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "target"  # day 2 high 130 >= 115 target; the low 99 never reaches the 95 stop
    assert t["exit_price"] == pytest.approx(115)


def test_level_stop_above_fill_skips_the_entry():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})
    stop = pd.DataFrame({"A": [101.0, np.nan, np.nan]}, index=o.index)  # stop above the fill: invalid
    res = run_portfolio(
        o, h, lo, c, sig, PortfolioConfig(commission_bps=0, slippage_bps=0, signal_exit=False), stop_levels=stop
    )
    assert res.trades.empty
    assert res.skipped_entries == 1


def test_signal_exit_off_keeps_position_when_signal_drops():
    rows = {"A": [(100, 100, 100, 100)] * 4}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0, 0]})
    on = run_portfolio(o, h, lo, c, sig, PortfolioConfig(commission_bps=0, slippage_bps=0))
    off = run_portfolio(o, h, lo, c, sig, PortfolioConfig(commission_bps=0, slippage_bps=0, signal_exit=False))
    assert on.trades.iloc[0]["exit_reason"] == "signal"
    assert off.trades["open"].all() and len(off.trades) == 1  # still held at the end


def _ohlc(closes, spread=1.0):
    idx = pd.bdate_range("2018-01-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": c + spread, "low": c - spread, "close": c}, index=idx)


def test_price_action_rejects_falling_knives_and_lower_lows():
    from ibbt.strategies import PriceActionBreakout

    falling = _ohlc(np.linspace(200, 80, 400))  # steady decline: below the 200-day average, lower lows
    assert PriceActionBreakout().signal(falling).sum() == 0


def test_price_action_fires_on_breakout_in_an_uptrend():
    from ibbt.strategies import PriceActionBreakout

    up = np.concatenate([np.linspace(50, 150, 300), np.full(30, 150.0)])
    bars = _ohlc(up, spread=0.5)
    bars.iloc[-1, bars.columns.get_loc("high")] = 160.0  # a new high closed in the upper half
    bars.iloc[-1, bars.columns.get_loc("close")] = 158.0
    bars.iloc[-1, bars.columns.get_loc("open")] = 151.0
    bars.iloc[-1, bars.columns.get_loc("low")] = 150.5
    strat = PriceActionBreakout(breakout_lookback=20, max_risk=0.5)
    sig = strat.signal(bars)
    assert sig.iloc[-1] == 1
    levels = strat.levels(bars)
    assert levels["stop"].iloc[-1] < bars["close"].iloc[-1] < levels["target"].iloc[-1]


def test_gap_up_through_the_target_skips_the_entry():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})
    stop = pd.DataFrame({"A": [95.0, np.nan, np.nan]}, index=o.index)
    target = pd.DataFrame({"A": [99.0, np.nan, np.nan]}, index=o.index)  # target below the fill: already through it
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0, signal_exit=False)
    res = run_portfolio(o, h, lo, c, sig, cfg, stop_levels=stop, target_levels=target)
    assert res.trades.empty
    assert res.skipped_entries == 1


def test_fill_risk_above_limit_skips_the_entry():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)]}
    o, h, lo, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})
    stop = pd.DataFrame({"A": [90.0, np.nan, np.nan]}, index=o.index)  # 10% risk at the fill
    target = pd.DataFrame({"A": [120.0, np.nan, np.nan]}, index=o.index)
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0, signal_exit=False, fill_max_risk=0.05)
    res = run_portfolio(o, h, lo, c, sig, cfg, stop_levels=stop, target_levels=target)
    assert res.trades.empty
    assert res.skipped_entries == 1


def test_price_action_fires_on_support_bounce():
    from ibbt.strategies import PriceActionBreakout

    bars = _ohlc(np.concatenate([np.linspace(50, 150, 300), np.full(30, 150.0)]), spread=4.0)
    last = bars.index[-1]
    bars.loc[last, ["open", "high", "low", "close"]] = [
        149.0,
        151.5,
        146.5,
        151.0,
    ]  # tests 146 support, reclaims, bullish
    strat = PriceActionBreakout()
    assert strat.signal(bars).loc[last] == 1
    lv = strat.levels(bars).loc[last]
    assert lv["stop"] < 151.0 < lv["target"]


def test_price_action_legs_split_the_trigger():
    import pytest as _pt

    from ibbt.strategies import PriceActionBreakout

    with _pt.raises(ValueError):
        PriceActionBreakout(leg="sideways")
    up = np.concatenate([np.linspace(50, 150, 300), np.full(30, 150.0)])
    bars = _ohlc(up, spread=4.0)
    last = bars.index[-1]
    bars.loc[last, ["open", "high", "low", "close"]] = [149.0, 151.5, 146.5, 151.0]  # a bounce bar
    both = PriceActionBreakout().signal(bars)
    bounce = PriceActionBreakout(leg="bounce").signal(bars)
    breakout = PriceActionBreakout(leg="breakout").signal(bars)
    assert (both == (bounce | breakout)).all()
    assert bounce.loc[last] == 1 and breakout.loc[last] == 0
