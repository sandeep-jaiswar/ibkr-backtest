"""Strategy search on the portfolio simulator, tracked as MLflow runs.

Three windows, used in this order:
  * train      2015-01-01 .. 2019-12-31   (candidates are compared and gated here)
  * valid      2020-01-01 .. 2022-12-31   (second gate; same rules as train)
  * holdout    2023-01-01 .. end          (run once, on one chosen candidate, via `run_holdout`)

Signals are computed on the full history so indicator warm-up uses real data. Each window is
then simulated from fresh capital, so no window starts with positions carried over from another.

Goal (both train and valid must pass):
  profit factor >= 2.0, win rate > 50%, and at least `min_round_trips` closed trades.

MLflow layout (experiment `ibkr-portfolio`):
  * one parent run per search round (params: the base account; tags: hypothesis, note)
  * one nested child per candidate (params, metrics for each window, tags: goal_met, candidate_json,
    an equity curve logged as a stepped metric, and the valid-window trade list as an artifact)
  * one run per holdout check, tagged stage=holdout and linked to the candidate it tests
"""

from __future__ import annotations

import itertools
import json
import math
import tempfile
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import mlflow
import numpy as np
import pandas as pd

from ibbt.config import Settings
from ibbt.portfolio import PortfolioConfig, portfolio_metrics, run_portfolio
from ibbt.strategies import make_strategy

EXPERIMENT = "ibkr-portfolio"
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
}
# Exit rules applied on top of each strategy's signal exit.
EXIT_GRID: dict[str, list[Any]] = {
    "stop_pct": [None, 0.03, 0.05],
    "target_pct": [None, 0.04, 0.06, 0.10],
    "max_hold": [None],
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
        return replace(base, stop_pct=self.stop_pct, target_pct=self.target_pct, max_hold=self.max_hold)


def expand_candidates(
    strategy_grid: dict[str, dict[str, list[Any]]] = STRATEGY_GRID,
    exit_grid: dict[str, list[Any]] = EXIT_GRID,
    strategies: list[str] | None = None,
) -> list[Candidate]:
    exit_keys = list(exit_grid)
    exit_combos = [dict(zip(exit_keys, v, strict=True)) for v in itertools.product(*exit_grid.values())]
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
            for exits in exit_combos:
                out.append(Candidate(name, tuple(sorted(params.items())), **exits))
    return out


@dataclass
class Universe:
    opens: pd.DataFrame
    highs: pd.DataFrame
    lows: pd.DataFrame
    closes: pd.DataFrame
    bars: dict[str, pd.DataFrame] = field(repr=False, default_factory=dict)

    @property
    def n_symbols(self) -> int:
        return len(self.opens.columns)


def load_universe(db_path: str | Path, symbols: list[str] | None = None, min_bars: int = 250) -> Universe:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        sql = "SELECT symbol, ts, open, high, low, close FROM bars"
        params: list[Any] = []
        if symbols:
            sql += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
            params = list(symbols)
        df = con.execute(sql + " ORDER BY symbol, ts", params).df()
    finally:
        con.close()
    df["ts"] = pd.to_datetime(df["ts"])
    counts = df.groupby("symbol").size()
    df = df[df["symbol"].isin(counts[counts >= min_bars].index)]

    wide = {c: df.pivot(index="ts", columns="symbol", values=c).sort_index() for c in ("open", "high", "low", "close")}
    bars = {sym: g.set_index("ts")[["open", "high", "low", "close"]] for sym, g in df.groupby("symbol")}
    return Universe(wide["open"], wide["high"], wide["low"], wide["close"], bars)


def _panel(
    univ: Universe, strategy: str, params: tuple[tuple[str, Any], ...], cache: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Signal and rank frames (dates x symbols) for one strategy config, cached across exit rules."""
    key = (strategy, params)
    if key in cache:
        return cache[key]
    strat = make_strategy(strategy, dict(params))
    sig: dict[str, pd.Series] = {}
    rank: dict[str, pd.Series] = {}
    for sym, bars in univ.bars.items():
        sig[sym] = strat.signal(bars)
        score = strat.rank_score(bars)
        if score is not None:
            rank[sym] = score
    sig_df = pd.DataFrame(sig).reindex(index=univ.opens.index, columns=univ.opens.columns).fillna(0).astype(np.int8)
    rank_df = (
        pd.DataFrame(rank).reindex(index=univ.opens.index, columns=univ.opens.columns) if rank else None
    )
    cache[key] = (sig_df, rank_df)
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
    sig, rank = _panel(univ, cand.strategy, tuple(sorted(cand.params.items())), cache)
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


def log_round(
    evaluated: list[dict[str, Any]],
    *,
    settings: Settings,
    base: PortfolioConfig,
    n_symbols: int,
    hypothesis: str,
    note: str,
    experiment: str = EXPERIMENT,
) -> str:
    """Log one search round: a parent run and a nested child per candidate. Returns the parent run id."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(experiment)
    stamp = pd.Timestamp.now().strftime("%Y%m%d-%H%M%S")
    with mlflow.start_run(run_name=f"round-{stamp}") as parent:
        mlflow.set_tags(
            {"project": "ibkr-backtest", "kind": "portfolio_search", "stage": "search", "hypothesis": hypothesis, "note": note}
        )
        mlflow.log_params(
            {**base.as_params(), "n_symbols": n_symbols, "n_candidates": len(evaluated)}
        )
        mlflow.log_params({f"window_{w}": f"{a}..{b}" for w, (a, b) in WINDOWS.items()})
        n_pass = sum(e["goal_met"] for e in evaluated)
        mlflow.log_metric("candidates_passing_goal", n_pass)

        rows = []
        for e in evaluated:
            cand: Candidate = e["candidate"]
            with mlflow.start_run(run_name=cand.name()[:250], nested=True) as child:
                mlflow.set_tags(
                    {
                        "stage": "search",
                        "strategy": cand.strategy,
                        "goal_met": str(e["goal_met"]).lower(),
                        "candidate_json": cand.to_json(),
                        "source_parent_run": parent.info.run_id,
                    }
                )
                mlflow.log_params({**cand.params, "stop_pct": cand.stop_pct, "target_pct": cand.target_pct, "max_hold": cand.max_hold})
                mlflow.log_metrics(_flat_metrics(e["results"]))
                valid_eq = e["results"]["valid"]["equity"]
                for step, (_, value) in enumerate(valid_eq.iloc[::21].items()):
                    mlflow.log_metric("valid_equity", float(value), step=step)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "valid_trades.csv"
                    e["results"]["valid"]["trades"].to_csv(path, index=False)
                    mlflow.log_artifact(str(path), artifact_path="trades")
                rows.append(
                    {
                        "run_id": child.info.run_id,
                        "candidate": cand.name(),
                        "goal_met": e["goal_met"],
                        **{k: v for k, v in _flat_metrics(e["results"]).items() if k in LEADERBOARD_COLS},
                    }
                )

        leaderboard = pd.DataFrame(rows).sort_values(
            ["goal_met", "valid_profit_factor"], ascending=[False, False]
        )
        mlflow.log_table(leaderboard, artifact_file="leaderboard.json")
        if not leaderboard.empty:
            best = leaderboard.iloc[0]
            mlflow.log_metric("best_valid_profit_factor", float(best["valid_profit_factor"]))
            mlflow.log_metric("best_valid_win_rate", float(best["valid_win_rate"]))
        return parent.info.run_id


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
) -> tuple[str, pd.DataFrame]:
    univ = load_universe(db_path, symbols)
    cands = expand_candidates(strategies=strategies)
    cache: dict = {}
    evaluated = []
    for k, cand in enumerate(cands, 1):
        evaluated.append(evaluate(univ, cand, base, cache))
        if k % 10 == 0:
            print(f"{k}/{len(cands)} candidates", flush=True)
    run_id = log_round(
        evaluated,
        settings=settings,
        base=base,
        n_symbols=univ.n_symbols,
        hypothesis=hypothesis,
        note=note,
        experiment=experiment,
    )
    table = pd.DataFrame(
        [
            {"candidate": e["candidate"].name(), "goal_met": e["goal_met"], **{k: v for k, v in _flat_metrics(e["results"]).items() if k in LEADERBOARD_COLS}}
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
) -> dict[str, float]:
    """Run one candidate on the holdout window, once. Logged as a new run linked to the candidate."""
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    client = mlflow.MlflowClient()
    source = client.get_run(child_run_id)
    cand = Candidate.from_json(source.data.tags["candidate_json"])
    if source.data.tags.get("stage") != "search":
        raise ValueError(f"run {child_run_id} is not a search candidate")

    univ = load_universe(db_path)
    metrics, result, _ = simulate(univ, cand, base, "holdout", {})
    pooled, _, _ = simulate(univ, cand, base, "holdout", {}, unconstrained=True)

    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=f"holdout-{cand.strategy}") as run:
        mlflow.set_tags(
            {
                "stage": "holdout",
                "source_run_id": child_run_id,
                "candidate_json": cand.to_json(),
                "strategy": cand.strategy,
            }
        )
        mlflow.log_params({**cand.params, "stop_pct": cand.stop_pct, "target_pct": cand.target_pct, "max_hold": cand.max_hold})
        mlflow.log_metrics({f"holdout_{k}": v for k, v in metrics.items() if not (math.isnan(v) or math.isinf(v))})
        mlflow.log_metrics({f"holdout_pooled_{k}": v for k, v in pooled.items() if k in ("profit_factor", "win_rate", "round_trips") and not (math.isnan(v) or math.isinf(v))})
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
