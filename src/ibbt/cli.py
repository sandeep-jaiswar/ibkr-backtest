"""Command-line interface: `ibbt fetch | backtest | sweep | demo | runs`."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import sys
from datetime import date, timedelta
from typing import Any

import mlflow
import pandas as pd

from ibbt import ib_source, tracking
from ibbt.config import Settings
from ibbt.engine import BacktestConfig
from ibbt.runner import run_and_record
from ibbt.store import Store
from ibbt.strategies import REGISTRY
from ibbt.synthetic import synthetic_bars

DEMO_SYMBOL = "SYNTH"


# ---- argument helpers -------------------------------------------------------


def _parse_value(text: str) -> Any:
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            pass
    return text


def _parse_params(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        out[key.strip()] = _parse_value(value.strip())
    return out


def _parse_grid(items: list[str] | None) -> dict[str, list[Any]]:
    grid: dict[str, list[Any]] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"expected KEY=V1,V2,..., got {item!r}")
        key, values = item.split("=", 1)
        grid[key.strip()] = [_parse_value(v.strip()) for v in values.split(",") if v.strip()]
    if not grid:
        raise ValueError("sweep needs at least one --grid KEY=V1,V2 argument")
    return grid


def _add_backtest_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("symbol")
    p.add_argument("--strategy", default="sma_crossover", choices=sorted(REGISTRY))
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--cash", type=float, default=100_000.0, help="initial cash")
    p.add_argument("--commission-bps", type=float, default=5.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--no-track", action="store_true", help="skip MLflow logging")


def _cfg(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=args.cash,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
    )


# ---- commands ---------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    with Store(settings.duckdb_path) as store:
        asyncio.run(_backfill(settings, store, args.symbols, args.start, args.end, args.exchange, args.currency))
    return 0


async def _backfill(
    settings: Settings,
    store: Store,
    symbols: list[str],
    start: date,
    end: date,
    exchange: str,
    currency: str,
) -> None:
    async with ib_source.connect(settings) as ib:
        for symbol in symbols:
            gaps = ib_source.missing_ranges(store.coverage(symbol), start, end)
            if not gaps:
                print(f"{symbol}: already covered {start}..{end}")
                continue
            for gap_start, gap_end in gaps:
                bars = await ib_source.fetch_daily_bars(ib, symbol, gap_start, gap_end, exchange, currency)
                written = store.upsert_bars(symbol, bars)
                print(f"{symbol}: stored {written} bars for {gap_start}..{gap_end}")


def _print_metrics(metrics: dict[str, float]) -> None:
    pct = {"total_return", "cagr", "ann_volatility", "max_drawdown", "time_in_market", "win_rate", "avg_trade_pnl_pct"}
    for key, value in metrics.items():
        if key in pct:
            shown = f"{value:.2%}"
        elif key == "final_equity":
            shown = f"{value:,.2f}"
        elif key == "round_trips":
            shown = f"{int(value)}"
        else:
            shown = f"{value:,.4f}"
        print(f"  {key:<18} {shown}")


def cmd_backtest(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    with Store(settings.duckdb_path) as store:
        out = run_and_record(
            store=store,
            settings=settings,
            symbol=args.symbol,
            strategy_name=args.strategy,
            strategy_params=_parse_params(args.param),
            start=args.start,
            end=args.end,
            cfg=_cfg(args),
            track=not args.no_track,
        )
    print(f"run {out.run_id}  ({args.strategy} on {args.symbol}, {args.start}..{args.end})")
    _print_metrics(out.metrics)
    if out.mlflow_run_id:
        print(f"mlflow run {out.mlflow_run_id}")
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    grid = _parse_grid(args.grid)
    keys = list(grid)
    combos = [dict(zip(keys, values)) for values in itertools.product(*grid.values())]
    rows: list[dict[str, Any]] = []

    with Store(settings.duckdb_path) as store:
        tracking.configure(settings)
        with mlflow.start_run(run_name=f"sweep-{args.strategy}-{args.symbol}"):
            mlflow.set_tag("sweep_grid", str(grid))
            for combo in combos:
                try:
                    out = run_and_record(
                        store=store,
                        settings=settings,
                        symbol=args.symbol,
                        strategy_name=args.strategy,
                        strategy_params=combo,
                        start=args.start,
                        end=args.end,
                        cfg=_cfg(args),
                        track=not args.no_track,
                    )
                except ValueError as exc:  # e.g. sma fast >= slow
                    print(f"skipping {combo}: {exc}")
                    continue
                rows.append({**combo, **out.metrics, "run_id": out.run_id})

    if not rows:
        print("no valid parameter combinations ran")
        return 1
    table = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    cols = [*keys, "total_return", "cagr", "sharpe", "max_drawdown", "round_trips", "run_id"]
    print(table[cols].head(args.top).to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\n{len(rows)} runs. Sorted by Sharpe; open the MLflow UI to compare them.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Offline end-to-end run on synthetic data. Needs no IB connection."""
    settings = Settings.from_env()
    with Store(settings.duckdb_path) as store:
        bars = synthetic_bars("2015-01-01", "2025-12-31")
        store.upsert_bars(DEMO_SYMBOL, bars)
        out = run_and_record(
            store=store,
            settings=settings,
            symbol=DEMO_SYMBOL,
            strategy_name="sma_crossover",
            strategy_params={"fast": 20, "slow": 100},
            start=date(2015, 1, 1),
            end=date(2025, 12, 31),
            cfg=BacktestConfig(),
            track=not args.no_track,
        )
    print(f"demo run {out.run_id} on synthetic {DEMO_SYMBOL} data")
    _print_metrics(out.metrics)
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    with Store(settings.duckdb_path) as store:
        runs = store.list_runs(args.limit)
    if runs.empty:
        print("no backtest runs stored yet")
    else:
        print(runs.to_string(index=False))
    return 0


# ---- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ibbt", description="Backtest strategies on IBKR data.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="download daily bars from IB into DuckDB (read-only)")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    p.add_argument("--exchange", default="SMART")
    p.add_argument("--currency", default="USD")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("backtest", help="run one backtest on stored bars")
    _add_backtest_args(p)
    p.add_argument("--param", action="append", metavar="KEY=VALUE", help="strategy parameter, repeatable")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("sweep", help="grid-search strategy parameters; each run is an MLflow child")
    _add_backtest_args(p)
    p.add_argument("--grid", action="append", metavar="KEY=V1,V2", help="repeatable")
    p.add_argument("--top", type=int, default=10, help="rows to print")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("demo", help="offline run on synthetic data (no IB needed)")
    p.add_argument("--no-track", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("runs", help="list stored backtest runs")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_runs)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, ValueError, ConnectionError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
