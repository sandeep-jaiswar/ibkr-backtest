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
    o, h, l, c = _frames(rows)
    sig = _signal(symbols, o.index, {s: [1, 1, 1, 1, 1, 1] for s in symbols})
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0)
    res = run_portfolio(o, h, l, c, sig, cfg)

    assert res.exposure.max() == 5
    assert res.skipped_entries > 0  # three signals per day had no slot
    # Flat prices and no costs: equity never moves from the starting 10k.
    assert np.allclose(res.equity.to_numpy(), 10_000.0)
    assert res.trades.empty or res.trades["pnl"].abs().max() < 1e-9


def test_costs_and_sizing_on_one_round_trip():
    rows = {"A": [(100, 100, 100, 100), (100, 110, 100, 110), (110, 110, 110, 110)]}
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})  # enter at day 1 open, exit at day 2 open
    cfg = PortfolioConfig(commission_bps=10, slippage_bps=10)  # 10 bps per side each
    res = run_portfolio(o, h, l, c, sig, cfg)

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
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 0]})
    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(slippage_bps=0, commission_bps=0))
    assert res.trades.iloc[0]["entry_date"] == o.index[1]  # bar 0 signal fills at bar 1 open (60)
    assert res.trades.iloc[0]["entry_price"] == pytest.approx(60)


def test_stop_fills_at_stop_level_and_gap_fills_at_open():
    # Entry at 100 (open of day 1). Stop at -5% = 95. Day 2 trades down to 90 intraday: fill at 95.
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 90, 92), (92, 92, 92, 92)]}
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1, 1]})
    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(stop_pct=0.05, slippage_bps=0, commission_bps=0))
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop"
    assert t["exit_price"] == pytest.approx(95)
    assert t["exit_date"] == o.index[2]

    # Gap: day 2 opens at 90, below the stop, so the fill is the open, not the stop.
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (90, 91, 89, 90), (90, 90, 90, 90)]}
    o, h, l, c = _frames(rows)
    res = run_portfolio(o, h, l, c, _signal(["A"], o.index, {"A": [1, 1, 1, 1]}), PortfolioConfig(stop_pct=0.05, slippage_bps=0, commission_bps=0))
    assert res.trades.iloc[0]["exit_price"] == pytest.approx(90)


def test_stop_and_target_in_same_bar_assume_stop_first():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 120, 90, 100)]}
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1]})
    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(stop_pct=0.05, target_pct=0.10, slippage_bps=0, commission_bps=0))
    assert res.trades.iloc[0]["exit_reason"] == "stop"


def test_target_hit_and_time_stop():
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (100, 111, 99, 110), (110, 110, 110, 110)]}
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1, 1]})
    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(target_pct=0.10, slippage_bps=0, commission_bps=0))
    assert res.trades.iloc[0]["exit_reason"] == "target"
    assert res.trades.iloc[0]["exit_price"] == pytest.approx(110)

    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(max_hold=2, slippage_bps=0, commission_bps=0))
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "time"
    assert t["bars_held"] == 2


def test_open_position_at_end_is_flagged_and_excluded_from_closed_stats():
    rows = {"A": [(100, 100, 100, 100), (100, 110, 100, 110)]}
    o, h, l, c = _frames(rows)
    cfg = PortfolioConfig(slippage_bps=0, commission_bps=0)
    res = run_portfolio(o, h, l, c, _signal(["A"], o.index, {"A": [1, 1]}), cfg)
    assert res.trades["open"].all()
    m = portfolio_metrics(res, cfg)
    assert m["round_trips"] == 0
    assert math.isnan(m["win_rate"])


def test_profit_factor_and_win_rate_on_closed_trades():
    # Trade 1: enter 100 (day 1 open), exit 110 (day 2 open) = +10%.
    # Trade 2: enter 100 (day 3 open), exit 95 (day 4 open) = -5%. Equal size, no costs.
    # Dollar PF = 0.10 / 0.05 = 2, win rate = 1 of 2.
    rows = {"A": [(100, 100, 100, 100), (100, 100, 100, 100), (110, 110, 110, 110), (100, 100, 100, 100), (95, 95, 95, 95), (95, 95, 95, 95)]}
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 0, 1, 0, 0, 0]})
    cfg = PortfolioConfig(slippage_bps=0, commission_bps=0)
    res = run_portfolio(o, h, l, c, sig, cfg)
    m = portfolio_metrics(res, cfg)
    assert m["round_trips"] == 2
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["profit_factor"] == pytest.approx(2.0)


def test_unconstrained_takes_every_signal():
    symbols = [f"S{i}" for i in range(8)]
    rows = {s: [FLAT] * 4 for s in symbols}
    o, h, l, c = _frames(rows)
    sig = _signal(symbols, o.index, {s: [1, 1, 1, 1] for s in symbols})
    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(max_positions=None))
    assert res.exposure.max() == 8
    assert res.skipped_entries == 0


def test_ranking_decides_who_gets_the_free_slot():
    symbols = ["A", "B"]
    rows = {s: [FLAT] * 3 for s in symbols}
    o, h, l, c = _frames(rows)
    sig = _signal(symbols, o.index, {"A": [1, 1, 1], "B": [1, 1, 1]})
    cfg = PortfolioConfig(max_positions=1, position_size=2_000, min_position_size=1_000)
    rank = pd.DataFrame({"A": [5.0, 5.0, 5.0], "B": [1.0, 1.0, 1.0]}, index=o.index)
    res = run_portfolio(o, h, l, c, sig, cfg, rank=rank)
    assert list(res.trades["symbol"]) == ["B"]  # lower score wins


def test_cash_check_skips_underfunded_entries():
    # Five 2k positions fill 10k. S0 is then stopped out at half its price: the 1k loss leaves 1k cash,
    # which is below min_position_size=1500, so S5 (ready on day 2) must be skipped, not sized down.
    names = ["S0", "S1", "S2", "S3", "S4", "S5"]
    rows = {s: [FLAT] * 4 for s in names}
    rows["S0"] = [(100, 100, 100, 100), (100, 100, 100, 100), (50, 50, 50, 50), (50, 50, 50, 50)]
    o, h, l, c = _frames(rows)
    sig = _signal(
        names,
        o.index,
        {"S0": [1, 0, 0, 0], "S1": [1] * 4, "S2": [1] * 4, "S3": [1] * 4, "S4": [1] * 4, "S5": [0, 1, 1, 1]},
    )
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0, min_position_size=1_500)
    res = run_portfolio(o, h, l, c, sig, cfg)
    assert "S5" not in set(res.trades["symbol"])
    assert res.skipped_entries == 2  # S5 wanted a slot on day 2 and again on day 3; both refused
    s0 = res.trades[res.trades["symbol"] == "S0"].iloc[0]
    assert s0["pnl"] == pytest.approx(-1_000)


def test_nan_bars_are_not_traded_and_close_carries_forward():
    rows = {"A": [(100, 100, 100, 100), (np.nan, np.nan, np.nan, np.nan), (105, 105, 105, 105)]}
    o, h, l, c = _frames(rows)
    sig = _signal(["A"], o.index, {"A": [1, 1, 1]})
    res = run_portfolio(o, h, l, c, sig, PortfolioConfig(commission_bps=0, slippage_bps=0))
    assert res.trades.empty or res.trades["exit_price"].isna().sum() == 0
    assert np.isfinite(res.equity).all()
