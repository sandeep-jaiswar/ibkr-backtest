import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ibbt.config import Settings
from ibbt.engine import BacktestConfig, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.runner import run_and_record
from ibbt.store import Store
from ibbt.strategies import BuyAndHold, make_strategy
from ibbt.synthetic import synthetic_bars
from ibbt.validation import (
    benchmark_metrics,
    excess_return,
    overfit_warning,
    walk_forward_eval,
    walk_forward_splits,
)

CFG = BacktestConfig(commission_bps=5, slippage_bps=5)
# The last entry is invalid (slow <= fast) and must be skipped, not raise.
GRID = [
    {"fast": 5, "slow": 20},
    {"fast": 10, "slow": 50},
    {"fast": 20, "slow": 100},
    {"fast": 50, "slow": 10},
]


def _bars():
    return synthetic_bars("2015-01-01", "2024-12-31").set_index("ts")


def _test_index(bars, test_slice):
    return bars.loc[test_slice].index


def test_benchmark_is_buy_and_hold_through_the_same_engine():
    bars = _bars()
    result = run_backtest(bars, BuyAndHold().signal(bars), CFG)
    expected = compute_metrics(result.equity, result.trades, result.position)
    assert benchmark_metrics(bars, CFG)["total_return"] == pytest.approx(expected["total_return"])


def test_excess_return_is_strategy_minus_benchmark_total_return():
    assert excess_return({"total_return": 0.20}, {"total_return": 0.05}) == pytest.approx(0.15)
    assert excess_return({"total_return": -0.10}, {"total_return": 0.05}) == pytest.approx(-0.15)


def test_splits_order_train_before_test_and_never_overlap():
    bars = _bars()
    splits = walk_forward_splits(bars.index, n_folds=3, train_years=3, test_years=1)

    assert len(splits) == 3
    seen: set[pd.Timestamp] = set()
    for train, test in splits:
        assert isinstance(train.start, pd.Timestamp) and isinstance(test.stop, pd.Timestamp)
        train_idx = bars.loc[train].index
        test_idx = _test_index(bars, test)
        assert train_idx.max() < test_idx.min()  # train ends before test starts
        assert not seen.intersection(test_idx)  # test windows never overlap
        seen.update(test_idx)

    # The test windows tile up to the final bar.
    assert max(seen) == bars.index[-1]


def test_splits_reject_insufficient_history():
    bars = _bars()
    with pytest.raises(ValueError):
        walk_forward_splits(bars.index, n_folds=3, train_years=9, test_years=1)


def _windowed_expected(bars, strategy, window):
    """Signal over `window` from history up to its end, then the backtest on the window's bars."""
    window_bars = bars.loc[window]
    signal = strategy.signal(bars.loc[: window.stop]).loc[window]
    result = run_backtest(window_bars, signal, CFG)
    return compute_metrics(result.equity, result.trades, result.position)


def test_walk_forward_eval_picks_best_train_sharpe_and_scores_test_only():
    bars = _bars()
    splits = walk_forward_splits(bars.index, 3, 3, 1)
    out = walk_forward_eval(bars, "sma_crossover", GRID, CFG, 3, 3, 1)

    assert len(out) == 3
    assert (out["train_end"] < out["test_start"]).all()

    for k, (train_sl, test_sl) in enumerate(splits):
        train_sharpes = {}
        for params in GRID[:3]:
            metrics = _windowed_expected(bars, make_strategy("sma_crossover", params), train_sl)
            train_sharpes[(params["fast"], params["slow"])] = metrics["sharpe"]
        best = max((sharpe, key) for key, sharpe in train_sharpes.items() if not math.isnan(sharpe))[1]
        assert (int(out.loc[k, "fast"]), int(out.loc[k, "slow"])) == best

        # Out-of-sample metrics: the chosen params' signal over the test window, computed from
        # history up to the test end, then backtested on the test window's bars.
        chosen = make_strategy("sma_crossover", {"fast": best[0], "slow": best[1]})
        expected = _windowed_expected(bars, chosen, test_sl)
        assert out.loc[k, "oos_total_return"] == pytest.approx(expected["total_return"])
        assert out.loc[k, "oos_sharpe"] == pytest.approx(expected["sharpe"])


def _cyclic_bars(n: int = 1300, period: int = 150) -> pd.DataFrame:
    """Business-day bars with a sine-wave close. Fast/slow SMA crossovers recur every few months."""
    dates = pd.bdate_range("2019-01-01", periods=n)
    t = np.arange(n)
    close = 100 + 20 * np.sin(2 * np.pi * t / period)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6},
        index=pd.DatetimeIndex(dates, name="ts"),
    )


def test_warmup_history_lets_slow_strategy_trade_inside_the_test_window():
    bars = _cyclic_bars()
    params = {"fast": 50, "slow": 200}
    out = walk_forward_eval(bars, "sma_crossover", [params], CFG, 1, 3, 1)
    _, test_sl = walk_forward_splits(bars.index, 1, 3, 1)[0]

    # The 200-bar slow SMA needs warm-up. Computed from the test bars alone (the old behaviour),
    # the 50/200 crossover produces no trade in this window.
    test_bars = bars.loc[test_sl]
    old = run_backtest(test_bars, make_strategy("sma_crossover", params).signal(test_bars), CFG)
    assert compute_metrics(old.equity, old.trades, old.position)["round_trips"] == 0

    # With history before the window visible, the same window contains a round trip.
    assert out.loc[0, "oos_round_trips"] >= 1


def test_oos_result_ignores_bars_after_the_test_window_end():
    bars = _cyclic_bars()
    grid = [{"fast": 50, "slow": 200}]
    out = walk_forward_eval(bars, "sma_crossover", grid, CFG, 1, 3, 1)

    # Replace every price after the test window with a different series. The fold's signal and
    # backtest must not see any of it, so the OOS metrics stay identical.
    tampered = bars.copy()
    later = tampered.index > out.loc[0, "test_end"]
    tampered.loc[later, ["open", "high", "low", "close"]] *= 0.5
    tampered_out = walk_forward_eval(tampered, "sma_crossover", grid, CFG, 1, 3, 1)

    oos_cols = [c for c in out.columns if c.startswith("oos_")]
    pd.testing.assert_frame_equal(out[oos_cols], tampered_out[oos_cols])


def test_train_fit_ignores_bars_after_the_train_end():
    bars = _cyclic_bars()
    out = walk_forward_eval(bars, "sma_crossover", GRID, CFG, 1, 3, 1)

    # Alter only bars inside the test window (after the train end). Fitting must not see them, so
    # the chosen params and the train Sharpe are unchanged.
    tampered = bars.copy()
    inside_test = (tampered.index > out.loc[0, "train_end"]) & (tampered.index <= out.loc[0, "test_end"])
    tampered.loc[inside_test, ["open", "high", "low", "close"]] *= 3
    tampered_out = walk_forward_eval(tampered, "sma_crossover", GRID, CFG, 1, 3, 1)

    fit_cols = ["fold", "train_start", "train_end", "fast", "slow", "train_sharpe"]
    pd.testing.assert_frame_equal(out[fit_cols], tampered_out[fit_cols])


def test_walk_forward_eval_skips_invalid_grid_entries():
    bars = _bars()
    out = walk_forward_eval(bars, "sma_crossover", [GRID[3], GRID[0]], CFG, 2, 3, 1)
    assert set(zip(out["fast"].astype(int), out["slow"].astype(int), strict=True)) == {(5, 20)}


def test_walk_forward_eval_raises_when_no_grid_entry_is_valid():
    bars = _bars()
    with pytest.raises(ValueError):
        walk_forward_eval(bars, "sma_crossover", [{"fast": 50, "slow": 10}], CFG, 2, 3, 1)


def test_overfit_warning_flags_best_at_grid_maximum():
    df = pd.DataFrame({"fast": [5, 10, 20], "slow": [50, 100, 200], "sharpe": [0.1, 0.3, 0.9]})
    msg = overfit_warning(df, ["fast", "slow"])
    assert msg is not None
    assert "'fast'" in msg and "'slow'" in msg and "maximum" in msg


def test_overfit_warning_flags_best_at_grid_minimum():
    df = pd.DataFrame({"fast": [5, 10, 20], "slow": [50, 100, 200], "sharpe": [0.9, 0.3, 0.1]})
    msg = overfit_warning(df, ["fast"])
    assert msg is not None and "minimum" in msg and "'fast'" in msg


def test_overfit_warning_is_none_when_best_is_interior():
    df = pd.DataFrame({"fast": [5, 10, 20], "slow": [50, 100, 200], "sharpe": [0.1, 0.9, 0.3]})
    assert overfit_warning(df, ["fast", "slow"]) is None


def test_overfit_warning_ignores_nan_sharpe_and_single_valued_params():
    df = pd.DataFrame({"fast": [5, 10, 20], "slow": [100, 100, 100], "sharpe": [math.nan, 0.5, 0.2]})
    assert overfit_warning(df, ["fast", "slow"]) is None


def test_overfit_warning_rejects_missing_columns():
    df = pd.DataFrame({"fast": [5, 10], "sharpe": [0.1, 0.2]})
    with pytest.raises(ValueError):
        overfit_warning(df, ["slow"])
    with pytest.raises(ValueError):
        overfit_warning(df.drop(columns="sharpe"), ["fast"])


def test_run_and_record_stores_benchmark_fields(tmp_path):
    bars = synthetic_bars("2015-01-01", "2024-12-31")
    with Store(tmp_path / "m.duckdb") as store:
        store.upsert_bars("ABC", bars)
        out = run_and_record(
            store=store,
            settings=Settings(),
            symbol="ABC",
            strategy_name="sma_crossover",
            strategy_params={"fast": 5, "slow": 20},
            start=date(2015, 1, 1),
            end=date(2024, 12, 31),
            cfg=CFG,
            track=False,
        )

    expected = benchmark_metrics(bars.set_index("ts"), CFG)
    assert out.metrics["benchmark_total_return"] == pytest.approx(expected["total_return"])
    assert out.metrics["benchmark_cagr"] == pytest.approx(expected["cagr"])
