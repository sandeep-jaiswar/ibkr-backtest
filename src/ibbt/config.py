"""Runtime settings, read from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Local disk, not the data drive: SQLite commits are very slow on /media/sandeep/DataDrive3.
LOCAL_MLFLOW_DB = Path.home() / "mlflow" / "mlflow.db"


@dataclass(frozen=True)
class Settings:
    ib_host: str = "127.0.0.1"
    # TWS paper 7497 | TWS live 7496 | IB Gateway paper 4002 | IB Gateway live 4001
    ib_port: int = 7497
    ib_client_id: int = 17
    duckdb_path: Path = Path("data/market.duckdb")
    mlflow_tracking_uri: str = f"sqlite:///{LOCAL_MLFLOW_DB}"
    mlflow_experiment: str = "ibkr-backtests"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            ib_host=os.getenv("IBKR_HOST", "127.0.0.1"),
            ib_port=int(os.getenv("IBKR_PORT", "7497")),
            ib_client_id=int(os.getenv("IBKR_CLIENT_ID", "17")),
            duckdb_path=Path(os.getenv("IBBT_DUCKDB", "data/market.duckdb")),
            mlflow_tracking_uri=os.getenv("MLFLOW_TRACKING_URI", f"sqlite:///{LOCAL_MLFLOW_DB}"),
            mlflow_experiment=os.getenv("IBBT_MLFLOW_EXPERIMENT", "ibkr-backtests"),
        )
