"""Strategy search across the stored universe, with a fixed in-sample / out-of-sample split.

Each configuration's signal is computed on the full history (so indicator warm-up uses real data),
then backtested on two slices: in-sample (selection) and out-of-sample (one-time check).
Trades are pooled across symbols per configuration, so a result has to hold across the universe,
not just in one name. Costs come from BacktestConfig (commission and slippage per side).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from ibbt.engine import BacktestConfig, run_backtest
from ibbt.strategies import make_strategy

DEFAULT_GRID: dict[str, dict[str, list[Any]]] = {
    "buy_and_hold": {},
    "sma_crossover": {"fast": [10, 20, 50], "slow": [100, 200]},
    "donchian_breakout": {"lookback": [20, 55, 100], "exit_lookback": [10, 20]},
    "rsi_pullback": {"entry_rsi": [5, 10, 15], "exit_rsi": [60, 70, 80], "trend": [50, 200]},
}


def expand_grid(grid: dict[str, dict[str, list[Any]]] = DEFAULT_GRID) -> list[tuple[str, dict[str, Any]]]:
    """Every valid parameter combination; combinations a strategy rejects (e.g. fast >= slow) are dropped."""
    configs: list[tuple[str, dict[str, Any]]] = []
    for name, space in grid.items():
        keys = list(space)
        for values in itertools.product(*(space[k] for k in keys)):
            params = dict(zip(keys, values))
            try:
                make_strategy(name, params)
            except ValueError:
                continue
            configs.append((name, params))
        if not keys:
            configs.append((name, {}))
    return configs


@dataclass
class Pool:
    pnl: list[float]

    def stats(self) -> dict[str, float]:
        p = np.asarray(self.pnl, dtype=float)
        if p.size == 0:
            return {"n": 0, "win_rate": math.nan, "profit_factor": math.nan, "avg_pnl_pct": math.nan}
        wins, losses = p[p > 0].sum(), -p[p <= 0].sum()
        pf = wins / losses if losses > 0 else math.inf
        return {
            "n": int(p.size),
            "win_rate": float((p > 0).mean()),
            "profit_factor": float(pf),
            "avg_pnl_pct": float(p.mean()),
        }


def load_bars(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.DataFrame:
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM bars WHERE symbol = ? ORDER BY ts", [symbol]
    ).df()
    df["ts"] = pd.to_datetime(df["ts"])
    return df.set_index("ts")


def run_search(
    db_path: str,
    split: date,
    symbols: list[str] | None = None,
    cfg: BacktestConfig | None = None,
    grid: dict[str, dict[str, list[Any]]] = DEFAULT_GRID,
    progress_every: int = 200,
) -> pd.DataFrame:
    cfg = cfg or BacktestConfig()
    split_ts = pd.Timestamp(split)
    con = duckdb.connect(db_path, read_only=True)
    if symbols is None:
        symbols = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()]

    configs = expand_grid(grid)
    pools = {(i, "is"): Pool([]) for i in range(len(configs))}
    pools.update({(i, "oos"): Pool([]) for i in range(len(configs))})

    for n, symbol in enumerate(symbols, 1):
        bars = load_bars(con, symbol)
        if len(bars) < 250:  # too short to say anything; skip rather than pad with noise
            continue
        for i, (name, params) in enumerate(configs):
            signal = make_strategy(name, params).signal(bars)
            for period, mask in (("is", bars.index < split_ts), ("oos", bars.index >= split_ts)):
                part = bars[mask]
                if len(part) < 2:
                    continue
                result = run_backtest(part, signal.reindex(part.index), cfg)
                closed = result.trades.loc[~result.trades["open"].astype(bool)]
                pools[(i, period)].pnl.extend(closed["pnl_pct"].astype(float).tolist())
        if n % progress_every == 0:
            print(f"{n}/{len(symbols)} symbols", flush=True)
    con.close()

    rows = []
    for i, (name, params) in enumerate(configs):
        is_s, oos_s = pools[(i, "is")].stats(), pools[(i, "oos")].stats()
        rows.append(
            {
                "strategy": name,
                "params": repr(params),
                "is_n": is_s["n"],
                "is_win_rate": is_s["win_rate"],
                "is_profit_factor": is_s["profit_factor"],
                "oos_n": oos_s["n"],
                "oos_win_rate": oos_s["win_rate"],
                "oos_profit_factor": oos_s["profit_factor"],
                "oos_avg_pnl_pct": oos_s["avg_pnl_pct"],
            }
        )
    return pd.DataFrame(rows)


def passes(df: pd.DataFrame, prefix: str, min_pf: float = 2.0, min_win: float = 0.5, min_n: int = 200) -> pd.Series:
    return (
        (df[f"{prefix}_profit_factor"] >= min_pf)
        & (df[f"{prefix}_win_rate"] >= min_win)
        & (df[f"{prefix}_n"] >= min_n)
    )


def log_search(
    results: pd.DataFrame,
    *,
    settings: Any,
    split: date,
    n_symbols: int,
    cfg: BacktestConfig,
    experiment_note: str = "",
) -> str:
    """Log a strategy search to MLflow: one parent run, one child run per configuration."""
    import tempfile
    from pathlib import Path

    import mlflow

    from ibbt import tracking

    tracking.configure(settings)
    with mlflow.start_run(run_name=f"search-{split}") as parent:
        mlflow.set_tags({"project": "ibkr-backtest", "kind": "strategy_search", "note": experiment_note})
        mlflow.log_params(
            {"split": str(split), "symbols": n_symbols, **{f"cost_{k}": v for k, v in cfg.__dict__.items()}}
        )
        mlflow.log_metrics(
            {
                "configs_passing_is": float(passes(results, "is").sum()),
                "configs_passing_oos": float(passes(results, "oos").sum()),
                "configs_passing_both": float((passes(results, "is") & passes(results, "oos")).sum()),
            }
        )
        for _, row in results.iterrows():
            metrics = {
                k: float(row[k])
                for k in row.index
                if k.startswith(("is_", "oos_")) and pd.notna(row[k]) and not math.isinf(row[k])
            }
            with mlflow.start_run(run_name=f"{row['strategy']}{row['params']}", nested=True):
                mlflow.set_tags({"strategy": row["strategy"], "params": row["params"]})
                mlflow.log_params({"strategy": row["strategy"], "params": row["params"]})
                mlflow.log_metrics(metrics)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "search_results.csv"
            results.to_csv(path, index=False)
            mlflow.log_artifact(str(path), artifact_path="search")
        return parent.info.run_id
