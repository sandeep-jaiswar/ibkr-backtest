"""MLflow tracking for backtest runs.

If a parent run is already active (e.g. during a parameter sweep), the run is logged
as a nested child of it.
"""

from __future__ import annotations

import math
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import mlflow

from ibbt.config import Settings
from ibbt.engine import BacktestResult


def configure(settings: Settings) -> None:
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment)


def log_backtest(
    *,
    run_name: str,
    symbol: str,
    strategy: str,
    start: date,
    end: date,
    params: dict[str, Any],
    metrics: dict[str, float],
    result: BacktestResult,
) -> str:
    nested = mlflow.active_run() is not None
    with mlflow.start_run(run_name=run_name, nested=nested) as run:
        mlflow.set_tags({"symbol": symbol, "strategy": strategy, "project": "ibkr-backtest"})
        mlflow.log_params({**params, "symbol": symbol, "start": str(start), "end": str(end)})
        mlflow.log_metrics({k: v for k, v in metrics.items() if not math.isnan(v)})

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            result.equity.to_frame().to_csv(tmp_dir / "equity.csv")
            result.trades.to_csv(tmp_dir / "trades.csv", index=False)
            mlflow.log_artifacts(str(tmp_dir), artifact_path="backtest")
        return run.info.run_id
