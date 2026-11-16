from datetime import date

import pandas as pd
import pytest

from ibbt.ib_source import missing_ranges
from ibbt.strategies import SmaCrossover, make_strategy
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
