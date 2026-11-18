"""HTML tear sheet for one stored backtest run, rendered with quantstats.

One renderer: the stored metrics, parameters and trades are shown first, then the quantstats figures when the
run's returns are valid. Stored metrics stay canonical. quantstats may use different conventions for some
figures (CAGR is counted by periods there), so the page labels its figures as computed from the same equity curve.

Benchmark is always off, so nothing is downloaded. quantstats is imported inside the function, so the CLI
does not load matplotlib or seaborn for other commands.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ibbt.config import Settings
from ibbt.store import Store

MIN_BARS = 3

PCT_METRICS = {
    "total_return",
    "cagr",
    "ann_volatility",
    "max_drawdown",
    "time_in_market",
    "win_rate",
    "avg_trade_pnl_pct",
}

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; color: #1d2633; margin: 0; padding: 16px 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 20px 0 8px; border-bottom: 1px solid #d6dbe3; padding-bottom: 4px; }
.sub { color: #5b6573; font-size: 13px; margin-bottom: 12px; }
.note { color: #5b6573; font-style: italic; }
table.kv, table.trades { border-collapse: collapse; font-size: 13px; }
table.kv th { text-align: left; padding: 3px 14px 3px 0; font-weight: 500; color: #5b6573; }
table.kv td { padding: 3px 0; }
table.trades th, table.trades td { border-bottom: 1px solid #eef1f5; padding: 4px 10px; text-align: left; }
table.trades td.num { text-align: right; font-variant-numeric: tabular-nums; }
"""


@dataclass
class RunData:
    run_id: str
    strategy: str
    symbol: str
    start: Any
    end: Any
    created_at: Any
    params: dict[str, Any]
    metrics: dict[str, Any]
    equity: pd.Series  # indexed by bar timestamp
    trades: pd.DataFrame
    notes: list[str] = field(default_factory=list)


def _load_run(store: Store, run_id: str) -> RunData:
    rows = store.con.execute(
        "SELECT strategy, symbol, start_date, end_date, params, metrics, created_at "
        "FROM backtest_runs WHERE run_id = ?",
        [run_id],
    ).fetchall()
    if not rows:
        raise LookupError(f"no backtest run with id {run_id!r}")
    strategy, symbol, start, end, params_json, metrics_json, created_at = rows[0]
    eq = store.con.execute("SELECT ts, equity FROM equity_curves WHERE run_id = ? ORDER BY ts", [run_id]).fetchall()
    trades = store.con.execute(
        "SELECT entry_date, entry_price, exit_date, exit_price, pnl_pct, is_open "
        "FROM trades WHERE run_id = ? ORDER BY entry_date",
        [run_id],
    ).df()
    index = pd.DatetimeIndex([pd.Timestamp(r[0]) for r in eq])
    if index.tz is not None:
        index = index.tz_localize(None)
    return RunData(
        run_id=run_id,
        strategy=strategy,
        symbol=symbol,
        start=start,
        end=end,
        created_at=created_at,
        params=json.loads(params_json) if params_json else {},
        metrics=json.loads(metrics_json) if metrics_json else {},
        equity=pd.Series([float(r[1]) for r in eq], index=index, dtype=float),
        trades=trades,
    )


def _fmt_metric(key: str, value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if key in PCT_METRICS:
        return f"{float(value):.2%}"
    if key == "final_equity":
        return f"{float(value):,.2f}"
    if key == "round_trips":
        return f"{int(value)}"
    return f"{float(value):,.4f}"


def _fmt_price(value: Any) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{float(value):,.2f}"


def _metrics_table(metrics: dict[str, Any]) -> str:
    rows = "\n".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(_fmt_metric(k, v))}</td></tr>" for k, v in metrics.items()
    )
    return f'<table class="kv">\n{rows}\n</table>'


def _params_table(params: dict[str, Any]) -> str:
    if not params:
        return '<p class="note">No parameters recorded.</p>'
    rows = "\n".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in params.items()
    )
    return f'<table class="kv">\n{rows}\n</table>'


def _trades_table(trades: pd.DataFrame) -> str:
    if trades.empty:
        return '<p class="note">No trades in this run.</p>'
    body = []
    for row in trades.itertuples(index=False):
        status = "open" if row.is_open else "closed"
        body.append(
            "<tr>"
            f"<td>{html.escape(str(row.entry_date))}</td>"
            f'<td class="num">{html.escape(_fmt_price(row.entry_price))}</td>'
            f"<td>{html.escape(str(row.exit_date))}</td>"
            f'<td class="num">{html.escape(_fmt_price(row.exit_price))}</td>'
            f'<td class="num">{html.escape(_fmt_metric("total_return", row.pnl_pct))}</td>'
            f"<td>{status}</td>"
            "</tr>"
        )
    head = "<tr><th>entry</th><th>entry price</th><th>exit</th><th>exit price</th><th>P&amp;L</th><th></th></tr>"
    return f'<table class="trades">\n{head}\n{"".join(body)}\n</table>'


def periods_per_year(index: pd.DatetimeIndex) -> int:
    """Bars per year, observed from the data. About 252 for daily stocks, about 365 for 24/7 markets."""
    years = (index[-1] - index[0]).days / 365.25
    if years <= 0:
        raise ValueError("need more than one calendar day of data")
    return max(1, round((len(index) - 1) / years))


def _returns(equity: pd.Series) -> pd.Series:
    """Per-bar returns for quantstats. Raises ValueError with the reason when there is nothing to analyse."""
    if len(equity) < MIN_BARS:
        raise ValueError(f"only {len(equity)} equity points; quantstats needs at least {MIN_BARS}")
    returns = equity.pct_change().dropna()
    if returns.empty or float(returns.abs().sum()) == 0.0:
        raise ValueError("flat equity, so there are no returns to analyse")
    return returns


def _quantstats_page(run: RunData, returns: pd.Series, title: str) -> str:
    import quantstats as qs  # lazy: heavy imports stay out of the other CLI commands

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "quantstats.html"
        qs.reports.html(
            returns,
            benchmark=None,  # no benchmark means no network download
            rf=0.0,
            title=html.escape(title),
            output=str(raw),
            periods_per_year=periods_per_year(run.equity.index),
            match_dates=False,
        )
        return _strip_remote_fetches(raw.read_text(encoding="utf-8"))


# quantstats links a favicon from a remote host, which a browser would fetch when the page opens.
_REMOTE_ICON = re.compile(r'<link[^>]*rel="shortcut icon"[^>]*>', re.IGNORECASE)


def _strip_remote_fetches(page: str) -> str:
    """Drop the one resource quantstats loads automatically. Plain links (anchors) are left alone."""
    return _REMOTE_ICON.sub("", page)


def _our_sections(run: RunData, title: str, qs_note: str) -> str:
    return f"""<style>{_CSS}</style>
<div class="ibbt-sections" style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;padding:16px 24px;color:#1d2633">
<h1>{html.escape(title)}</h1>
<div class="sub">run {html.escape(run.run_id)} &middot; {html.escape(str(run.start))} to {html.escape(str(run.end))}
&middot; created {html.escape(str(run.created_at))}</div>
<h2>Stored metrics</h2>
<p class="note">These stored values are canonical. The quantstats figures below come from the same equity curve,
but may use different conventions (for example CAGR).</p>
{_metrics_table(run.metrics)}
<h2>Parameters</h2>
{_params_table(run.params)}
<h2>Trades</h2>
{_trades_table(run.trades)}
<p class="note">{html.escape(qs_note)}</p>
</div>
"""


def _inject_after_body(page: str, fragment: str) -> str:
    at = page.find("<body")
    if at == -1:
        return fragment + page
    close = page.find(">", at) + 1
    return page[:close] + fragment + page[close:]


def render_tear_sheet(store: Store, run_id: str, out_path: Path | str) -> Path:
    """Write one HTML tear sheet for a stored run and return its path."""
    run = _load_run(store, run_id)
    title = f"{run.strategy} on {run.symbol} ({run.run_id})"

    try:
        returns = _returns(run.equity)
    except ValueError as exc:
        page = (
            f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{html.escape(title)}</title>\n</head>\n<body>\n"
            + _our_sections(run, title, qs_note=f"quantstats figures skipped: {exc}.")
            + "</body>\n</html>\n"
        )
    else:
        base = _quantstats_page(run, returns, title)
        page = _inject_after_body(base, _our_sections(run, title, qs_note="quantstats figures follow."))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


# ---- CLI wiring -------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    out = Path(args.out) if args.out else Path("reports") / f"{args.run_id}.html"
    with Store(settings.duckdb_path) as store:
        path = render_tear_sheet(store, args.run_id, out)
    print(f"wrote {path}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    """Add the `report` subcommand to an existing argparse subparser group."""
    p = sub.add_parser("report", help="write a self-contained HTML tear sheet (quantstats) for a stored run")
    p.add_argument("run_id")
    p.add_argument("--out", default=None, help="output file (default reports/<run_id>.html)")
    p.set_defaults(func=cmd_report)
