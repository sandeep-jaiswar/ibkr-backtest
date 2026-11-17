import json
from datetime import date

import pandas as pd

from ibbt.engine import BacktestConfig, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.store import Store
from ibbt.synthetic import synthetic_bars


def test_upsert_is_idempotent_and_coverage_reports_range(tmp_path):
    bars = synthetic_bars("2022-01-03", "2022-03-31")
    with Store(tmp_path / "m.duckdb") as store:
        assert store.coverage("ABC") is None

        store.upsert_bars("ABC", bars)
        store.upsert_bars("ABC", bars)  # re-running must not duplicate rows

        count = store.con.execute("SELECT count(*) FROM bars WHERE symbol='ABC'").fetchall()[0][0]
        assert count == len(bars)
        assert store.coverage("ABC") == (date(2022, 1, 3), date(2022, 3, 31))


def test_load_bars_filters_by_symbol_and_range(tmp_path):
    with Store(tmp_path / "m.duckdb") as store:
        store.upsert_bars("ABC", synthetic_bars("2022-01-03", "2022-06-30"))
        store.upsert_bars("XYZ", synthetic_bars("2022-01-03", "2022-06-30", seed=2))

        df = store.load_bars("ABC", date(2022, 2, 1), date(2022, 2, 28))

        assert df.index.name == "ts"
        assert df.index.min() >= pd.Timestamp("2022-02-01")
        assert df.index.max() <= pd.Timestamp("2022-02-28")
        assert set(df.columns) == {"open", "high", "low", "close", "volume"}


def test_run_persists_runs_trades_and_equity(tmp_path):
    bars = synthetic_bars("2022-01-03", "2022-12-30").set_index("ts")
    signal = (bars["close"] > bars["close"].rolling(10).mean()).astype(int)
    result = run_backtest(bars, signal, BacktestConfig())
    metrics = compute_metrics(result.equity, result.trades, result.position)

    with Store(tmp_path / "m.duckdb") as store:
        store.save_run(
            run_id="r1",
            strategy="test",
            symbol="ABC",
            start=date(2022, 1, 3),
            end=date(2022, 12, 30),
            params={"fast": 10},
            metrics=metrics,
            mlflow_run_id=None,
        )
        store.save_trades("r1", result.trades)
        store.save_equity("r1", result.equity)

        assert store.con.execute("SELECT count(*) FROM equity_curves WHERE run_id='r1'").fetchall()[0][0] == len(bars)
        assert store.con.execute("SELECT count(*) FROM trades WHERE run_id='r1'").fetchall()[0][0] == len(result.trades)
        runs = store.list_runs()
        assert list(runs["run_id"]) == ["r1"]


def test_log_fetch_records_request_and_row_count(tmp_path):
    with Store(tmp_path / "m.duckdb") as store:
        store.log_fetch(symbol="ABC", start=date(2022, 1, 3), end=date(2022, 3, 31), rows=60, source="ib")

        rows = store.con.execute(
            "SELECT symbol, start_date, end_date, rows, source, fetched_at FROM fetch_log"
        ).fetchall()
        assert len(rows) == 1
        symbol, start, end, n, source, fetched_at = rows[0]
        assert (symbol, start, end, n, source) == ("ABC", date(2022, 1, 3), date(2022, 3, 31), 60, "ib")
        assert fetched_at is not None


def test_save_run_stores_strict_json_when_metrics_are_infinite(tmp_path):
    """profit_factor can be +inf; the stored JSON must still parse with a strict parser."""

    def _reject_constant(name):
        raise ValueError(f"non-standard JSON constant {name}")

    metrics = {"profit_factor": float("inf"), "sortino": float("-inf"), "sharpe": float("nan"), "total_return": 0.1}
    with Store(tmp_path / "m.duckdb") as store:
        store.save_run(
            run_id="inf1",
            strategy="test",
            symbol="ABC",
            start=date(2022, 1, 3),
            end=date(2022, 3, 31),
            params={"fast": 10, "cap": float("inf")},
            metrics=metrics,
            mlflow_run_id=None,
        )
        raw_metrics, raw_params = store.con.execute(
            "SELECT metrics, params FROM backtest_runs WHERE run_id = 'inf1'"
        ).fetchone()

    parsed = json.loads(raw_metrics, parse_constant=_reject_constant)
    assert parsed == {"profit_factor": None, "sortino": None, "sharpe": None, "total_return": 0.1}
    assert json.loads(raw_params, parse_constant=_reject_constant) == {"fast": 10, "cap": None}


def test_fetched_ranges_returns_every_logged_window_for_the_symbol(tmp_path):
    with Store(tmp_path / "m.duckdb") as store:
        store.log_fetch(symbol="ABC", start=date(2010, 1, 1), end=date(2015, 12, 31), rows=0, source="IB")
        store.log_fetch(symbol="ABC", start=date(2016, 1, 1), end=date(2016, 12, 31), rows=252, source="IB")
        store.log_fetch(symbol="XYZ", start=date(2000, 1, 1), end=date(2000, 12, 31), rows=10, source="IB")

        assert store.fetched_ranges("ABC") == [
            (date(2010, 1, 1), date(2015, 12, 31)),
            (date(2016, 1, 1), date(2016, 12, 31)),
        ]
        assert store.fetched_ranges("NOPE") == []
