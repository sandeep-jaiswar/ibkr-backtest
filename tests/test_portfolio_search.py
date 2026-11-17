from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from mlflow.tracking import MlflowClient

from ibbt import portfolio_search as ps
from ibbt.config import Settings
from ibbt.portfolio import PortfolioConfig
from ibbt.search import expand_grid


def _settings(tmp_path: Path) -> Settings:
    return Settings(mlflow_tracking_uri=f"sqlite:///{tmp_path / 'mlflow.db'}", duckdb_path=tmp_path / "market.duckdb")


def _candidate() -> ps.Candidate:
    return ps.Candidate("rsi_pullback", (("entry_rsi", 10), ("exit_rsi", 70), ("trend", 50)))


def _fake_result(valid_with_equity: bool) -> dict:
    m = {"profit_factor": 2.5, "win_rate": 0.6, "round_trips": 300.0, "total_return": 0.1, "max_drawdown": -0.05}
    p = {"profit_factor": 2.5, "win_rate": 0.6, "round_trips": 300.0}
    valid: dict = {"metrics": m}
    if valid_with_equity:
        valid["equity"] = pd.Series(np.linspace(10_000.0, 11_000.0, 100))
        valid["trades"] = pd.DataFrame({"pnl": [1.0]})
    return {
        "candidate": _candidate(),
        "goal_met": True,
        "results": {
            "train": {"metrics": m},
            "valid": valid,
            "train_pooled": {"metrics": p},
            "valid_pooled": {"metrics": p},
        },
    }


def _run_round(settings: Settings, evaluated: list[dict]) -> str:
    return ps.log_round(
        evaluated,
        settings=settings,
        base=PortfolioConfig(),
        n_symbols=2,
        hypothesis="test",
        note="test",
        experiment="test-round",
    )


def test_search_without_any_grid_strategy_raises_before_the_pool(tmp_path):
    # sma_crossover is registered but has no search grid, so there is nothing to evaluate.
    # The database path does not exist: the error must come before the universe is loaded.
    with pytest.raises(ValueError, match="no candidates"):
        ps.search(
            tmp_path / "missing.duckdb",
            _settings(tmp_path),
            base=PortfolioConfig(),
            hypothesis="test",
            strategies=["sma_crossover"],
        )


def test_expand_grid_lists_parameterless_strategy_once():
    configs = [c for c in expand_grid() if c[0] == "buy_and_hold"]
    assert configs == [("buy_and_hold", {})]


def test_log_round_terminates_parent_as_finished_on_success(tmp_path):
    settings = _settings(tmp_path)
    run_id = _run_round(settings, [_fake_result(valid_with_equity=True)])
    client = MlflowClient(settings.mlflow_tracking_uri)
    assert client.get_run(run_id).info.status == "FINISHED"
    children = client.search_runs(
        [client.get_run(run_id).info.experiment_id], filter_string=f"tags.mlflow.parentRunId = '{run_id}'"
    )
    assert [c.info.status for c in children] == ["FINISHED"]


def test_log_round_terminates_open_children_and_parent_on_failure(tmp_path):
    settings = _settings(tmp_path)
    # No "equity" in the valid window: the top candidate fails after its child run is created.
    with pytest.raises(KeyError):
        _run_round(settings, [_fake_result(valid_with_equity=False)])

    client = MlflowClient(settings.mlflow_tracking_uri)
    parent = client.search_runs(
        [client.get_experiment_by_name("test-round").experiment_id],
        filter_string="tags.kind = 'portfolio_search'",
    )
    assert len(parent) == 1
    assert parent[0].info.status == "FAILED"
    children = client.search_runs(
        [parent[0].info.experiment_id], filter_string=f"tags.mlflow.parentRunId = '{parent[0].info.run_id}'"
    )
    assert len(children) == 1
    assert children[0].info.status == "FAILED"


def _make_bars(path: Path) -> None:
    dates = pd.bdate_range("2022-01-03", periods=400)
    rng = np.random.default_rng(0)
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE bars (symbol VARCHAR, ts TIMESTAMP, open DOUBLE, high DOUBLE, "
        "low DOUBLE, close DOUBLE, volume DOUBLE)"
    )
    for sym in ("A", "B"):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(dates))))
        df = pd.DataFrame(
            {
                "symbol": sym,
                "ts": dates,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
        con.register("df", df)
        con.execute("INSERT INTO bars SELECT * FROM df")
        con.unregister("df")
    con.close()


def _search_child(settings: Settings, experiment: str) -> str:
    client = MlflowClient(settings.mlflow_tracking_uri)
    exp_id = client.get_experiment_by_name(experiment)
    exp_id = exp_id.experiment_id if exp_id else client.create_experiment(experiment)
    return client.create_run(
        exp_id,
        tags={"stage": "search", "candidate_json": _candidate().to_json(), "strategy": "rsi_pullback"},
    ).info.run_id


def test_holdout_guard_blocks_a_repeat_without_running_the_simulation(tmp_path):
    settings = _settings(tmp_path)
    child = _search_child(settings, "test-holdout")
    client = MlflowClient(settings.mlflow_tracking_uri)
    exp_id = client.get_experiment_by_name("test-holdout").experiment_id
    prior = client.create_run(
        exp_id, tags={"stage": "holdout", "source_run_id": child, "candidate_json": _candidate().to_json()}
    ).info.run_id

    # The database does not exist: the guard must fire before any data is loaded.
    with pytest.raises(ValueError, match=f"already run.*{prior}") as exc:
        ps.run_holdout(
            tmp_path / "missing.duckdb",
            settings,
            child_run_id=child,
            base=PortfolioConfig(),
            experiment="test-holdout",
        )
    assert "force=True" in str(exc.value)


def test_holdout_rejects_a_malformed_run_id(tmp_path):
    with pytest.raises(ValueError, match="not an MLflow run id"):
        ps.run_holdout(
            tmp_path / "missing.duckdb",
            _settings(tmp_path),
            child_run_id="x' or tags.stage = 'search",
            base=PortfolioConfig(),
        )


def test_holdout_runs_once_then_needs_force_and_tags_the_repeat(tmp_path):
    settings = _settings(tmp_path)
    db = tmp_path / "market.duckdb"
    _make_bars(db)
    child = _search_child(settings, "test-holdout-run")
    base = PortfolioConfig()
    client = MlflowClient(settings.mlflow_tracking_uri)
    exp_id = client.get_experiment_by_name("test-holdout-run").experiment_id

    ps.run_holdout(db, settings, child_run_id=child, base=base, experiment="test-holdout-run")
    holdouts = client.search_runs([exp_id], filter_string=f"tags.source_run_id = '{child}'")
    assert len(holdouts) == 1
    assert "holdout_repeat" not in holdouts[0].data.tags

    with pytest.raises(ValueError, match="already run"):
        ps.run_holdout(db, settings, child_run_id=child, base=base, experiment="test-holdout-run")

    ps.run_holdout(db, settings, child_run_id=child, base=base, experiment="test-holdout-run", force=True)
    holdouts = client.search_runs([exp_id], filter_string=f"tags.source_run_id = '{child}'")
    assert len(holdouts) == 2
    repeats = [r for r in holdouts if r.data.tags.get("holdout_repeat") == "true"]
    assert len(repeats) == 1
