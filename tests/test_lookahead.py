"""No look-ahead: each strategy output on a prefix of the bars must equal its output on the full bars.
A value that changes when later bars are added means the strategy is peeking at the future."""

import numpy as np
import pandas as pd
import pytest

from ibbt.strategies import REGISTRY, make_strategy

CONFIGS = {
    "buy_and_hold": {},
    "sma_crossover": {"fast": 20, "slow": 100},
    "ema_crossover": {"fast": 21, "slow": 50},
    "donchian_breakout": {"lookback": 55, "exit_lookback": 20},
    "rsi_pullback": {"entry_rsi": 10, "exit_rsi": 70, "trend": 200},
    "ibs_reversion": {"trend": 200, "entry_ibs": 0.2, "exit_ibs": 0.8},
    "price_action_breakout": {
        "breakout_lookback": 20,
        "max_risk": 0.10,
        "leg": "both",
        "stop_mode": "atr",
        "min_volume_ratio": 1.5,
    },
    "price_action_breakout_support": {"breakout_lookback": 20, "max_risk": 0.10, "leg": "both"},
    "higher_high_structure": {"lookback": 20, "trail_bars": 5, "trend": 200},
    "champion_daily_setup": {},
    "rma_atr_bands": {"source": "high", "ma_length": 14, "atr_length": 13, "upper_mult": 0.4, "lower_mult": 1.6},
}


def _bars(n: int = 600, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n)))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.01, n)))
    vol = rng.integers(10_000, 500_000, n).astype(float)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


def _strategy_name(key: str) -> str:
    return "price_action_breakout" if key.startswith("price_action") else key


@pytest.mark.parametrize("key", list(CONFIGS))
def test_signal_uses_only_past_and_present(key):
    bars = _bars()
    full = make_strategy(_strategy_name(key), CONFIGS[key]).signal(bars)
    for cut in (250, 400, 550):
        part = make_strategy(_strategy_name(key), CONFIGS[key]).signal(bars.iloc[:cut])
        pd.testing.assert_series_equal(full.iloc[:cut], part, check_names=False, check_dtype=False)


@pytest.mark.parametrize("key", [k for k in CONFIGS if k.startswith("price_action")])
def test_levels_and_ranking_use_only_past_and_present(key):
    bars = _bars()
    strat = make_strategy("price_action_breakout", CONFIGS[key])
    full_lv = strat.levels(bars)
    full_rank = strat.rank_score(bars)
    for cut in (300, 500):
        part_lv = make_strategy("price_action_breakout", CONFIGS[key]).levels(bars.iloc[:cut])
        part_rank = make_strategy("price_action_breakout", CONFIGS[key]).rank_score(bars.iloc[:cut])
        pd.testing.assert_frame_equal(full_lv.iloc[:cut], part_lv, check_dtype=False)
        pd.testing.assert_series_equal(full_rank.iloc[:cut], part_rank, check_dtype=False, check_names=False)


def test_every_registered_strategy_is_covered():
    covered = {_strategy_name(k) for k in CONFIGS}
    assert set(REGISTRY) <= covered, f"no look-ahead config for {set(REGISTRY) - covered}"


def test_portfolio_equity_before_cut_is_unchanged_by_future_bars():
    from ibbt.portfolio import PortfolioConfig, run_portfolio
    from ibbt.strategies import PriceActionBreakout

    rng_syms = ["A", "B", "C", "D", "E", "F", "G"]
    frames = {}
    for k, s in enumerate(rng_syms):
        frames[s] = _bars(500, seed=20 + k)
    idx = frames["A"].index
    OP = pd.DataFrame({s: f["open"] for s, f in frames.items()}, index=idx)
    H = pd.DataFrame({s: f["high"] for s, f in frames.items()}, index=idx)
    L = pd.DataFrame({s: f["low"] for s, f in frames.items()}, index=idx)
    C = pd.DataFrame({s: f["close"] for s, f in frames.items()}, index=idx)
    sig = pd.DataFrame(
        {
            s: make_strategy(
                "price_action_breakout", {"breakout_lookback": 20, "max_risk": 0.10, "leg": "breakout"}
            ).signal(f)
            for s, f in frames.items()
        },
        index=idx,
    )
    lv = {
        s: PriceActionBreakout(breakout_lookback=20, max_risk=0.10, leg="breakout").levels(f) for s, f in frames.items()
    }
    SL = pd.DataFrame({s: lv[s]["stop"] for s in frames}, index=idx)
    TL = pd.DataFrame({s: lv[s]["target"] for s in frames}, index=idx)
    rank = pd.DataFrame(
        {
            s: PriceActionBreakout(breakout_lookback=20, max_risk=0.10, leg="breakout").rank_score(f)
            for s, f in frames.items()
        },
        index=idx,
    )
    cfg = PortfolioConfig(
        initial_cash=10_000, max_positions=3, position_size=2_000, min_position_size=1_000, signal_exit=False
    )

    full = run_portfolio(OP, H, L, C, sig, cfg, rank=rank, stop_levels=SL, target_levels=TL)
    cut = 380
    part = run_portfolio(
        OP.iloc[:cut],
        H.iloc[:cut],
        L.iloc[:cut],
        C.iloc[:cut],
        sig.iloc[:cut],
        cfg,
        rank=rank.iloc[:cut],
        stop_levels=SL.iloc[:cut],
        target_levels=TL.iloc[:cut],
    )
    np.testing.assert_allclose(full.equity.iloc[:cut].to_numpy(), part.equity.to_numpy(), rtol=1e-12)


@pytest.mark.parametrize(
    "rank_by", ["volume_surge", "trend_distance", "liquidity", "range_expansion", "close_strength"]
)
def test_champion_rankings_use_only_past_and_present(rank_by):
    from ibbt.strategies import ChampionDailySetup

    bars = _bars(600, seed=11)
    full = ChampionDailySetup(rank_by=rank_by).rank_score(bars)
    for cut in (300, 500):
        part = ChampionDailySetup(rank_by=rank_by).rank_score(bars.iloc[:cut])
        pd.testing.assert_series_equal(full.iloc[:cut], part, check_names=False, check_dtype=False)


def test_champion_stop_levels_use_only_past_and_present():
    from ibbt.strategies import ChampionDailySetup

    bars = _bars(600, seed=13)
    full = ChampionDailySetup(stop_atr_mult=2.0).levels(bars)
    for cut in (300, 500):
        part = ChampionDailySetup(stop_atr_mult=2.0).levels(bars.iloc[:cut])
        pd.testing.assert_frame_equal(full["stop"].iloc[:cut].to_frame(), part["stop"].to_frame(), check_dtype=False)


def test_champion_stop_only_trade_exits_on_stop_not_target():
    from ibbt.portfolio import PortfolioConfig, run_portfolio

    idx = pd.bdate_range("2024-01-01", periods=4)
    o = pd.DataFrame({"A": [100.0, 100.0, 100.0, 100.0]}, index=idx)
    h = pd.DataFrame({"A": [100.0, 101.0, 101.0, 101.0]}, index=idx)
    lo = pd.DataFrame({"A": [100.0, 99.0, 90.0, 90.0]}, index=idx)
    c = pd.DataFrame({"A": [100.0, 100.0, 92.0, 92.0]}, index=idx)
    sig = pd.DataFrame({"A": [1, 0, 0, 0]}, index=idx)
    stop = pd.DataFrame({"A": [95.0, np.nan, np.nan, np.nan]}, index=idx)
    target = pd.DataFrame({"A": [np.nan] * 4}, index=idx)
    cfg = PortfolioConfig(commission_bps=0, slippage_bps=0, signal_exit=False)
    res = run_portfolio(o, h, lo, c, sig, cfg, stop_levels=stop, target_levels=target)
    t = res.trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["exit_price"] == pytest.approx(95.0)
