"""Long/flat backtest engine with explicit next-open fills, commissions and slippage.

Timing convention:
  * A signal computed from bar t's close is an order for bar t+1.
  * Orders fill at bar t+1's open, adjusted by slippage against the trader.
  * Commission is charged on notional, on each side.
  * Equity is marked to each bar's close.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADE_COLUMNS = ["entry_date", "entry_price", "exit_date", "exit_price", "pnl_pct", "open"]


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission_bps: float = 5.0  # per side, on notional
    slippage_bps: float = 5.0    # per side, adverse to the trader


@dataclass
class BacktestResult:
    equity: pd.Series      # indexed by bar date
    position: pd.Series    # 1 when holding shares at the bar's close, else 0
    trades: pd.DataFrame   # one row per round trip; `open` marks a position still held at the end


def run_backtest(
    bars: pd.DataFrame,
    signal: pd.Series,
    cfg: BacktestConfig = BacktestConfig(),
) -> BacktestResult:
    if bars.empty:
        raise ValueError("cannot backtest an empty price series")

    index = bars.index
    desired = signal.reindex(index).fillna(0).astype(int).to_numpy()
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    slip = cfg.slippage_bps / 10_000
    comm = cfg.commission_bps / 10_000

    cash = cfg.initial_cash
    shares = 0.0
    cost_basis = 0.0
    entry_date = None
    entry_price = 0.0

    n = len(bars)
    equity = np.empty(n)
    held = np.zeros(n, dtype=int)
    trades: list[dict] = []

    for i in range(n):
        # The order was decided at the previous bar's close and fills at this open.
        order = int(desired[i - 1]) if i > 0 else 0

        if order == 1 and shares == 0.0 and cash > 0.0:
            fill = opens[i] * (1 + slip)
            shares = cash / (fill * (1 + comm))
            cost_basis = cash
            entry_date, entry_price = index[i], fill
            cash = 0.0
        elif order == 0 and shares > 0.0:
            fill = opens[i] * (1 - slip)
            cash = shares * fill * (1 - comm)
            trades.append(
                {
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "exit_date": index[i],
                    "exit_price": fill,
                    "pnl_pct": cash / cost_basis - 1,
                    "open": False,
                }
            )
            shares = 0.0

        equity[i] = cash + shares * closes[i]
        held[i] = int(shares > 0.0)

    if shares > 0.0:
        trades.append(
            {
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": index[-1],
                "exit_price": closes[-1],
                "pnl_pct": shares * closes[-1] / cost_basis - 1,
                "open": True,
            }
        )

    return BacktestResult(
        equity=pd.Series(equity, index=index, name="equity"),
        position=pd.Series(held, index=index, name="position"),
        trades=pd.DataFrame(trades, columns=TRADE_COLUMNS),
    )
