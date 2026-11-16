"""Single entry point that runs a backtest, logs it to MLflow and persists it to DuckDB."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from ibbt import tracking
from ibbt.config import Settings
from ibbt.engine import BacktestConfig, BacktestResult, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.store import Store
from ibbt.strategies import make_strategy
from ibbt.validation import benchmark_metrics


@dataclass
class BacktestOutput:
    run_id: str
    mlflow_run_id: str | None
    metrics: dict[str, float]
    result: BacktestResult


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
    params = {**strategy.params(), **asdict(cfg)}

    run_id = uuid.uuid4().hex[:12]
    mlflow_run_id = None
    if track:
        tracking.configure(settings)
        run_name = f"{strategy_name}-{symbol}-{run_id}"
        mlflow_run_id = tracking.log_backtest(
            run_name=run_name,
            symbol=symbol,
            strategy=strategy_name,
            start=start,
            end=end,
            params=params,
            metrics=metrics,
            result=result,
        )

    store.save_run(
        run_id=run_id,
        strategy=strategy_name,
        symbol=symbol,
        start=start,
        end=end,
        params=params,
        metrics=metrics,
        mlflow_run_id=mlflow_run_id,
    )
    store.save_trades(run_id, result.trades)
    store.save_equity(run_id, result.equity)
    return BacktestOutput(run_id=run_id, mlflow_run_id=mlflow_run_id, metrics=metrics, result=result)
