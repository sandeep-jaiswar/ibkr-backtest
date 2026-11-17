"""Performance metrics computed from an equity curve and its trades."""

from __future__ import annotations

import math

import pandas as pd


def compute_metrics(
    equity: pd.Series,
    trades: pd.DataFrame,
    position: pd.Series,
    periods_per_year: int = 252,
) -> dict[str, float]:
    if len(equity) < 2:
        raise ValueError("need at least two bars to compute metrics")

    rets = equity.pct_change().dropna()
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else math.nan

    ret_std = rets.std(ddof=1)
    ann_vol = ret_std * math.sqrt(periods_per_year)
    sharpe = rets.mean() / ret_std * math.sqrt(periods_per_year) if ret_std > 0 else math.nan

    max_drawdown = (equity / equity.cummax() - 1).min()
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 and not math.isnan(cagr) else math.nan

    closed = trades.loc[~trades["open"].astype(bool)] if not trades.empty else trades
    round_trips = len(closed)
    win_rate = (closed["pnl_pct"] > 0).mean() if round_trips else math.nan
    avg_trade_pnl = closed["pnl_pct"].mean() if round_trips else math.nan
    gross_profit = closed.loc[closed["pnl_pct"] > 0, "pnl_pct"].sum() if round_trips else 0.0
    gross_loss = -closed.loc[closed["pnl_pct"] <= 0, "pnl_pct"].sum() if round_trips else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else math.nan)

    return {
        "final_equity": float(equity.iloc[-1]),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "ann_volatility": float(ann_vol),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "calmar": float(calmar),
        "time_in_market": float(position.mean()),
        "round_trips": float(round_trips),
        "win_rate": float(win_rate),
        "avg_trade_pnl_pct": float(avg_trade_pnl),
        "profit_factor": float(profit_factor),
    }
