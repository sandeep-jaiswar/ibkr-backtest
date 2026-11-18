"""Parallel paths must return exactly what the serial path returns, in the same order."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ibbt.optuna_search import optimize
from ibbt.parallel import pmap
from ibbt.search import run_search
from ibbt.store import Store
from ibbt.synthetic import synthetic_bars


def _square(x: int) -> int:
    return x * x


def test_pmap_matches_serial_and_keeps_order():
    items = list(range(40))
    assert pmap(_square, items, workers=1) == [x * x for x in items]
    assert pmap(_square, items, workers=4) == [x * x for x in items]


def test_pmap_stays_serial_below_threshold():
    # With fewer items than min_items the call must not fork; a lambda can only run serially here.
    assert pmap(lambda x: x + 1, [1, 2], workers=8, min_items=5) == [2, 3]


@pytest.fixture
def small_db(tmp_path):
    path = tmp_path / "par.duckdb"
    with Store(path) as store:
        for i, symbol in enumerate(["AAA", "BBB", "CCC", "DDD"]):
            bars = synthetic_bars("2019-01-01", "2022-12-30", seed=i).copy()
            store.upsert_bars(symbol, bars)
    return str(path)


def test_run_search_is_identical_for_one_and_many_workers(small_db, monkeypatch):
    grid = {"sma_crossover": {"fast": [10, 20], "slow": [50, 100]}}
    results = {}
    for workers in ("1", "3"):
        monkeypatch.setenv("IBBT_WORKERS", workers)
        results[workers] = run_search(small_db, date(2021, 1, 1), grid=grid)
    pd.testing.assert_frame_equal(results["1"], results["3"], check_exact=True)
    assert results["1"]["is_n"].sum() > 0  # the comparison is not trivially empty


def _fake_score(candidate_key: str) -> float:
    return (sum(map(ord, candidate_key)) % 97) / 10.0 + (2.0 if "rsi_pullback" in candidate_key else 0.0)


def _fake_eval_one(c):
    pf = _fake_score(c.to_json())
    return {"candidate": c, "results": {"valid": {"metrics": {"profit_factor": pf, "round_trips": 500.0}}}}


def test_seeded_optuna_proposals_do_not_depend_on_worker_count():
    grid = {"rsi_pullback": {"entry_rsi": [5, 10], "exit_rsi": [60, 70], "trend": [50, 200]}}
    exits = {"stop_pct": [None, 0.05], "target_pct": [None, 0.10], "max_hold": [None, 5]}

    def make_eval(workers):
        def evaluate_batch(cands):
            return pmap(_fake_eval_one, cands, workers=workers, min_items=2)

        return evaluate_batch

    runs = {
        w: [
            e["candidate"].to_json()
            for e in optimize(make_eval(w), n_trials=60, seed=5, batch_size=8, strategy_grid=grid, exit_grid=exits)
        ]
        for w in (1, 3)
    }
    assert runs[1] == runs[3]
