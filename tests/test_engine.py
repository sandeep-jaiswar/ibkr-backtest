import math

import pandas as pd
import pytest

from ibbt.engine import BacktestConfig, run_backtest
from ibbt.metrics import compute_metrics


def _bars(opens, closes):
    idx = pd.bdate_range("2024-01-01", periods=len(opens))
    return pd.DataFrame({"open": opens, "close": closes}, index=idx)


def test_signal_fills_at_next_open_not_same_bar_close():
    bars = _bars(opens=[100, 101, 102, 103, 104], closes=[100, 101, 102, 103, 104])
    # Signal goes long at bar 0's close and flat at bar 1's close.
    signal = pd.Series([1, 0, 0, 0, 0], index=bars.index)

    result = run_backtest(bars, signal, BacktestConfig(commission_bps=0, slippage_bps=0))

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["entry_price"] == pytest.approx(101)  # open of bar 1, not bar 0's close
    assert trade["exit_price"] == pytest.approx(102)   # open of bar 2
    assert not trade["open"]


def test_costs_reduce_round_trip_pnl():
    bars = _bars(opens=[100, 100, 100, 100], closes=[100, 100, 100, 100])
    signal = pd.Series([1, 1, 0, 0], index=bars.index)

    free = run_backtest(bars, signal, BacktestConfig(commission_bps=0, slippage_bps=0))
    costly = run_backtest(bars, signal, BacktestConfig(commission_bps=10, slippage_bps=10))

    assert free.equity.iloc[-1] == pytest.approx(100_000)
    assert costly.equity.iloc[-1] < free.equity.iloc[-1]


def test_open_position_is_marked_and_flagged_at_end():
    bars = _bars(opens=[100, 110, 120], closes=[100, 110, 120])
    signal = pd.Series([1, 1, 1], index=bars.index)

    result = run_backtest(bars, signal, BacktestConfig(commission_bps=0, slippage_bps=0))

    assert len(result.trades) == 1
    assert bool(result.trades.iloc[0]["open"]) is True
    assert result.equity.iloc[-1] == pytest.approx(100_000 * 120 / 110)


def test_flat_signal_never_trades():
    bars = _bars(opens=[1, 2, 3], closes=[1, 2, 3])
    result = run_backtest(bars, pd.Series(0, index=bars.index), BacktestConfig())
    assert result.trades.empty
    assert (result.equity == BacktestConfig().initial_cash).all()
    assert result.position.sum() == 0


def test_max_drawdown_and_round_trips():
    equity = pd.Series([100, 120, 90, 110], index=pd.bdate_range("2024-01-01", periods=4))
    position = pd.Series([1, 1, 1, 1], index=equity.index)
    trades = pd.DataFrame(columns=["entry_date", "entry_price", "exit_date", "exit_price", "pnl_pct", "open"])

    metrics = compute_metrics(equity, trades, position)

    assert metrics["max_drawdown"] == pytest.approx(90 / 120 - 1)
    assert metrics["round_trips"] == 0
    assert math.isnan(metrics["win_rate"])
    assert metrics["time_in_market"] == 1.0


def test_sharpe_is_nan_for_constant_equity():
    equity = pd.Series(100.0, index=pd.bdate_range("2024-01-01", periods=10))
    position = pd.Series(0, index=equity.index)
    trades = pd.DataFrame(columns=["entry_date", "entry_price", "exit_date", "exit_price", "pnl_pct", "open"])
    assert math.isnan(compute_metrics(equity, trades, position)["sharpe"])
