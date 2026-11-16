"""Self-contained HTML tear sheet for one stored backtest run.

Charts are inline SVG generated here, so the file opens offline with no JS or plotting dependency.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ibbt.config import Settings
from ibbt.store import Store

PCT_METRICS = {
    "total_return",
    "cagr",
    "ann_volatility",
    "max_drawdown",
    "time_in_market",
    "win_rate",
    "avg_trade_pnl_pct",
}

CHART_W, CHART_H = 820, 260
PAD_L, PAD_R, PAD_T, PAD_B = 70, 16, 28, 36


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


def _line_chart(
    dates: list[date],
    values: list[float],
    *,
    title: str,
    color: str,
    fill: bool,
    y_format: str,
) -> str:
    """Return an inline SVG line chart. `fill` shades the area between the line and the top baseline."""
    if len(values) < 2:
        return f'<p class="note">Not enough points to draw {html.escape(title)}.</p>'

    lo, hi = min(values), max(values)
    if math.isclose(lo, hi):
        lo, hi = lo - 1.0, hi + 1.0
    plot_w = CHART_W - PAD_L - PAD_R
    plot_h = CHART_H - PAD_T - PAD_B
    n = len(values)

    def x(i: int) -> float:
        return PAD_L + plot_w * i / (n - 1)

    def y(v: float) -> float:
        return PAD_T + plot_h * (1 - (v - lo) / (hi - lo))

    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    parts = [
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" width="100%" role="img" '
        f'aria-label="{html.escape(title)}" xmlns="http://www.w3.org/2000/svg">',
        f'<text x="{PAD_L}" y="18" class="ctitle">{html.escape(title)}</text>',
        f'<rect x="{PAD_L}" y="{PAD_T}" width="{plot_w}" height="{plot_h}" class="frame"/>',
    ]
    for frac in (0.0, 0.5, 1.0):
        v = hi - (hi - lo) * frac
        yy = PAD_T + plot_h * frac
        parts.append(f'<line x1="{PAD_L}" x2="{PAD_L + plot_w}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>')
        label = html.escape(_axis_label(v, y_format))
        parts.append(f'<text x="{PAD_L - 6}" y="{yy + 4:.1f}" class="tick" text-anchor="end">{label}</text>')
    parts.append(f'<text x="{PAD_L}" y="{CHART_H - 10}" class="tick">{html.escape(dates[0].isoformat())}</text>')
    parts.append(
        f'<text x="{PAD_L + plot_w}" y="{CHART_H - 10}" class="tick" text-anchor="end">'
        f"{html.escape(dates[-1].isoformat())}</text>"
    )
    if fill:
        base = y(min(hi, max(lo, 0.0)))  # zero line when it lies inside the range, else the nearest edge
        area = f"{PAD_L},{base:.1f} {points} {PAD_L + plot_w},{base:.1f}"
        parts.append(f'<polygon points="{area}" fill="{color}" fill-opacity="0.15"/>')
    parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _axis_label(value: float, y_format: str) -> str:
    return f"{value:.1%}" if y_format == "pct" else f"{value:,.0f}"


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
            f'<td class="num">{html.escape(f"{float(row.pnl_pct):.2%}")}</td>'
            f"<td>{status}</td>"
            "</tr>"
        )
    head = "<tr><th>entry</th><th>entry px</th><th>exit</th><th>exit px</th><th>pnl</th><th>status</th></tr>"
    return f'<table class="trades">\n<thead>{head}</thead>\n<tbody>\n' + "\n".join(body) + "\n</tbody>\n</table>"


_CSS = """
body { font: 14px/1.45 system-ui, sans-serif; color: #1d2330; margin: 24px; max-width: 900px; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; border-bottom: 1px solid #d8dde6; padding-bottom: 4px; }
.sub { color: #5b6573; margin-bottom: 8px; }
table { border-collapse: collapse; }
table.kv th { text-align: left; font-weight: 500; padding: 3px 18px 3px 0; color: #5b6573; }
table.kv td { padding: 3px 0; font-variant-numeric: tabular-nums; }
table.trades { width: 100%; font-variant-numeric: tabular-nums; }
table.trades th, table.trades td { padding: 4px 10px 4px 0; text-align: left; border-bottom: 1px solid #eef1f5; }
table.trades td.num { text-align: right; }
svg { display: block; margin: 4px 0; }
svg .ctitle { font-size: 13px; font-weight: 600; fill: #1d2330; }
svg .tick { font-size: 11px; fill: #5b6573; }
svg .grid { stroke: #e3e7ee; stroke-width: 1; }
svg .frame { fill: none; stroke: #d8dde6; }
.note { color: #5b6573; font-style: italic; }
"""


def render_tear_sheet(store: Store, run_id: str, out_path: Path | str) -> Path:
    """Write a single HTML file summarising one stored run and return its path."""
    run_rows = store.con.execute(
        "SELECT strategy, symbol, start_date, end_date, params, metrics, created_at "
        "FROM backtest_runs WHERE run_id = ?",
        [run_id],
    ).fetchall()
    if not run_rows:
        raise LookupError(f"no backtest run with id {run_id!r}")
    strategy, symbol, start, end, params_json, metrics_json, created_at = run_rows[0]
    params = json.loads(params_json) if params_json else {}
    metrics = json.loads(metrics_json) if metrics_json else {}

    eq_rows = store.con.execute(
        "SELECT ts, equity FROM equity_curves WHERE run_id = ? ORDER BY ts", [run_id]
    ).fetchall()
    trades = store.con.execute(
        "SELECT entry_date, entry_price, exit_date, exit_price, pnl_pct, is_open "
        "FROM trades WHERE run_id = ? ORDER BY entry_date",
        [run_id],
    ).df()

    dates = [r[0] for r in eq_rows]
    equity = [float(r[1]) for r in eq_rows]
    drawdown = []
    peak = -math.inf
    for value in equity:
        peak = max(peak, value)
        drawdown.append(value / peak - 1 if peak > 0 else 0.0)

    equity_svg = (
        _line_chart(dates, equity, title="Equity", color="#2456a6", fill=False, y_format="num") if dates else ""
    )
    dd_svg = _line_chart(dates, drawdown, title="Drawdown", color="#b03a2e", fill=True, y_format="pct") if dates else ""

    title = f"{strategy} on {symbol}"
    body = f"""<h1>{html.escape(title)}</h1>
<div class="sub">run {html.escape(run_id)} &middot; {html.escape(str(start))} to {html.escape(str(end))}
&middot; created {html.escape(str(created_at))}</div>

<h2>Metrics</h2>
{_metrics_table(metrics)}

<h2>Parameters</h2>
{_params_table(params)}

<h2>Equity curve</h2>
{equity_svg or '<p class="note">No equity data stored for this run.</p>'}

<h2>Drawdown</h2>
{dd_svg or '<p class="note">No equity data stored for this run.</p>'}

<h2>Trades ({len(trades)})</h2>
{_trades_table(trades)}
"""
    document = (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(title)} - {html.escape(run_id)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n{body}</body>\n</html>\n"
    )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
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
    p = sub.add_parser("report", help="write a self-contained HTML tear sheet for a stored run")
    p.add_argument("run_id")
    p.add_argument("--out", default=None, help="output file (default reports/<run_id>.html)")
    p.set_defaults(func=cmd_report)
