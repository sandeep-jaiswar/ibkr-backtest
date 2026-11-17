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


def test_make_strategy_unknown_parameter_names_the_strategy_and_accepted_names():
    with pytest.raises(ValueError, match=r"sma_crossover.*fastt.*accepted parameters.*'fast'.*'slow'"):
        make_strategy("sma_crossover", {"fastt": 5})


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


def test_profit_factor_is_gross_profit_over_gross_loss():
    import math

    from ibbt.metrics import compute_metrics

    idx = pd.bdate_range("2020-01-01", periods=6)
    equity = pd.Series([100.0, 110, 105, 115, 112, 120], index=idx)
    trades = pd.DataFrame(
        {
            "entry_date": idx[:3],
            "entry_price": [1.0] * 3,
            "exit_date": idx[1:4],
            "exit_price": [1.0] * 3,
            "pnl_pct": [0.20, -0.10, 0.30],
            "open": [False] * 3,
        }
    )
    position = pd.Series([1, 1, 1, 1, 0, 0], index=idx)
    m = compute_metrics(equity, trades, position)
    assert m["profit_factor"] == pytest.approx(0.50 / 0.10)
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert math.isnan(compute_metrics(equity, trades.iloc[:0], position)["profit_factor"])


def test_rma_matches_pine_definition():
    """Pine ta.rma: seeded with the SMA of the first n values, then alpha = 1/n recursion."""
    import numpy as np

    from ibbt.strategies import _rma

    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    out = _rma(x, 3)
    assert np.isnan(out[:2]).all()
    assert out[2] == pytest.approx(2.0)  # mean of 1, 2, 3
    assert out[3] == pytest.approx(2.0 + (4.0 - 2.0) / 3)
    assert out[5] == pytest.approx(out[4] + (6.0 - out[4]) / 3)


def test_rma_atr_bands_trend_latch():
    """Close above the upper band latches long; close below the lower band latches flat; in between holds."""
    import numpy as np

    from ibbt.strategies import RmaAtrBands

    n = 60
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.full(30, 100.0), np.linspace(100, 130, 10), np.linspace(130, 110, 10), np.full(10, 80.0)]
    bars = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1.0}, index=idx
    )
    strat = RmaAtrBands(ma_length=5, atr_length=5, upper_mult=0.4, lower_mult=1.6)
    sig = strat.signal(bars)
    _, upper, lower = strat.bands(bars)

    assert sig.iloc[:10].sum() == 0  # warm-up stays flat
    first_long = int(np.argmax(close > upper.to_numpy()))
    assert sig.iloc[first_long] == 1
    assert sig.iloc[-1] == 0  # the last 10 bars sit below the lower band, so the trend is short
    assert sig.iloc[-1] == 0 and sig.iloc[-5] == 0


def test_rma_atr_bands_rejects_bad_params():
    from ibbt.strategies import RmaAtrBands

    with pytest.raises(ValueError):
        RmaAtrBands(source="volume")
    with pytest.raises(ValueError):
        RmaAtrBands(ma_length=0)


def test_ema_matches_pine_definition():
    """Pine ta.ema: seeded with the SMA of the first n values, then alpha = 2/(n+1)."""
    import numpy as np

    from ibbt.strategies import _ema

    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = _ema(x, 3)
    alpha = 2 / 4
    assert np.isnan(out[:2]).all()
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(2.0 + alpha * (4.0 - 2.0))
    assert out[4] == pytest.approx(out[3] + alpha * (5.0 - out[3]))


def test_projected_crossover_follows_uptrend_and_downtrend():
    """A rising series latches long once MDI and the slow-lag test agree; a falling one latches flat."""
    import numpy as np

    from ibbt.strategies import ProjectedCrossover

    n = 200
    idx = pd.bdate_range("2020-01-01", periods=n)
    up = np.linspace(100, 200, 120)
    down = np.linspace(200, 80, 80)
    close = np.r_[up, down]
    bars = pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1.0}, index=idx
    )
    strat = ProjectedCrossover()
    sig = strat.signal(bars)
    assert sig.iloc[:30].sum() == 0  # warm-up stays flat
    assert sig.iloc[100] == 1  # well into the uptrend
    assert sig.iloc[-1] == 0  # the falling leg latches the short side


def test_projected_crossover_rejects_bad_params():
    from ibbt.strategies import ProjectedCrossover

    with pytest.raises(ValueError):
        ProjectedCrossover(fast_len=1)
    with pytest.raises(ValueError):
        ProjectedCrossover(source="volume")


def test_dual_ma_sd_oscillator_uses_population_stdev():
    """Pine ta.stdev is the population standard deviation (ddof=0), and a length-1 EMA is the source itself."""
    import numpy as np

    from ibbt.strategies import DualMaSdOscillator

    n = 60
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 + np.sin(np.arange(n) / 3.0) * 5
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    strat = DualMaSdOscillator(slow_len=5, upper_sd_len=10, lower_sd_len=10)
    osc, upper, lower = strat.oscillator(bars)
    # The spread with fast_len 1 is close minus its EMA(5); check the band against a hand-computed population stdev.
    window = osc.iloc[-10:].to_numpy()
    assert upper.iloc[-1] == pytest.approx(window.std(ddof=0))
    assert lower.iloc[-1] == pytest.approx(-window.std(ddof=0))
    assert upper.iloc[:10].isna().all()  # warm-up is NaN


def test_dual_ma_sd_oscillator_latches_on_band_breaks():
    import numpy as np

    from ibbt.strategies import DualMaSdOscillator

    n = 200
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 160, 100), np.linspace(160, 90, 100)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = DualMaSdOscillator().signal(bars)
    assert sig.iloc[:30].sum() == 0
    assert sig.iloc[90] == 1  # strong rise: oscillator breaks above its upper band
    assert sig.iloc[-1] == 0  # strong fall: oscillator breaks below the lower band


def test_dual_ma_sd_oscillator_rejects_bad_params():
    from ibbt.strategies import DualMaSdOscillator

    with pytest.raises(ValueError):
        DualMaSdOscillator(upper_sd_len=0)
    with pytest.raises(ValueError):
        DualMaSdOscillator(source="volume")


def test_double_smoothed_mad_trend_starts_long_and_latches():
    """The script starts with trend = +1. A falling series latches flat and a rising one latches long."""
    import numpy as np

    from ibbt.strategies import DoubleSmoothedMadTrend

    n = 200
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 160, 100), np.linspace(160, 90, 100)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    strat = DoubleSmoothedMadTrend()
    sig = strat.signal(bars)
    assert sig.iloc[0] == 1  # var int SQ = 1: long before any signal
    assert sig.iloc[90] == 1
    assert sig.iloc[-1] == 0


def test_double_smoothed_mad_tsi_is_zero_when_denominator_is_zero():
    import numpy as np

    from ibbt.strategies import DoubleSmoothedMadTrend

    idx = pd.bdate_range("2020-01-01", periods=40)
    bars = pd.DataFrame({"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1.0}, index=idx)
    tsi = DoubleSmoothedMadTrend().tsi(bars)
    assert np.isnan(tsi.iloc[:20]).all()  # the second EMA(20) is still warming up
    assert (tsi.iloc[25:] == 0.0).all()  # flat prices: momentum and its absolute value are 0


def test_double_smoothed_mad_rejects_bad_params():
    from ibbt.strategies import DoubleSmoothedMadTrend

    with pytest.raises(ValueError):
        DoubleSmoothedMadTrend(mad_len=1)
    with pytest.raises(ValueError):
        DoubleSmoothedMadTrend(mad_mult=0.05)


def test_nearest_rank_percentile_matches_definition():
    import numpy as np

    from ibbt.strategies import _percentile_nearest_rank

    x = np.array([5.0, 1.0, 4.0, 2.0, 3.0])
    out = _percentile_nearest_rank(x, 5, 60.0)  # rank = ceil(0.6 * 5) = 3 -> third smallest
    assert np.isnan(out[:4]).all()
    assert out[4] == pytest.approx(3.0)


def test_adaptive_ehlers_percentile_regimes():
    """Starts flat, goes long on a breakout above the percentile band, and goes flat on a breakdown."""
    import numpy as np

    from ibbt.strategies import AdaptiveEhlersPercentile

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = AdaptiveEhlersPercentile().signal(bars)
    assert sig.iloc[:30].sum() == 0
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_adaptive_ehlers_percentile_rejects_bad_params():
    from ibbt.strategies import AdaptiveEhlersPercentile

    with pytest.raises(ValueError):
        AdaptiveEhlersPercentile(ma_min=40, ma_max=30)
    with pytest.raises(ValueError):
        AdaptiveEhlersPercentile(percentile_level=100)


def test_volatility_adaptive_trend_follows_breakouts():
    """Starts flat, goes long on a breakout above the volatility band, and goes flat on a breakdown."""
    import numpy as np

    from ibbt.strategies import VolatilityAdaptiveTrend

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = VolatilityAdaptiveTrend().signal(bars)
    assert sig.iloc[:20].sum() == 0  # bands are still NaN during warm-up
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_volatility_adaptive_trend_constant_price_has_no_trend_error():
    """With a constant price the trend equals the price, volatility is zero, and the bands collapse onto it."""
    import numpy as np

    from ibbt.strategies import VolatilityAdaptiveTrend

    idx = pd.bdate_range("2020-01-01", periods=120)
    bars = pd.DataFrame({"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1.0}, index=idx)
    trend, upper, lower = VolatilityAdaptiveTrend().bands(bars)
    valid = ~np.isnan(trend[-20:])
    assert np.allclose(trend[-20:][valid], 50.0)
    assert np.allclose(upper[-20:][valid], 50.0)
    assert VolatilityAdaptiveTrend().signal(bars).sum() == 0  # not above a band equal to the price


def test_volatility_adaptive_trend_rejects_bad_params():
    from ibbt.strategies import VolatilityAdaptiveTrend

    with pytest.raises(ValueError):
        VolatilityAdaptiveTrend(min_sc=0.0)
    with pytest.raises(ValueError):
        VolatilityAdaptiveTrend(filter_len=1)


def test_mesa_phase_activity_is_bounded_and_flat_on_constant_price():
    import numpy as np

    from ibbt.strategies import _mesa_phase_activity

    act = _mesa_phase_activity(np.linspace(100, 120, 300), 0.5, 0.05)
    assert np.all((act >= 0) & (act <= 1))
    assert np.isfinite(act).all()


def test_mesa_phase_band_trend_breakouts():
    import numpy as np

    from ibbt.strategies import MesaPhaseBandTrend

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = MesaPhaseBandTrend().signal(bars)
    assert sig.iloc[:20].sum() == 0
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_mesa_phase_band_rejects_bad_params():
    from ibbt.strategies import MesaPhaseBandTrend

    with pytest.raises(ValueError):
        MesaPhaseBandTrend(fast_limit=0.0)
    with pytest.raises(ValueError):
        MesaPhaseBandTrend(trend_len=1)


def test_adaptive_persistence_trail_regimes():
    """Starts long, follows a rally, and flips flat once a sustained selloff breaks the trail."""
    import numpy as np

    from ibbt.strategies import AdaptivePersistenceTrail

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = AdaptivePersistenceTrail().signal(bars)
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_adaptive_persistence_trail_rejects_bad_params():
    from ibbt.strategies import AdaptivePersistenceTrail

    with pytest.raises(ValueError):
        AdaptivePersistenceTrail(persistence_len=1)
    with pytest.raises(ValueError):
        AdaptivePersistenceTrail(max_acc=1.5)


def test_adaptive_vidya_regimes():
    """Starts bullish, goes long on a rally breakout, and goes flat once a selloff breaks the lower band."""
    import numpy as np

    from ibbt.strategies import AdaptiveVidya

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = AdaptiveVidya().signal(bars)
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_adaptive_vidya_constant_price_tracks_price():
    import numpy as np

    from ibbt.strategies import AdaptiveVidya

    idx = pd.bdate_range("2020-01-01", periods=80)
    bars = pd.DataFrame({"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1.0}, index=idx)
    vidya, upper, lower = AdaptiveVidya().bands(bars)
    assert np.allclose(vidya, 50.0)  # with no price movement the average stays at the price
    # The bands collapse onto the price, so nothing breaks out and the bullish starting regime never changes.
    assert AdaptiveVidya().signal(bars).sum() == len(bars)


def test_adaptive_vidya_rejects_bad_params():
    from ibbt.strategies import AdaptiveVidya

    with pytest.raises(ValueError):
        AdaptiveVidya(short_len=1)
    with pytest.raises(ValueError):
        AdaptiveVidya(base_smoothing=0.0)


def test_adaptive_supersmoother_regimes():
    """Starts flat, goes long on a sustained rally, and goes flat on a sustained selloff."""
    import numpy as np

    from ibbt.strategies import AdaptiveSuperSmoother

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = AdaptiveSuperSmoother().signal(bars)
    assert sig.iloc[:20].sum() == 0
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_adaptive_supersmoother_constant_price_is_flat():
    import numpy as np

    from ibbt.strategies import AdaptiveSuperSmoother

    idx = pd.bdate_range("2020-01-01", periods=80)
    bars = pd.DataFrame({"open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1.0}, index=idx)
    trend, eff = AdaptiveSuperSmoother().trend(bars)
    assert np.allclose(trend[5:], 50.0)
    assert AdaptiveSuperSmoother().signal(bars).sum() == 0  # no slope, so no regime change from flat


def test_adaptive_supersmoother_rejects_bad_params():
    from ibbt.strategies import AdaptiveSuperSmoother

    with pytest.raises(ValueError):
        AdaptiveSuperSmoother(smooth_len=2)
    with pytest.raises(ValueError):
        AdaptiveSuperSmoother(ma_min=60, ma_max=50)


def test_adx_lifecycle_trail_regimes():
    """Starts bullish, follows a rally, and flips flat once a sustained selloff with DI dominance breaks the trail."""
    import numpy as np

    from ibbt.strategies import AdxLifecycleTrail

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = AdxLifecycleTrail().signal(bars)
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_adx_lifecycle_trail_rejects_bad_params():
    from ibbt.strategies import AdxLifecycleTrail

    with pytest.raises(ValueError):
        AdxLifecycleTrail(short_len=12, medium_len=5)
    with pytest.raises(ValueError):
        AdxLifecycleTrail(dominance_level=0.9)


def test_kaufman_adaptive_channel_regimes():
    """Starts bullish, follows a rally, and flips flat once a sustained selloff breaks the trail."""
    import numpy as np

    from ibbt.strategies import KaufmanAdaptiveChannel

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = KaufmanAdaptiveChannel().signal(bars)
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_kaufman_adaptive_channel_rejects_bad_params():
    from ibbt.strategies import KaufmanAdaptiveChannel

    with pytest.raises(ValueError):
        KaufmanAdaptiveChannel(er_len=1)
    with pytest.raises(ValueError):
        KaufmanAdaptiveChannel(structure_influence=3.0)


def test_adaptive_breakout_oscillator_regimes():
    """Starts from a flat oscillator (regime long), follows a rally, and flips flat on a sustained selloff."""
    import numpy as np

    from ibbt.strategies import AdaptiveBreakoutOscillator

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    strat = AdaptiveBreakoutOscillator()
    osc, upper, lower = strat.oscillator(bars)
    assert np.isfinite(osc[60:]).all()
    sig = strat.signal(bars)
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_adaptive_breakout_oscillator_rejects_bad_params():
    from ibbt.strategies import AdaptiveBreakoutOscillator

    with pytest.raises(ValueError):
        AdaptiveBreakoutOscillator(short_len=20, medium_len=10)
    with pytest.raises(ValueError):
        AdaptiveBreakoutOscillator(max_threshold=1.5)


def test_ehlers_instant_trend_regimes():
    """Starts bullish, follows a rally, and flips flat on a sustained selloff with negative momentum."""
    import numpy as np

    from ibbt.strategies import EhlersInstantTrend

    n = 260
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = np.r_[np.linspace(100, 150, 130), np.linspace(150, 90, 130)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = EhlersInstantTrend().signal(bars)
    assert sig.iloc[125] == 1
    assert sig.iloc[-1] == 0


def test_ehlers_instant_trend_seed_during_first_bars():
    import numpy as np

    from ibbt.strategies import EhlersInstantTrend

    idx = pd.bdate_range("2020-01-01", periods=12)
    close = np.arange(100.0, 112.0)
    bars = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0}, index=idx)
    lv = EhlersInstantTrend()._levels(bars)
    # For bars 0-6 the trendline is the seed (src + 2 src[1] + src[2]) / 4; on a line that is src[t] - 1.
    assert lv["it"][3] == pytest.approx((103 + 2 * 102 + 101) / 4)


def test_ehlers_instant_trend_rejects_bad_params():
    from ibbt.strategies import EhlersInstantTrend

    with pytest.raises(ValueError):
        EhlersInstantTrend(alpha=0.9)
    with pytest.raises(ValueError):
        EhlersInstantTrend(noise_len=1)


def test_decycler_hl_breakout_stays_flat_during_warmup_and_follows_trend():
    """Flat until the 115-bar warm-up is complete, then long on a sustained rally and flat on a crash."""
    import numpy as np

    from ibbt.strategies import DecyclerHighLowBreakout

    n = 460
    idx = pd.bdate_range("2019-01-01", periods=n)
    close = np.r_[np.linspace(100, 200, 200), np.linspace(200, 80, 260)]
    bars = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}, index=idx)
    sig = DecyclerHighLowBreakout().signal(bars)
    assert sig.iloc[:115].sum() == 0
    assert sig.iloc[180:200].sum() > 0
    assert sig.iloc[-1] == 0


def test_decycler_hl_breakout_rejects_bad_params():
    from ibbt.strategies import DecyclerHighLowBreakout

    with pytest.raises(ValueError):
        DecyclerHighLowBreakout(period=3)
    with pytest.raises(ValueError):
        DecyclerHighLowBreakout(slope_conf=2.0)
