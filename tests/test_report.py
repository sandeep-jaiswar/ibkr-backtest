"""Tear sheet tests: one quantstats-backed renderer, offline, escaped, guarded against degenerate runs."""

from __future__ import annotations

import argparse
import re

import pandas as pd
import pytest

from ibbt.engine import BacktestConfig, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.report import periods_per_year, register, render_tear_sheet
from ibbt.store import Store
from ibbt.strategies import SmaCrossover
from ibbt.synthetic import synthetic_bars


def _seed(store: Store, run_id: str, strategy: str = "sma_crossover") -> None:
    bars = synthetic_bars("2022-01-03", "2022-12-30").set_index("ts")
    strat = SmaCrossover(fast=10, slow=30)
    result = run_backtest(bars, strat.signal(bars), BacktestConfig())
    store.save_run(
        run_id=run_id,
        strategy=strategy,
        symbol="SYNTH",
        start=bars.index[0].date(),
        end=bars.index[-1].date(),
        params={**strat.params(), "commission_bps": 5.0},
        metrics=compute_metrics(result.equity, result.trades, result.position),
        mlflow_run_id=None,
    )
    store.save_trades(run_id, result.trades)
    store.save_equity(run_id, result.equity)


def _seed_equity(store: Store, run_id: str, values: list[float]) -> None:
    idx = pd.bdate_range("2022-01-03", periods=len(values))
    store.save_run(
        run_id=run_id,
        strategy="flat",
        symbol="SYNTH",
        start=idx[0].date(),
        end=idx[-1].date(),
        params={},
        metrics={"final_equity": values[-1]},
        mlflow_run_id=None,
    )
    store.save_equity(run_id, pd.Series(values, index=idx, name="equity"))


def test_writes_sheet_with_stored_metrics_and_quantstats_figures(tmp_path, monkeypatch):
    import yfinance

    def no_network(*args, **kwargs):
        raise AssertionError("the report tried to download data")

    monkeypatch.setattr(yfinance, "download", no_network)
    with Store(tmp_path / "t.duckdb") as store:
        _seed(store, "run123abc")
        out = render_tear_sheet(store, "run123abc", tmp_path / "out" / "sheet.html")
    text = out.read_text(encoding="utf-8")
    assert "run123abc" in text
    assert "Stored metrics" in text
    assert "canonical" in text
    assert "<svg" in text or "<img" in text  # quantstats figures present
    assert "quantstats figures follow" in text


def test_no_external_resources_are_loaded(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        _seed(store, "offline1")
        out = render_tear_sheet(store, "offline1", tmp_path / "sheet.html")
    text = out.read_text(encoding="utf-8")
    # Anything a browser fetches on open: scripts, stylesheets, images, icons, CSS urls and @import.
    assert not re.search(r"<script[^>]+src=", text, re.IGNORECASE)
    assert not re.search(r"<link[^>]+href=[\"']?https?://", text, re.IGNORECASE)
    assert not re.search(r"<img[^>]+src=[\"']?https?://", text, re.IGNORECASE)
    assert not re.search(r"url\(\s*[\"']?https?://", text)
    assert "@import" not in text


def test_title_is_escaped(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        _seed(store, "esc1", strategy="<script>alert(1)</script>")
        out = render_tear_sheet(store, "esc1", tmp_path / "sheet.html")
    text = out.read_text(encoding="utf-8")
    assert "<script>alert(1)" not in text
    assert "&lt;script&gt;" in text


def test_flat_equity_still_writes_a_page_with_the_reason(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        _seed_equity(store, "flat1", [100.0] * 10)
        out = render_tear_sheet(store, "flat1", tmp_path / "sheet.html")
    text = out.read_text(encoding="utf-8")
    assert "quantstats figures skipped: flat equity" in text
    assert "Stored metrics" in text


def test_short_run_still_writes_a_page_with_the_reason(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        _seed_equity(store, "short1", [100.0, 101.0])
        out = render_tear_sheet(store, "short1", tmp_path / "sheet.html")
    assert "at least 3" in out.read_text(encoding="utf-8")


def test_missing_run_raises_lookup_error(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        with pytest.raises(LookupError):
            render_tear_sheet(store, "no-such-run", tmp_path / "sheet.html")


def test_periods_per_year_follows_bar_density():
    weekdays = pd.bdate_range("2015-01-01", "2024-12-31")
    # Exchange data omits holidays; drop the first weekday of each month to mimic roughly 250 bars a year.
    stocks = weekdays[weekdays.to_period("M").duplicated()]
    crypto = pd.date_range("2015-01-01", "2024-12-31", freq="D")
    assert 245 <= periods_per_year(stocks) <= 255
    assert 360 <= periods_per_year(crypto) <= 370


def test_report_subcommand_is_registered(tmp_path):
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(["report", "abc", "--out", str(tmp_path / "x.html")])
    assert args.run_id == "abc"
    assert args.out == str(tmp_path / "x.html")
    assert callable(args.func)
