"""Portfolio candidate search driven by Optuna (TPE), as an alternative to the exhaustive grid in `portfolio_search`.

This module only proposes candidates. `portfolio_search.search(method="optuna")` scores them, logs them and
returns the leaderboard, exactly as it does for the grid, so the two modes stay comparable.

Leakage rule: the objective reads only the `valid` window (the search windows are `train` and `valid`).
The holdout is never evaluated here, so `run_holdout` remains a one-time check.

Optuna is imported lazily, so the rest of the CLI does not pay for it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from ibbt.portfolio_search import EXIT_GRID, GOAL, LEVEL_MAX_HOLD, STRATEGY_GRID, Candidate
from ibbt.strategies import REGISTRY, make_strategy

PF_CAP = 10.0  # infinite profit factor (no losing trades) is capped so one run cannot dominate the sampler
INVALID_SCORE = -1.0  # below the trade-count floor, or a rejected configuration


def score_metrics(valid: dict[str, float]) -> float:
    """Objective: validation profit factor, only for configurations that clear the trade-count floor."""
    rt = valid.get("round_trips", math.nan)
    if not math.isfinite(rt) or rt < GOAL["min_round_trips"]:
        return INVALID_SCORE
    pf = valid.get("profit_factor", math.nan)
    if math.isnan(pf):
        return INVALID_SCORE
    return min(pf, PF_CAP)


def _suggest_candidate(trial: Any, strategy_grid: dict, exit_grid: dict) -> Candidate:
    """Sample one candidate. Parameter names are prefixed with the strategy so conditional spaces stay distinct."""
    name = trial.suggest_categorical("strategy", sorted(strategy_grid))
    space = strategy_grid[name]
    params = {k: trial.suggest_categorical(f"{name}.{k}", list(v)) for k, v in space.items()}
    if REGISTRY[name].uses_levels:
        exits = {
            "stop_pct": None,
            "target_pct": None,
            "max_hold": trial.suggest_categorical("max_hold", LEVEL_MAX_HOLD),
        }
    else:
        exits = {
            "stop_pct": trial.suggest_categorical("stop_pct", list(exit_grid["stop_pct"])),
            "target_pct": trial.suggest_categorical("target_pct", list(exit_grid["target_pct"])),
            "max_hold": trial.suggest_categorical("max_hold", list(exit_grid["max_hold"])),
        }
    return Candidate(name, tuple(sorted(params.items())), **exits)


def optimize(
    evaluate_batch: Callable[[list[Candidate]], list[dict[str, Any] | None]],
    *,
    n_trials: int,
    seed: int,
    batch_size: int = 16,
    strategy_grid: dict = STRATEGY_GRID,
    exit_grid: dict = EXIT_GRID,
) -> list[dict[str, Any]]:
    """Ask/tell loop. `evaluate_batch` returns one evaluation dict (from `portfolio_search.evaluate`) per
    candidate, or None for a candidate that cannot be run. Returns the unique evaluations, in proposal order.
    Duplicate proposals are scored from the cache, not re-evaluated.
    """
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    cache: dict[str, dict[str, Any]] = {}
    order: list[dict[str, Any]] = []
    remaining = n_trials
    while remaining > 0:
        n = min(batch_size, remaining)
        remaining -= n
        trials, cands, keys = [], [], []
        for _ in range(n):
            trial = study.ask()
            try:
                cand = _suggest_candidate(trial, strategy_grid, exit_grid)
                make_strategy(cand.strategy, cand.params)  # rejects e.g. fast >= slow
            except ValueError:
                study.tell(trial, INVALID_SCORE)
                continue
            key = cand.to_json()
            trials.append(trial)
            cands.append(cand)
            keys.append(key)

        # Evaluate only candidates not seen before in this study.
        fresh = [c for c, k in zip(cands, keys, strict=True) if k not in cache]
        fresh_unique = list({c.to_json(): c for c in fresh}.values())
        if fresh_unique:
            for cand, ev in zip(fresh_unique, evaluate_batch(fresh_unique), strict=True):
                cache[cand.to_json()] = ev if ev is not None else {"candidate": cand, "results": None}
                if ev is not None:
                    order.append(ev)

        for trial, key in zip(trials, keys, strict=True):
            ev = cache[key]
            score = score_metrics(ev["results"]["valid"]["metrics"]) if ev["results"] else INVALID_SCORE
            study.tell(trial, score)

    return order
