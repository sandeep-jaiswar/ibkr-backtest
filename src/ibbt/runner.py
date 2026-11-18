"""Run a backtest, then record it: compute is pure (safe in a worker), recording is done by the parent.

`compute_run` needs only bars, so sweeps can compute many parameter sets in parallel and record them
afterwards in one process, which keeps DuckDB and MLflow single-writer.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date
from functools import partial
from typing import Any

import pandas as pd

from ibbt import tracking
from ibbt.config import Settings
from ibbt.engine import BacktestConfig, BacktestResult, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.parallel import pmap
from ibbt.store import Store
from ibbt.strategies import make_strategy
from ibbt.validation import benchmark_metrics


@dataclass
class ComputedRun:
    strategy_name: str
    params: dict[str, Any]  # strategy params merged with the cost config, as stored
    metrics: dict[str, float]
    result: BacktestResult


@dataclass
class BacktestOutput:
    run_id: str
    mlflow_run_id: str | None
    metrics: dict[str, float]
    result: BacktestResult


def compute_run(
    bars: pd.DataFrame,
    strategy_name: str,
    strategy_params: dict[str, Any],
    cfg: BacktestConfig,
) -> ComputedRun:
    """Backtest and score one parameter set. Pure: no I/O, so it can run in a worker process."""
    strategy = make_strategy(strategy_name, strategy_params)
    result = run_backtest(bars, strategy.signal(bars), cfg)
    metrics = compute_metrics(result.equity, result.trades, result.position)
    # Buy-and-hold under the same costs and sizing, so runs can be compared with simply holding.
    benchmark = benchmark_metrics(bars, cfg)
    metrics = {
        **metrics,
        "benchmark_total_return": benchmark["total_return"],
        "benchmark_cagr": benchmark["cagr"],
    }
    return ComputedRun(
        strategy_name=strategy_name,
        params={**strategy.params(), **asdict(cfg)},
        metrics=metrics,
        result=result,
    )


# Below this many parameter sets, forking costs more than it saves.
PARALLEL_SWEEP_MIN = 8


def _compute_or_reason(
    params: dict[str, Any],
    *,
    bars: pd.DataFrame,
    strategy_name: str,
    cfg: BacktestConfig,
) -> ComputedRun | str:
    """A computed run, or the ValueError text when the parameters are rejected (e.g. sma fast >= slow)."""
    try:
        return compute_run(bars, strategy_name, params, cfg)
    except ValueError as exc:
        return str(exc)


def compute_grid(
    bars: pd.DataFrame,
    strategy_name: str,
    combos: list[dict[str, Any]],
    cfg: BacktestConfig,
    workers: int | None = None,
) -> list[ComputedRun | str]:
    """Compute every parameter set in parallel. Each entry is a ComputedRun, or the reason it was rejected.

    Results are in the order of `combos`. Recording is left to the caller, in one process.
    """
    task = partial(_compute_or_reason, bars=bars, strategy_name=strategy_name, cfg=cfg)
    return pmap(task, combos, workers, min_items=PARALLEL_SWEEP_MIN)


def record_run(
    *,
    store: Store,
    settings: Settings,
    symbol: str,
    start: date,
    end: date,
    computed: ComputedRun,
    track: bool = True,
) -> BacktestOutput:
    """Persist a computed run to DuckDB and, optionally, MLflow. Parent process only."""
    run_id = uuid.uuid4().hex[:12]
    mlflow_run_id = None
    if track:
        tracking.configure(settings)
        mlflow_run_id = tracking.log_backtest(
            run_name=f"{computed.strategy_name}-{symbol}-{run_id}",
            symbol=symbol,
            strategy=computed.strategy_name,
            start=start,
            end=end,
            params=computed.params,
            metrics=computed.metrics,
            result=computed.result,
        )
    store.save_run(
        run_id=run_id,
        strategy=computed.strategy_name,
        symbol=symbol,
        start=start,
        end=end,
        params=computed.params,
        metrics=computed.metrics,
        mlflow_run_id=mlflow_run_id,
    )
    store.save_trades(run_id, computed.result.trades)
    store.save_equity(run_id, computed.result.equity)
    return BacktestOutput(
        run_id=run_id,
        mlflow_run_id=mlflow_run_id,
        metrics=computed.metrics,
        result=computed.result,
    )


def run_and_record(
    *,
    store: Store,
    settings: Settings,
    symbol: str,
    strategy_name: str,
    strategy_params: dict[str, Any],
    start: date,
    end: date,
    cfg: BacktestConfig,
    track: bool = True,
) -> BacktestOutput:
    bars = store.load_bars(symbol, start, end)
    if bars.empty:
        raise LookupError(f"no stored bars for {symbol} between {start} and {end}; run `ibbt fetch` first")
    computed = compute_run(bars, strategy_name, strategy_params, cfg)
    return record_run(
        store=store,
        settings=settings,
        symbol=symbol,
        start=start,
        end=end,
        computed=computed,
        track=track,
    )
