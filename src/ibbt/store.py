"""DuckDB persistence: daily bars, backtest run registry, trades and equity curves."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol VARCHAR NOT NULL,
    ts DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id VARCHAR PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    strategy VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    start_date DATE,
    end_date DATE,
    params VARCHAR,
    metrics VARCHAR,
    mlflow_run_id VARCHAR
);
CREATE TABLE IF NOT EXISTS trades (
    run_id VARCHAR NOT NULL,
    entry_date DATE,
    entry_price DOUBLE,
    exit_date DATE,
    exit_price DOUBLE,
    pnl_pct DOUBLE,
    is_open BOOLEAN
);
CREATE TABLE IF NOT EXISTS equity_curves (
    run_id VARCHAR NOT NULL,
    ts DATE NOT NULL,
    equity DOUBLE NOT NULL,
    PRIMARY KEY (run_id, ts)
);
"""


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Replace NaN with None so the JSON stored in DuckDB is valid."""
    return {
        k: (None if isinstance(v, float) and math.isnan(v) else v)
        for k, v in values.items()
    }


class Store:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        for statement in SCHEMA.split(";"):
            if statement.strip():
                self.con.execute(statement)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- bars -------------------------------------------------------------

    def coverage(self, symbol: str) -> tuple[date, date] | None:
        """Return (first, last) stored bar date for a symbol, or None if empty."""
        rows = self.con.execute(
            "SELECT min(ts), max(ts) FROM bars WHERE symbol = ?", [symbol]
        ).fetchall()
        if not rows or rows[0][0] is None:
            return None
        return rows[0][0], rows[0][1]

    def upsert_bars(self, symbol: str, bars: pd.DataFrame) -> int:
        """Insert or replace daily bars. `bars` needs a `ts` column plus BAR_COLUMNS."""
        if bars.empty:
            return 0
        frame = pd.DataFrame(
            {
                "symbol": [symbol] * len(bars),
                "ts": pd.to_datetime(bars["ts"]).dt.date.to_numpy(),
                **{c: bars[c].astype(float).to_numpy() for c in BAR_COLUMNS},
            }
        )
        self.con.register("incoming_bars", frame)
        try:
            self.con.execute(
                "INSERT OR REPLACE INTO bars "
                "SELECT symbol, ts, open, high, low, close, volume FROM incoming_bars"
            )
        finally:
            self.con.unregister("incoming_bars")
        return len(frame)

    def load_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Return bars indexed by a DatetimeIndex named `ts`."""
        df = self.con.execute(
            "SELECT ts, open, high, low, close, volume FROM bars "
            "WHERE symbol = ? AND ts BETWEEN ? AND ? ORDER BY ts",
            [symbol, start, end],
        ).df()
        df["ts"] = pd.to_datetime(df["ts"])
        return df.set_index("ts")

    # ---- backtest runs ----------------------------------------------------

    def save_run(
        self,
        *,
        run_id: str,
        strategy: str,
        symbol: str,
        start: date,
        end: date,
        params: dict[str, Any],
        metrics: dict[str, Any],
        mlflow_run_id: str | None,
    ) -> None:
        self.con.execute(
            "INSERT INTO backtest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                datetime.now(),
                strategy,
                symbol,
                start,
                end,
                json.dumps(params, default=str),
                json.dumps(_clean(metrics), default=str),
                mlflow_run_id,
            ],
        )

    def save_trades(self, run_id: str, trades: pd.DataFrame) -> None:
        if trades.empty:
            return
        frame = pd.DataFrame(
            {
                "run_id": [run_id] * len(trades),
                "entry_date": pd.to_datetime(trades["entry_date"]).dt.date.to_numpy(),
                "entry_price": trades["entry_price"].astype(float).to_numpy(),
                "exit_date": pd.to_datetime(trades["exit_date"]).dt.date.to_numpy(),
                "exit_price": trades["exit_price"].astype(float).to_numpy(),
                "pnl_pct": trades["pnl_pct"].astype(float).to_numpy(),
                "is_open": trades["open"].astype(bool).to_numpy(),
            }
        )
        self.con.register("incoming_trades", frame)
        try:
            self.con.execute("INSERT INTO trades SELECT * FROM incoming_trades")
        finally:
            self.con.unregister("incoming_trades")

    def save_equity(self, run_id: str, equity: pd.Series) -> None:
        frame = pd.DataFrame(
            {
                "run_id": [run_id] * len(equity),
                "ts": pd.to_datetime(equity.index).date,
                "equity": equity.to_numpy(float),
            }
        )
        self.con.register("incoming_equity", frame)
        try:
            self.con.execute("INSERT INTO equity_curves SELECT run_id, ts, equity FROM incoming_equity")
        finally:
            self.con.unregister("incoming_equity")

    def list_runs(self, limit: int = 20) -> pd.DataFrame:
        return self.con.execute(
            "SELECT run_id, created_at, strategy, symbol, start_date, end_date, params, metrics "
            "FROM backtest_runs ORDER BY created_at DESC LIMIT ?",
            [limit],
        ).df()
