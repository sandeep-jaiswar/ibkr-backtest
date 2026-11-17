"""Command-line interface: `ibbt fetch | backtest | sweep | demo | runs`."""

from __future__ import annotations

import argparse
import re
import asyncio
import itertools
import sys
from datetime import date, timedelta
from typing import Any

import duckdb
import mlflow
import pandas as pd

from ibbt import checks, ib_source, report, tracking
from ibbt.config import Settings
from ibbt.engine import BacktestConfig
from ibbt.portfolio import PortfolioConfig
from ibbt.runner import run_and_record
from ibbt.store import Store
from ibbt.strategies import REGISTRY
from ibbt.synthetic import synthetic_bars
from ibbt.validation import overfit_warning, walk_forward_eval

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
    p.add_argument("--position-fraction", type=float, default=1.0, help="share of cash deployed, (0, 1]")
    p.add_argument("--no-track", action="store_true", help="skip MLflow logging")


def _cfg(args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        initial_cash=args.cash,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        position_fraction=args.position_fraction,
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
    concurrency: int = 4,
) -> dict[str, list]:
    """Fetch symbols with up to `concurrency` requests in flight on one IB connection.

    Writes are idempotent (upsert on the (symbol, ts) key), so re-running never duplicates rows.
    A failing symbol is recorded and skipped. If the connection drops, nothing new is started,
    in-flight symbols are recorded as interrupted, and ConnectionError is raised; re-running
    resumes because covered ranges are skipped.
    """
    summary: dict[str, list] = {"stored": [], "covered": [], "empty": [], "failed": [], "interrupted": []}
    gate = asyncio.Semaphore(concurrency)
    async with ib_source.connect(settings) as ib:

        async def worker(symbol: str) -> None:
            async with gate:
                if not ib.isConnected():
                    summary["interrupted"].append(symbol)
                    return
                try:
                    gaps = ib_source.missing_ranges(store.coverage(symbol), start, end)
                    if not gaps:
                        summary["covered"].append(symbol)
                        return
                    written_total = 0
                    for gap_start, gap_end in gaps:
                        bars = await ib_source.fetch_daily_bars(ib, symbol, gap_start, gap_end, exchange, currency)
                        written = store.upsert_bars(symbol, bars)
                        store.log_fetch(symbol=symbol, start=gap_start, end=gap_end, rows=written, source="IB")
                        written_total += written
                    summary["stored" if written_total else "empty"].append(symbol)
                    print(f"{symbol}: stored {written_total} bars", flush=True)
                except Exception as exc:
                    if not ib.isConnected():
                        summary["interrupted"].append(symbol)
                        return
                    summary["failed"].append((symbol, str(exc)))
                    print(f"{symbol}: FAILED {type(exc).__name__}: {exc}", flush=True)

        await asyncio.gather(*(worker(s) for s in symbols))
    if summary["interrupted"]:
        raise ConnectionError(
            f"IB connection lost; {len(summary['interrupted'])} symbols not finished. Re-run to resume."
        )
    return summary


def cmd_ingest_universe(args: argparse.Namespace) -> int:
    import pandas as pd

    membership = pd.read_csv(args.membership)
    indices = args.indices or sorted(membership["index"].unique())
    subset = membership[membership["index"].isin(indices)]
    # IB writes share classes with a space (BRK.B -> "BRK B").
    # Keep only plain US-style tickers; cash, futures and foreign-listing rows are not stock symbols.
    tickers = {str(t).strip() for t in subset["ticker"]}
    symbols = sorted(t.replace(".", " ") for t in tickers if re.fullmatch(r"[A-Z][A-Z.]{0,5}", t))
    print(f"ingesting {len(symbols)} unique symbols from {', '.join(indices)}", flush=True)
    settings = Settings.from_env()
    with Store(settings.duckdb_path) as store:
        summary = asyncio.run(
            _backfill(
                settings, store, symbols, args.start, args.end, args.exchange, args.currency, args.concurrency
            )
        )
    failed = pd.DataFrame(summary["failed"], columns=["symbol", "error"])
    failed.to_csv(args.failures_out, index=False)
    print(
        f"done: stored={len(summary['stored'])} covered={len(summary['covered'])} "
        f"empty={len(summary['empty'])} failed={len(summary['failed'])} "
        f"(failures -> {args.failures_out})",
        flush=True,
    )
    return 0


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


def cmd_search(args: argparse.Namespace) -> int:
    from ibbt.search import log_search, passes, run_search

    settings = Settings.from_env()
    cfg = BacktestConfig()
    results = run_search(str(settings.duckdb_path), args.split, symbols=args.symbols, cfg=cfg)
    results["pass_is"] = passes(results, "is")
    results["pass_oos"] = passes(results, "oos")
    n = len(args.symbols) if args.symbols else int(
        duckdb.connect(str(settings.duckdb_path), read_only=True).sql("select count(distinct symbol) from bars").fetchone()[0]
    )
    run_id = log_search(results, settings=settings, split=args.split, n_symbols=n, cfg=cfg, experiment_note=args.note)
    print(results.sort_values("is_profit_factor", ascending=False).head(10).to_string(index=False))
    print(
        f"configs passing IS: {int(results.pass_is.sum())}, OOS: {int(results.pass_oos.sum())}, "
        f"both: {int((results.pass_is & results.pass_oos).sum())}; MLflow parent run {run_id}"
    )
    return 0


def cmd_sweep(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    grid = _parse_grid(args.grid)
    keys = list(grid)
    combos = [dict(zip(keys, values, strict=True)) for values in itertools.product(*grid.values())]
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
    warning = overfit_warning(table, keys)
    if warning:
        print(f"warning: {warning}")
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


def cmd_walk_forward(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    grid = _parse_grid(args.grid)
    keys = list(grid)
    combos = [dict(zip(keys, values, strict=True)) for values in itertools.product(*grid.values())]
    with Store(settings.duckdb_path) as store:
        bars = store.load_bars(args.symbol, args.start, args.end)
    if bars.empty:
        raise LookupError(f"no stored bars for {args.symbol}; run `ibbt fetch` first")
    result = walk_forward_eval(bars, args.strategy, combos, _cfg(args), args.folds, args.train_years, args.test_years)
    print(result.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    oos = result["oos_sharpe"].mean() if "oos_sharpe" in result else float("nan")
    print(f"\nmean out-of-sample sharpe: {oos:.4f} across {len(result)} folds")
    return 0


def _portfolio_base(args: argparse.Namespace) -> PortfolioConfig:
    return PortfolioConfig(
        initial_cash=args.cash,
        max_positions=args.slots,
        position_size=args.size,
        min_position_size=args.min_size,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
    )


def _add_portfolio_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cash", type=float, default=10_000.0, help="starting account value")
    p.add_argument("--slots", type=int, default=5, help="max open positions")
    p.add_argument("--size", type=float, default=2_000.0, help="dollars per position")
    p.add_argument("--min-size", type=float, default=1_000.0, help="skip entries funded with less than this")
    p.add_argument("--commission-bps", type=float, default=5.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)


def cmd_portfolio_search(args: argparse.Namespace) -> int:
    from ibbt.portfolio_search import GOAL, LEADERBOARD_COLS, search

    settings = Settings.from_env()
    run_id, table = search(
        settings.duckdb_path,
        settings,
        base=_portfolio_base(args),
        hypothesis=args.hypothesis,
        note=args.note,
        symbols=args.symbols,
        strategies=args.strategies,
    )
    cols = ["candidate", "goal_met", *LEADERBOARD_COLS]
    print(table[cols].head(args.top).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print(
        f"\n{int(table['goal_met'].sum())} of {len(table)} candidates pass goal {GOAL} on train and valid. "
        f"MLflow parent run {run_id}"
    )
    return 0


def cmd_portfolio_holdout(args: argparse.Namespace) -> int:
    from ibbt.portfolio_search import pick_best, run_holdout

    settings = Settings.from_env()
    child = args.run_id or pick_best(settings)
    print(f"holdout check on candidate run {child}")
    metrics = run_holdout(settings.duckdb_path, settings, child_run_id=child, base=_portfolio_base(args))
    _print_metrics(metrics)
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

    p = sub.add_parser("ingest-universe", help="fetch daily bars for every ticker in the membership file")
    p.add_argument("--membership", default="data/universe/membership.csv")
    p.add_argument("--indices", nargs="*", help="subset of SP500 NDX DJIA RUT2000 (default: all)")
    p.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    p.add_argument("--exchange", default="SMART")
    p.add_argument("--currency", default="USD")
    p.add_argument("--failures-out", default="data/universe/fetch_failures.csv")
    p.add_argument("--concurrency", type=int, default=4, help="symbols in flight at once (IB pacing applies)")
    p.set_defaults(func=cmd_ingest_universe)

    p = sub.add_parser("backtest", help="run one backtest on stored bars")
    _add_backtest_args(p)
    p.add_argument("--param", action="append", metavar="KEY=VALUE", help="strategy parameter, repeatable")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("search", help="strategy search across the universe, logged to MLflow")
    p.add_argument("--split", type=date.fromisoformat, default=date(2021, 1, 1), help="out-of-sample start")
    p.add_argument("--symbols", nargs="*", help="default: every symbol in the database")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("portfolio-search", help="portfolio-level search (train/valid), logged to MLflow")
    _add_portfolio_args(p)
    p.add_argument("--hypothesis", required=True, help="what this round tests, stored as an MLflow tag")
    p.add_argument("--note", default="")
    p.add_argument("--symbols", nargs="*", help="default: every symbol with enough history")
    p.add_argument("--strategies", nargs="*", choices=sorted(REGISTRY), help="default: all with a grid")
    p.add_argument("--top", type=int, default=15, help="rows to print")
    p.set_defaults(func=cmd_portfolio_search)

    p = sub.add_parser("portfolio-holdout", help="one-time holdout check (2023 onward) on a search candidate")
    _add_portfolio_args(p)
    p.add_argument("--run-id", help="MLflow child run of a search candidate; default: best passing candidate")
    p.set_defaults(func=cmd_portfolio_holdout)

    p = sub.add_parser("sweep", help="grid-search strategy parameters; each run is an MLflow child")
    _add_backtest_args(p)
    p.add_argument("--grid", action="append", metavar="KEY=V1,V2", help="repeatable")
    p.add_argument("--top", type=int, default=10, help="rows to print")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("demo", help="offline run on synthetic data (no IB needed)")
    p.add_argument("--no-track", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("walk-forward", help="rolling train/test selection with out-of-sample results")
    _add_backtest_args(p)
    p.add_argument("--grid", action="append", metavar="KEY=V1,V2", help="repeatable")
    p.add_argument("--folds", type=int, default=3)
    p.add_argument("--train-years", type=int, default=3)
    p.add_argument("--test-years", type=int, default=1)
    p.set_defaults(func=cmd_walk_forward)

    checks.register(sub)
    report.register(sub)

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
