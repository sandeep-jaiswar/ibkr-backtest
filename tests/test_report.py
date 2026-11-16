import argparse

import pytest

from ibbt.engine import BacktestConfig, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.report import register, render_tear_sheet
from ibbt.store import Store
from ibbt.strategies import SmaCrossover
from ibbt.synthetic import synthetic_bars


def _seed_run(store: Store, run_id: str, strategy_name: str = "sma_crossover") -> None:
    bars = synthetic_bars("2022-01-03", "2022-12-30").set_index("ts")
    strat = SmaCrossover(fast=10, slow=30)
    result = run_backtest(bars, strat.signal(bars), BacktestConfig())
    metrics = compute_metrics(result.equity, result.trades, result.position)
    store.save_run(
        run_id=run_id,
        strategy=strategy_name,
        symbol="SYNTH",
        start=bars.index[0].date(),
        end=bars.index[-1].date(),
        params={**strat.params(), "commission_bps": 5.0},
        metrics=metrics,
        mlflow_run_id=None,
    )
    store.save_trades(run_id, result.trades)
    store.save_equity(run_id, result.equity)


def test_render_tear_sheet_writes_self_contained_html(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        _seed_run(store, "run123abc")
        out = render_tear_sheet(store, "run123abc", tmp_path / "out" / "sheet.html")

    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "run123abc" in text
    assert "Drawdown" in text
    assert "<script" not in text
    assert "http://" not in text.replace("http://www.w3.org/2000/svg", "")


def test_render_tear_sheet_escapes_user_text(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        _seed_run(store, "esc1", strategy_name="<script>alert(1)</script>")
        out = render_tear_sheet(store, "esc1", tmp_path / "sheet.html")

    text = out.read_text(encoding="utf-8")
    assert "<script>alert" not in text
    assert "&lt;script&gt;" in text


def test_render_tear_sheet_missing_run_raises_lookup_error(tmp_path):
    with Store(tmp_path / "t.duckdb") as store:
        with pytest.raises(LookupError):
            render_tear_sheet(store, "no-such-run", tmp_path / "sheet.html")


def test_report_subcommand_is_registered(tmp_path):
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(["report", "abc", "--out", str(tmp_path / "x.html")])
    assert args.run_id == "abc"
    assert args.out == str(tmp_path / "x.html")
    assert callable(args.func)
