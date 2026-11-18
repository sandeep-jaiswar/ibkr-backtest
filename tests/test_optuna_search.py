"""Optuna proposal loop: on a small space with a known best, TPE must find the exhaustive winner.

The evaluator is a deterministic fake, so the test checks the search logic without bars or MLflow.
"""

from __future__ import annotations

import itertools
import math
import zlib

from ibbt.optuna_search import optimize, score_metrics
from ibbt.portfolio_search import Candidate

STRATEGY_GRID = {
    # trend=1 is rejected by rsi_pullback (needs >= 2), so the rejection path runs too.
    "rsi_pullback": {"entry_rsi": [5, 10], "exit_rsi": [60, 70], "trend": [1, 50]},
}
EXIT_GRID = {"stop_pct": [None, 0.05], "target_pct": [None, 0.10], "max_hold": [None, 5]}
BEST = {"entry_rsi": 5, "exit_rsi": 70, "trend": 50, "stop_pct": 0.05, "target_pct": 0.10, "max_hold": 5}


def _pf(c: Candidate) -> float:
    params = {**c.params, "stop_pct": c.stop_pct, "target_pct": c.target_pct, "max_hold": c.max_hold}
    base = 1.0 + 0.1 * sum(zlib.crc32(f"{k}={v}".encode()) % 7 for k, v in sorted(params.items())) / 7
    return base + (2.0 if all(params[k] == v for k, v in BEST.items()) else 0.0)


def _fake_evaluate(cands):
    out = []
    for c in cands:
        pf = _pf(c)
        out.append({"candidate": c, "results": {"valid": {"metrics": {"profit_factor": pf, "round_trips": 500.0}}}})
    return out


def _exhaustive_best() -> Candidate:
    cands = []
    for entry, exit_, trend in itertools.product([5, 10], [60, 70], [1, 50]):
        if trend < 2:
            continue
        params = {"entry_rsi": entry, "exit_rsi": exit_, "trend": trend}
        for stop, target, hold in itertools.product(*EXIT_GRID.values()):
            cands.append(Candidate("rsi_pullback", tuple(sorted(params.items())), stop, target, hold))
    return max(cands, key=_pf)


def test_tpe_finds_the_exhaustive_best_and_skips_invalid_configs():
    evaluated = optimize(
        _fake_evaluate,
        n_trials=200,
        seed=7,
        batch_size=16,
        strategy_grid=STRATEGY_GRID,
        exit_grid=EXIT_GRID,
    )
    best = max(evaluated, key=lambda e: e["results"]["valid"]["metrics"]["profit_factor"])["candidate"]
    assert best == _exhaustive_best()
    assert all(e["candidate"].params["trend"] >= 2 for e in evaluated)


def test_duplicate_proposals_are_evaluated_once():
    seen: list[str] = []

    def counting(cands):
        seen.extend(c.to_json() for c in cands)
        return _fake_evaluate(cands)

    evaluated = optimize(
        counting, n_trials=120, seed=3, batch_size=10, strategy_grid=STRATEGY_GRID, exit_grid=EXIT_GRID
    )
    assert len(seen) == len(set(seen))
    assert len(evaluated) == len(seen)


def test_score_is_capped_and_floors_trade_count():
    assert score_metrics({"profit_factor": math.inf, "round_trips": 500.0}) == 10.0
    assert score_metrics({"profit_factor": 5.0, "round_trips": 50.0}) == -1.0
    assert score_metrics({"profit_factor": math.nan, "round_trips": 500.0}) == -1.0
    assert score_metrics({"profit_factor": 2.5, "round_trips": 500.0}) == 2.5
