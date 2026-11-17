"""Strategy search on the portfolio simulator, tracked as MLflow runs.

Three windows, used in this order:
  * train      2015-01-01 .. 2019-12-31   (candidates are compared and gated here)
  * valid      2020-01-01 .. 2022-12-31   (second gate; same rules as train)
  * holdout    2023-01-01 .. end          (one-time check on one chosen candidate, via `run_holdout`;
                                            one-time by convention and enforced: a repeat raises unless force=True)

Signals are computed on the full history so indicator warm-up uses real data. Each window is
then simulated from fresh capital, so no window starts with positions carried over from another.

Goal (both train and valid must pass):
  profit factor >= 2.0, win rate > 50%, and at least `min_round_trips` closed trades.

MLflow layout (experiment `ibkr-portfolio`):
  * one parent run per search round (params: the base account; tags: hypothesis, note)
  * one nested child per candidate (params, metrics for each window, tags: goal_met, candidate_json,
    an equity curve logged as a stepped metric, and the valid-window trade list as an artifact)
  * one run per holdout check, tagged stage=holdout and linked to the candidate it tests
    (a forced repeat is tagged holdout_repeat=true)
"""

from __future__ import annotations

import itertools
import json
import math
import multiprocessing as mp
import os
import re
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import mlflow
import numpy as np
import pandas as pd
from mlflow.entities import Metric, Param
from mlflow.utils.mlflow_tags import MLFLOW_PARENT_RUN_ID

from ibbt.config import Settings
from ibbt.portfolio import PortfolioConfig, portfolio_metrics, run_portfolio
from ibbt.strategies import REGISTRY, make_strategy

EXPERIMENT = "ibkr-portfolio"
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}")
WINDOWS: dict[str, tuple[date, date]] = {
    "train": (date(2015, 1, 1), date(2020, 1, 1)),
    "valid": (date(2020, 1, 1), date(2023, 1, 1)),
    "holdout": (date(2023, 1, 1), date(2100, 1, 1)),
}
SEARCH_WINDOWS = ("train", "valid")
GOAL = {"min_profit_factor": 2.0, "min_win_rate": 0.5, "min_round_trips": 200}

# Strategy parameter grids. Combinations a strategy rejects are dropped.
STRATEGY_GRID: dict[str, dict[str, list[Any]]] = {
    "rsi_pullback": {"entry_rsi": [5, 10], "exit_rsi": [60, 70], "trend": [50, 200]},
    "ibs_reversion": {"trend": [50, 200], "entry_ibs": [0.1, 0.2], "exit_ibs": [0.6, 0.8]},
    "price_action_breakout": {
        "breakout_lookback": [20, 55],
        "support_lookback": [20, 40],
        "support_tol": [0.01, 0.03],
        "max_risk": [0.05, 0.10],
        "leg": ["breakout", "bounce", "both"],
    },
}
LEVEL_MAX_HOLD: list[int | None] = [None, 20, 40]  # time stops tried on top of a level-based stop and target
# Exit rules applied on top of each strategy's signal exit.
EXIT_PRESETS: dict[str, dict[str, list[Any]]] = {
    # Round 1 exit grid (tight exits).
    "r1": {"stop_pct": [None, 0.03, 0.05], "target_pct": [None, 0.04, 0.06, 0.10], "max_hold": [None]},
}
EXIT_GRID: dict[str, list[Any]] = {
    "stop_pct": [None, 0.05, 0.10],
    "target_pct": [None, 0.10, 0.20],
    "max_hold": [None, 5, 10, 20],
}


@dataclass(frozen=True)
class Candidate:
    strategy: str
    strategy_params: tuple[tuple[str, Any], ...]
    stop_pct: float | None = None
    target_pct: float | None = None
    max_hold: int | None = None

    @property
    def params(self) -> dict[str, Any]:
        return dict(self.strategy_params)

    def name(self) -> str:
        body = ",".join(f"{k}={v}" for k, v in self.strategy_params)
        exits = f"stop={self.stop_pct},target={self.target_pct},hold={self.max_hold}"
        return f"{self.strategy}({body})|{exits}"

    def to_json(self) -> str:
        return json.dumps(
            {
                "strategy": self.strategy,
                "strategy_params": self.params,
                "stop_pct": self.stop_pct,
                "target_pct": self.target_pct,
                "max_hold": self.max_hold,
            },
            sort_keys=True,
        )

    @staticmethod
    def from_json(text: str) -> Candidate:
        d = json.loads(text)
        return Candidate(
            strategy=d["strategy"],
            strategy_params=tuple(sorted(d["strategy_params"].items())),
            stop_pct=d["stop_pct"],
            target_pct=d["target_pct"],
            max_hold=d["max_hold"],
        )

    def portfolio_cfg(self, base: PortfolioConfig) -> PortfolioConfig:
        cls = REGISTRY[self.strategy]
        # Level-based strategies: the same max_risk that gates the signal also gates the fill.
        fill_max_risk = self.params.get("max_risk") if cls.uses_levels else None
        return replace(
            base,
            stop_pct=self.stop_pct,
            target_pct=self.target_pct,
            max_hold=self.max_hold,
            signal_exit=cls.signal_exits,
            fill_max_risk=fill_max_risk,
        )


def expand_candidates(
    strategy_grid: dict[str, dict[str, list[Any]]] = STRATEGY_GRID,
    exit_grid: dict[str, list[Any]] = EXIT_GRID,
    strategies: list[str] | None = None,
) -> list[Candidate]:
    exit_keys = list(exit_grid)
    exit_combos = [dict(zip(exit_keys, v, strict=True)) for v in itertools.product(*exit_grid.values())]
    level_combos = [{"stop_pct": None, "target_pct": None, "max_hold": h} for h in LEVEL_MAX_HOLD]
    out: list[Candidate] = []
    for name, space in strategy_grid.items():
        if strategies and name not in strategies:
            continue
        keys = list(space)
        for values in itertools.product(*(space[k] for k in keys)):
            params = dict(zip(keys, values, strict=True))
            try:
                make_strategy(name, params)
            except ValueError:
                continue
            # Level-based strategies carry their own stop and target, so only a time-stop variant is searched.
            combos = level_combos if REGISTRY[name].uses_levels else exit_combos
            for exits in combos:
                out.append(Candidate(name, tuple(sorted(params.items())), **exits))
    return out


@dataclass
class Universe:
    opens: pd.DataFrame
    highs: pd.DataFrame
    lows: pd.DataFrame
    closes: pd.DataFrame
    bars: dict[str, pd.DataFrame] = field(repr=False, default_factory=dict)
    excluded_for_quality: int = 0  # symbols dropped by the data-quality screen

    @property
    def n_symbols(self) -> int:
        return len(self.opens.columns)


def load_universe(db_path: str | Path, symbols: list[str] | None = None) -> Universe:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        sql = "SELECT symbol, ts, open, high, low, close, volume FROM bars"
        params: list[Any] = []
        if symbols:
            sql += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
            params = list(symbols)
        df = con.execute(sql + " ORDER BY symbol, ts", params).df()
    finally:
        con.close()
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values(["symbol", "ts"])
    # Data-quality screen, causal. Each bar is judged only from itself and the prior bar, so a decision on date t
    # never depends on data after t. From a symbol's first corrupt bar onward, the symbol is cut off: its later
    # history is dropped, so the test cannot skip a bad stock at the start and keep it afterwards.
    # Corrupt means: a non-positive price, an inverted high/low, a high above 4x the low,
    # or a one-day move beyond 3x / below 1/3 of the prior close (unit glitches, stale ticks).
    # No absolute price cap: it removed high-priced rupee stocks with no corruption evidence
    # (see data/runs/screen_evidence.md).
    prev = df.groupby("symbol")["close"].shift(1)
    corrupt = (
        (df["close"] <= 0)
        | (df["high"] < df["low"])
        | (df["high"] > 4 * df["low"])
        | ((prev > 0) & ((df["close"] / prev > 3) | (df["close"] / prev < 1 / 3)))
    )
    first_bad = df.loc[corrupt].groupby("symbol")["ts"].min()
    cutoff = pd.to_datetime(df["symbol"].map(first_bad.to_dict()))
    df = df[cutoff.isna() | (df["ts"] < cutoff)]
    bad_symbols = set(first_bad.index)
    # No minimum-history filter over the full span: that would let future bar counts decide inclusion.
    # Indicators stay flat during their own warm-up, so short histories simply produce no trades.

    wide = {c: df.pivot(index="ts", columns="symbol", values=c).sort_index() for c in ("open", "high", "low", "close")}
    bars = {sym: g.set_index("ts")[["open", "high", "low", "close", "volume"]] for sym, g in df.groupby("symbol")}
    return Universe(wide["open"], wide["high"], wide["low"], wide["close"], bars, excluded_for_quality=len(bad_symbols))


Panel = tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]


def _panel(univ: Universe, strategy: str, params: tuple[tuple[str, Any], ...], cache: dict) -> Panel:
    """Signal, rank, stop and target frames (dates x symbols) for one strategy config, cached across exit rules."""
    key = (strategy, params)
    if key in cache:
        return cache[key]
    strat_params = dict(params)
    breadth_min = float(strat_params.pop("breadth_min", 0.0))  # portfolio-level regime filter, not a strategy arg
    strat = make_strategy(strategy, strat_params)
    sig: dict[str, pd.Series] = {}
    rank: dict[str, pd.Series] = {}
    stops: dict[str, pd.Series] = {}
    targets: dict[str, pd.Series] = {}
    for sym, bars in univ.bars.items():
        sig[sym] = strat.signal(bars)
        score = strat.rank_score(bars)
        if score is not None:
            rank[sym] = score
        levels = strat.levels(bars)
        if levels is not None:
            stops[sym] = levels["stop"]
            targets[sym] = levels["target"]

    def frame(d: dict[str, pd.Series]) -> pd.DataFrame | None:
        if not d:
            return None
        return pd.DataFrame(d).reindex(index=univ.opens.index, columns=univ.opens.columns)

    sig_df = pd.DataFrame(sig).reindex(index=univ.opens.index, columns=univ.opens.columns).fillna(0).astype(np.int8)
    if breadth_min > 0:
        # Regime: share of the universe closing above its 200-day average. Entries only when breadth is high.
        above = univ.closes > univ.closes.rolling(200).mean()
        breadth = above.sum(axis=1) / univ.closes.notna().sum(axis=1).replace(0, np.nan)
        sig_df = sig_df.mul((breadth >= breadth_min).fillna(False).astype(np.int8), axis=0).astype(np.int8)
    cache[key] = (sig_df, frame(rank), frame(stops), frame(targets))
    return cache[key]


def _window_slice(univ: Universe, window: str) -> pd.Series:
    start, stop = WINDOWS[window]
    idx = univ.opens.index
    return (idx >= pd.Timestamp(start)) & (idx < pd.Timestamp(stop))


def simulate(
    univ: Universe,
    cand: Candidate,
    base: PortfolioConfig,
    window: str,
    cache: dict,
    *,
    unconstrained: bool = False,
) -> tuple[dict[str, float], Any, PortfolioConfig]:
    """Run one candidate on one window. Returns (metrics, result, cfg)."""
    sig, rank, stops, targets = _panel(univ, cand.strategy, tuple(sorted(cand.params.items())), cache)
    cfg = cand.portfolio_cfg(base)
    if unconstrained:
        cfg = replace(cfg, max_positions=None)
    mask = _window_slice(univ, window)
    result = run_portfolio(
        univ.opens[mask],
        univ.highs[mask],
        univ.lows[mask],
        univ.closes[mask],
        sig[mask],
        cfg,
        rank=rank[mask] if rank is not None else None,
        stop_levels=stops[mask] if stops is not None else None,
        target_levels=targets[mask] if targets is not None else None,
    )
    return portfolio_metrics(result, cfg), result, cfg


def passes_goal(metrics: dict[str, float]) -> bool:
    return (
        metrics["profit_factor"] >= GOAL["min_profit_factor"]
        and metrics["win_rate"] > GOAL["min_win_rate"]
        and metrics["round_trips"] >= GOAL["min_round_trips"]
    )


def evaluate(univ: Universe, cand: Candidate, base: PortfolioConfig, cache: dict) -> dict[str, Any]:
    """Score one candidate on the search windows, with pooled (unconstrained) stats alongside."""
    out: dict[str, Any] = {"candidate": cand, "results": {}}
    for window in SEARCH_WINDOWS:
        metrics, result, _ = simulate(univ, cand, base, window, cache)
        pooled, _, _ = simulate(univ, cand, base, window, cache, unconstrained=True)
        out["results"][window] = {"metrics": metrics, "trades": result.trades, "equity": result.equity}
        out["results"][f"{window}_pooled"] = {"metrics": pooled}
    out["goal_met"] = all(passes_goal(out["results"][w]["metrics"]) for w in SEARCH_WINDOWS)
    return out


def _flat_metrics(results: dict[str, Any]) -> dict[str, float]:
    flat: dict[str, float] = {}
    for window in SEARCH_WINDOWS:
        for k, v in results[window]["metrics"].items():
            if isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v):
                flat[f"{window}_{k}"] = float(v)
        pooled = results[f"{window}_pooled"]["metrics"]
        for k in ("profit_factor", "win_rate", "round_trips"):
            v = pooled[k]
            if not math.isnan(v) and not math.isinf(v):
                flat[f"{window}_pooled_{k}"] = float(v)
    return flat


def _valid_pf_key(e: dict[str, Any]) -> float:
    pf = e["results"]["valid"]["metrics"]["profit_factor"]
    return pf if math.isfinite(pf) else -1.0


def log_round(
    evaluated: list[dict[str, Any]],
    *,
    settings: Settings,
    base: PortfolioConfig,
    n_symbols: int,
    excluded_for_quality: int = 0,
    hypothesis: str,
    note: str,
    experiment: str = EXPERIMENT,
) -> str:
    """Log one search round with batched writes: one `log_batch` call per run, not one per metric.

    A parent run for the round and a nested child per candidate. Parent and children are created through
    MlflowClient, so each run costs a handful of commits instead of one commit per parameter, metric or
    equity point. If anything fails mid-round, the open children and the parent are still terminated, the
    parent with status FAILED. Returns the parent run id.
    """
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    exp_id = mlflow.set_experiment(experiment).experiment_id
    now = int(time.time() * 1000)
    stamp = pd.Timestamp.now().strftime("%Y%m%d-%H%M%S")

    parent_id = client.create_run(
        exp_id,
        run_name=f"round-{stamp}",
        tags={
            "project": "ibkr-backtest",
            "kind": "portfolio_search",
            "stage": "search",
            "hypothesis": hypothesis,
            "note": note,
        },
    ).info.run_id
    open_children: list[str] = []  # created but not yet terminated
    status = "FAILED"
    try:
        round_params = {
            **base.as_params(),
            "n_symbols": n_symbols,
            "excluded_for_quality": excluded_for_quality,
            "n_candidates": len(evaluated),
        }
        round_params.update({f"window_{w}": f"{a}..{b}" for w, (a, b) in WINDOWS.items()})
        client.log_batch(
            parent_id,
            params=[Param(k, str(v)) for k, v in round_params.items()],
            metrics=[Metric("candidates_passing_goal", float(sum(e["goal_met"] for e in evaluated)), now, 0)],
        )

        # Heavy artifacts (equity curve, trade list) only for the top 10 by validation PF.
        top_ids = {id(e) for e in sorted(evaluated, key=_valid_pf_key, reverse=True)[:10]}
        rows = []
        for e in evaluated:
            cand: Candidate = e["candidate"]
            child_id = client.create_run(
                exp_id,
                run_name=cand.name()[:250],
                tags={
                    MLFLOW_PARENT_RUN_ID: parent_id,
                    "stage": "search",
                    "strategy": cand.strategy,
                    "goal_met": str(e["goal_met"]).lower(),
                    "candidate_json": cand.to_json(),
                    "source_parent_run": parent_id,
                },
            ).info.run_id
            open_children.append(child_id)
            metrics = [Metric(k, v, now, 0) for k, v in _flat_metrics(e["results"]).items()]
            params = {
                **cand.params,
                "stop_pct": cand.stop_pct,
                "target_pct": cand.target_pct,
                "max_hold": cand.max_hold,
            }
            if id(e) in top_ids:
                valid_eq = e["results"]["valid"]["equity"].iloc[::21]
                metrics += [Metric("valid_equity", float(v), now, step) for step, v in enumerate(valid_eq.to_numpy())]
            client.log_batch(
                child_id,
                metrics=metrics[:1000],
                params=[Param(k, str(v)) for k, v in params.items()],
            )
            if id(e) in top_ids:
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "valid_trades.csv"
                    e["results"]["valid"]["trades"].to_csv(path, index=False)
                    client.log_artifact(child_id, str(path), artifact_path="trades")
            client.set_terminated(child_id)
            open_children.remove(child_id)
            rows.append(
                {
                    "run_id": child_id,
                    "candidate": cand.name(),
                    "goal_met": e["goal_met"],
                    **{k: v for k, v in _flat_metrics(e["results"]).items() if k in LEADERBOARD_COLS},
                }
            )

        leaderboard = pd.DataFrame(rows).sort_values(["goal_met", "valid_profit_factor"], ascending=[False, False])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leaderboard.csv"
            leaderboard.to_csv(path, index=False)
            client.log_artifact(parent_id, str(path))
        if not leaderboard.empty:
            best = leaderboard.iloc[0]
            client.log_batch(
                parent_id,
                metrics=[
                    Metric("best_valid_profit_factor", float(best["valid_profit_factor"]), now, 0),
                    Metric("best_valid_win_rate", float(best["valid_win_rate"]), now, 0),
                ],
            )
        status = "FINISHED"
    finally:
        for child_id in open_children:
            client.set_terminated(child_id, status="FAILED")
        client.set_terminated(parent_id, status=status)
    return parent_id


LEADERBOARD_COLS = [
    "train_profit_factor",
    "train_win_rate",
    "train_round_trips",
    "valid_profit_factor",
    "valid_win_rate",
    "valid_round_trips",
    "valid_pooled_profit_factor",
    "valid_pooled_win_rate",
    "valid_total_return",
    "valid_max_drawdown",
]


# Shared with forked worker processes (copy-on-write), so the universe is loaded once.
_UNIV: Universe | None = None
_BASE: PortfolioConfig | None = None


def _eval_group(cands: list[Candidate]) -> list[dict[str, Any]]:
    """Evaluate every exit variant of one strategy config. The signal panel is computed once per group."""
    assert _UNIV is not None and _BASE is not None
    cache: dict = {}
    return [evaluate(_UNIV, c, _BASE, cache) for c in cands]


def search(
    db_path: str | Path,
    settings: Settings,
    *,
    base: PortfolioConfig,
    hypothesis: str,
    note: str = "",
    symbols: list[str] | None = None,
    strategies: list[str] | None = None,
    experiment: str = EXPERIMENT,
    workers: int | None = None,
    exit_grid: dict[str, list[Any]] = EXIT_GRID,
) -> tuple[str, pd.DataFrame]:
    cands = expand_candidates(strategies=strategies, exit_grid=exit_grid)
    if not cands:
        raise ValueError(
            f"no candidates: none of the requested strategies has a search grid "
            f"(strategies={strategies}, searchable: {sorted(STRATEGY_GRID)})"
        )
    global _UNIV, _BASE
    univ = load_universe(db_path, symbols)
    _UNIV, _BASE = univ, base
    groups: dict[tuple, list[Candidate]] = {}
    for cand in cands:
        groups.setdefault((cand.strategy, cand.strategy_params), []).append(cand)

    evaluated: list[dict[str, Any]] = []
    # Each worker holds its own pandas copies of the universe, so memory bounds the worker count (7 GB RAM here).
    default_workers = int(os.getenv("IBBT_WORKERS", str(os.cpu_count() or 1)))
    n_workers = min(workers or default_workers, len(groups))
    with ProcessPoolExecutor(max_workers=n_workers, mp_context=mp.get_context("fork")) as pool:
        for k, group_result in enumerate(pool.map(_eval_group, groups.values()), 1):
            evaluated.extend(group_result)
            print(f"{k}/{len(groups)} strategy configs ({len(evaluated)}/{len(cands)} candidates)", flush=True)
    run_id = log_round(
        evaluated,
        settings=settings,
        base=base,
        n_symbols=univ.n_symbols,
        excluded_for_quality=univ.excluded_for_quality,
        hypothesis=hypothesis,
        note=note,
        experiment=experiment,
    )
    table = pd.DataFrame(
        [
            {
                "candidate": e["candidate"].name(),
                "goal_met": e["goal_met"],
                **{k: v for k, v in _flat_metrics(e["results"]).items() if k in LEADERBOARD_COLS},
            }
            for e in evaluated
        ]
    ).sort_values(["goal_met", "valid_profit_factor"], ascending=[False, False])
    return run_id, table


def run_holdout(
    db_path: str | Path,
    settings: Settings,
    *,
    child_run_id: str,
    base: PortfolioConfig,
    experiment: str = EXPERIMENT,
    force: bool = False,
) -> dict[str, float]:
    """Run one candidate on the holdout window. Logged as a new run linked to the candidate.

    The holdout is one-time by convention, and this is enforced: if a holdout run already exists for
    `child_run_id` in the experiment, this raises ValueError unless `force=True`. A forced repeat still runs,
    and its run is tagged holdout_repeat=true so the contamination stays visible.
    """
    if not _RUN_ID_RE.fullmatch(child_run_id):
        raise ValueError(f"not an MLflow run id: {child_run_id!r}")
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    source = client.get_run(child_run_id)
    cand = Candidate.from_json(source.data.tags["candidate_json"])
    if source.data.tags.get("stage") != "search":
        raise ValueError(f"run {child_run_id} is not a search candidate")

    exp_id = mlflow.set_experiment(experiment).experiment_id
    prior = client.search_runs(
        [exp_id],
        filter_string=f"tags.stage = 'holdout' and tags.source_run_id = '{child_run_id}'",
        max_results=1,
    )
    if prior and not force:
        raise ValueError(
            f"holdout was already run for candidate {child_run_id} (holdout run {prior[0].info.run_id}). "
            "The holdout is one-time; pass force=True (CLI: --force) to run it again anyway."
        )

    univ = load_universe(db_path)
    metrics, result, _ = simulate(univ, cand, base, "holdout", {})
    pooled, _, _ = simulate(univ, cand, base, "holdout", {}, unconstrained=True)

    with mlflow.start_run(run_name=f"holdout-{cand.strategy}") as run:
        mlflow.set_tags(
            {
                "stage": "holdout",
                "source_run_id": child_run_id,
                "candidate_json": cand.to_json(),
                "strategy": cand.strategy,
            }
        )
        if prior:
            mlflow.set_tag("holdout_repeat", "true")
        mlflow.log_params(
            {**cand.params, "stop_pct": cand.stop_pct, "target_pct": cand.target_pct, "max_hold": cand.max_hold}
        )
        mlflow.log_metrics({f"holdout_{k}": v for k, v in metrics.items() if not (math.isnan(v) or math.isinf(v))})
        mlflow.log_metrics(
            {
                f"holdout_pooled_{k}": v
                for k, v in pooled.items()
                if k in ("profit_factor", "win_rate", "round_trips") and not (math.isnan(v) or math.isinf(v))
            }
        )
        mlflow.set_tag("goal_met_holdout", str(passes_goal(metrics)).lower())
        for step, (_, value) in enumerate(result.equity.iloc[::21].items()):
            mlflow.log_metric("holdout_equity", float(value), step=step)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "holdout_trades.csv"
            result.trades.to_csv(path, index=False)
            mlflow.log_artifact(str(path), artifact_path="trades")
        print(f"holdout run {run.info.run_id}")
    return metrics


def pick_best(settings: Settings, experiment: str = EXPERIMENT) -> str:
    """Child run id of the best search candidate that passed the goal on both windows."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    runs = mlflow.search_runs(
        experiment_names=[experiment],
        filter_string="tags.stage = 'search' and tags.goal_met = 'true'",
        order_by=["metrics.valid_profit_factor DESC"],
        max_results=1,
    )
    if runs.empty:
        raise LookupError("no search candidate has passed the goal on train and valid yet")
    return str(runs.iloc[0]["run_id"])
