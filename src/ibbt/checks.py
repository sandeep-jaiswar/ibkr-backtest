"""Verification of stored daily bars: coverage, gaps and bad rows. Works offline."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Any

import pandas as pd

from ibbt.config import Settings
from ibbt.store import Store

DEFAULT_START = date(2015, 1, 1)  # same default as `backtest`
BAD_BAR_KEYS = ("high_below_low", "close_outside_high_low", "non_positive_prices")


def check_symbol(store: Store, symbol: str, start: date, end: date) -> dict[str, Any]:
    """Summarise stored bars for `symbol` between start and end (inclusive).

    `missing_business_days` counts weekdays with no bar. It ignores exchange
    holidays, so a holiday shows up as missing. A row can count under more than
    one bad-bar key.
    """
    if start > end:
        raise ValueError(f"start {start} is after end {end}")

    con = store.con
    where = "symbol = ? AND ts BETWEEN ? AND ?"
    params = [symbol, start, end]

    stored = [r[0] for r in con.execute(f"SELECT ts FROM bars WHERE {where} ORDER BY ts", params).fetchall()]
    present = set(stored)
    expected = [d.date() for d in pd.bdate_range(start, end)]

    def count(condition: str) -> int:
        row = con.execute(f"SELECT count(*) FROM bars WHERE {where} AND ({condition})", params).fetchall()
        return int(row[0][0])

    return {
        "symbol": symbol,
        "start": start,
        "end": end,
        "bars": len(stored),
        "first": stored[0] if stored else None,
        "last": stored[-1] if stored else None,
        "missing_business_days": sum(1 for d in expected if d not in present),
        "high_below_low": count("high < low"),
        "close_outside_high_low": count("close < low OR close > high"),
        "non_positive_prices": count("open <= 0 OR high <= 0 OR low <= 0 OR close <= 0"),
    }


def _format(report: dict[str, Any]) -> str:
    first = report["first"] or "-"
    last = report["last"] or "-"
    return (
        f"{report['symbol']} {report['start']}..{report['end']} bars={report['bars']} "
        f"first={first} last={last} missing_business_days={report['missing_business_days']} "
        f"high_below_low={report['high_below_low']} "
        f"close_outside_high_low={report['close_outside_high_low']} "
        f"non_positive_prices={report['non_positive_prices']}"
    )


def _run(args: argparse.Namespace) -> int:
    end = args.end or date.today()
    if args.start > end:
        print(f"--start {args.start} is after --end {end}", file=sys.stderr)
        return 2
    path = Settings.from_env().duckdb_path
    if not path.exists():
        print(f"no database at {path}", file=sys.stderr)
        return 2

    problems = 0
    with Store(path) as store:
        for symbol in args.symbols:
            report = check_symbol(store, symbol, args.start, end)
            print(_format(report))
            if report["bars"] == 0 or any(report[k] for k in BAD_BAR_KEYS):
                problems += 1
    return 1 if problems else 0


def register(sub: argparse._SubParsersAction) -> None:
    """Add the `check` subcommand. Exit 1 if a symbol has bad bars or no bars."""
    p = sub.add_parser("check", help="verify stored bars: gaps and bad rows (no IB needed)")
    p.add_argument("symbols", nargs="+", metavar="SYMBOL")
    p.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    p.add_argument("--end", type=date.fromisoformat, default=None, help="default: today")
    p.set_defaults(func=_run)
