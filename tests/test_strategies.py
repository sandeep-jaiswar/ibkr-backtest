from datetime import date

import pandas as pd
import pytest

from ibbt.ib_source import missing_ranges
from ibbt.strategies import DonchianBreakout, SmaCrossover, make_strategy
from ibbt.synthetic import synthetic_bars


def test_sma_signal_uses_only_past_data():
    """Truncating the future must not change any earlier signal value (no look-ahead)."""
    bars = synthetic_bars("2020-01-01", "2021-12-31", seed=1)
    bars = bars.set_index("ts")
    strat = SmaCrossover(fast=5, slow=20)

    full = strat.signal(bars)
    cut = len(bars) // 2
    partial = strat.signal(bars.iloc[:cut])

    pd.testing.assert_series_equal(full.iloc[:cut], partial, check_names=False)


def test_sma_warmup_is_flat():
    bars = synthetic_bars("2020-01-01", "2020-03-31").set_index("ts")
    signal = SmaCrossover(fast=5, slow=50).signal(bars)
    assert signal.iloc[:49].sum() == 0


def test_sma_rejects_fast_not_below_slow():
    with pytest.raises(ValueError):
        SmaCrossover(fast=50, slow=20)


def test_make_strategy_unknown_name():
    with pytest.raises(KeyError):
        make_strategy("does_not_exist")


def test_missing_ranges_empty_store_fetches_everything():
    assert missing_ranges(None, date(2020, 1, 1), date(2020, 6, 1)) == [(date(2020, 1, 1), date(2020, 6, 1))]


def test_missing_ranges_fetches_only_the_edges():
    coverage = (date(2020, 3, 1), date(2020, 9, 1))
    gaps = missing_ranges(coverage, date(2020, 1, 1), date(2021, 1, 1))
    assert gaps == [
        (date(2020, 1, 1), date(2020, 2, 29)),
        (date(2020, 9, 2), date(2021, 1, 1)),
    ]


def test_missing_ranges_fully_covered():
    assert missing_ranges((date(2019, 1, 1), date(2021, 1, 1)), date(2020, 1, 1), date(2020, 6, 1)) == []


def test_donchian_signal_uses_only_past_data():
    """Truncating the future must not change any earlier signal value (no look-ahead)."""
    bars = synthetic_bars("2020-01-01", "2021-12-31", seed=3).set_index("ts")
    strat = DonchianBreakout(lookback=20, exit_lookback=8)

    full = strat.signal(bars)
    cut = len(bars) // 2
    partial = strat.signal(bars.iloc[:cut])

    pd.testing.assert_series_equal(full.iloc[:cut], partial, check_names=False)


def test_donchian_breakout_and_breakdown_on_known_series():
    closes = [10, 10, 10, 10, 12, 11, 9, 8, 13, 13]
    bars = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
        },
        index=pd.bdate_range("2022-01-03", periods=len(closes)),
    )
    signal = DonchianBreakout(lookback=3, exit_lookback=2).signal(bars)

    # Bar 4 closes above the prior 3-bar high (10) -> long.
    # Bar 6 closes below the prior 2-bar low (11) -> flat.
    # Bar 8 closes above the prior 3-bar high (11) -> long again; bar 9 holds.
    assert signal.tolist() == [0, 0, 0, 0, 1, 1, 0, 0, 1, 1]


def test_donchian_rejects_exit_not_below_lookback():
    with pytest.raises(ValueError):
        DonchianBreakout(lookback=20, exit_lookback=20)
    with pytest.raises(ValueError):
        DonchianBreakout(lookback=20, exit_lookback=0)


def test_donchian_is_registered():
    assert isinstance(make_strategy("donchian_breakout", {"lookback": 10, "exit_lookback": 5}), DonchianBreakout)
