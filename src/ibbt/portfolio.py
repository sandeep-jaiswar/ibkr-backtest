"""Portfolio backtest: one account, a fixed sleeve per trade, and a cap on open positions.

Timing matches the single-symbol engine:
  * A signal computed from bar t's close is an order for bar t+1.
  * Signal orders fill at bar t+1's open, adjusted by slippage against the trader.
  * Stop, target and time exits are checked on each bar after the entry logic.
  * Commission is charged on notional, on each side. Equity is marked to each bar's close.

Funding rule (constrained mode):
  * Each entry gets `position_size` dollars, or whatever free cash is left if that is smaller.
  * An entry smaller than `min_position_size` is skipped, so the account never over-trades.
  * At most `max_positions` positions are open at once.

Candidate ranking: when more signals fire than there are free slots, the strategy's
`rank_score` (computed on the previous bar's close) decides who goes first. Without a score,
a seeded random tie-break is used, so runs are reproducible and carry no alphabetical bias.

Unconstrained mode (`max_positions=None`): every signal is taken at the full `position_size`
with no cash check. It gives pooled per-trade statistics, which show what the strategy does
without the slot limit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADE_COLUMNS = [
    "symbol",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "exit_reason",
    "bars_held",
    "pnl",
    "pnl_pct",
    "open",
]


@dataclass(frozen=True)
class PortfolioConfig:
    initial_cash: float = 10_000.0
    max_positions: int | None = 5  # None = unconstrained
    position_size: float = 2_000.0
    min_position_size: float = 1_000.0
    commission_bps: float = 5.0  # per side, on notional
    slippage_bps: float = 5.0  # per side, adverse to the trader
    stop_pct: float | None = None  # exit when the low reaches entry * (1 - stop_pct)
    target_pct: float | None = None  # exit when the high reaches entry * (1 + target_pct)
    max_hold: int | None = None  # exit at the open once a position is held this many bars

    def __post_init__(self) -> None:
        if self.position_size <= 0:
            raise ValueError("position_size must be positive")
        if not 0 < self.min_position_size <= self.position_size:
            raise ValueError("min_position_size must be in (0, position_size]")
        if self.max_positions is not None:
            if self.max_positions < 1:
                raise ValueError("max_positions must be at least 1, or None for unconstrained")
            if self.max_positions * self.position_size > self.initial_cash + 1e-9:
                raise ValueError("max_positions * position_size exceeds initial_cash")
        if self.stop_pct is not None and not 0 < self.stop_pct < 1:
            raise ValueError("stop_pct must be in (0, 1)")
        if self.target_pct is not None and self.target_pct <= 0:
            raise ValueError("target_pct must be positive")
        if self.max_hold is not None and self.max_hold < 1:
            raise ValueError("max_hold must be at least 1 bar")

    def as_params(self) -> dict[str, object]:
        return {
            "initial_cash": self.initial_cash,
            "max_positions": self.max_positions if self.max_positions is not None else "unconstrained",
            "position_size": self.position_size,
            "min_position_size": self.min_position_size,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "stop_pct": self.stop_pct if self.stop_pct is not None else "none",
            "target_pct": self.target_pct if self.target_pct is not None else "none",
            "max_hold": self.max_hold if self.max_hold is not None else "none",
        }


@dataclass
class PortfolioResult:
    equity: pd.Series  # marked to each bar's close
    exposure: pd.Series  # number of open positions at each close
    trades: pd.DataFrame  # one row per round trip; `open` marks positions still held at the end
    skipped_entries: int  # candidate entries that found no free slot or enough cash


def run_portfolio(
    opens: pd.DataFrame,
    highs: pd.DataFrame,
    lows: pd.DataFrame,
    closes: pd.DataFrame,
    signal: pd.DataFrame,
    cfg: PortfolioConfig,
    rank: pd.DataFrame | None = None,
    seed: int = 0,
) -> PortfolioResult:
    """Simulate one account over wide frames (dates x symbols). NaN means no bar for that symbol that day.

    `signal` holds 1 (long) or 0 (flat) at each close. `rank` is lower-is-better, read at the close
    before the entry bar; if it is None, a seeded random tie-break is used instead.
    """
    dates = opens.index
    cols = opens.columns
    O = opens.to_numpy(dtype=float)
    H = highs.reindex(index=dates, columns=cols).to_numpy(dtype=float)
    L = lows.reindex(index=dates, columns=cols).to_numpy(dtype=float)
    C = closes.reindex(index=dates, columns=cols).to_numpy(dtype=float)
    S = signal.reindex(index=dates, columns=cols).fillna(0).to_numpy(dtype=np.int8)
    if rank is None:
        R = np.random.default_rng(seed).random(O.shape)
    else:
        R = rank.reindex(index=dates, columns=cols).to_numpy(dtype=float)
        R = np.where(np.isnan(R), np.inf, R)

    n, m = O.shape
    constrained = cfg.max_positions is not None
    limit = cfg.max_positions if constrained else m
    slip = cfg.slippage_bps / 10_000
    comm = cfg.commission_bps / 10_000

    cash = cfg.initial_cash
    held = np.zeros(m, dtype=bool)
    shares = np.zeros(m)
    entry_px = np.zeros(m)
    entry_i = np.zeros(m, dtype=int)
    last_close = np.full(m, np.nan)
    trades: list[dict] = []
    skipped = 0

    def close_position(j: int, i: int, base: float, reason: str) -> None:
        # Hot path: plain numbers only. Dates are resolved once, after the loop.
        nonlocal cash
        fill = base * (1 - slip)
        proceeds = shares[j] * fill * (1 - comm)
        cash += proceeds
        cost = shares[j] * entry_px[j] * (1 + comm)
        trades.append((j, entry_i[j], i, entry_px[j], fill, reason, proceeds - cost, proceeds / cost - 1, False))
        held[j] = False
        shares[j] = 0.0

    equity = np.empty(n)
    exposure = np.zeros(n, dtype=int)
    for i in range(n):
        if i > 0:
            # 1. Signal exits: the order was decided at the previous close and fills at this open.
            for j in np.flatnonzero(held & (S[i - 1] == 0)):
                if np.isfinite(O[i, j]):
                    close_position(j, i, O[i, j], "signal")

            # 2. Entries: candidates that were long at the previous close, best rank first.
            free = limit - int(held.sum())
            candidates = np.flatnonzero((S[i - 1] == 1) & ~held & np.isfinite(O[i]) & (O[i] > 0))
            if candidates.size:
                candidates = candidates[np.argsort(R[i - 1, candidates], kind="stable")]
            for j in candidates:
                size = min(cfg.position_size, cash) if constrained else cfg.position_size
                if free <= 0 or (constrained and size < cfg.min_position_size):
                    skipped += 1
                    continue
                fill = O[i, j] * (1 + slip)
                shares[j] = size / (fill * (1 + comm))
                entry_px[j] = fill
                entry_i[j] = i
                last_close[j] = fill
                held[j] = True
                cash -= size
                free -= 1

        # 3. Intrabar exits on today's range. If the stop and target both sit inside the bar,
        #    the stop is assumed to fill first, which is the conservative order.
        for j in np.flatnonzero(held):
            o, h, lo = O[i, j], H[i, j], L[i, j]
            if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(lo)):
                continue
            stop_px = entry_px[j] * (1 - cfg.stop_pct) if cfg.stop_pct is not None else None
            target_px = entry_px[j] * (1 + cfg.target_pct) if cfg.target_pct is not None else None
            reason, base = None, 0.0
            if stop_px is not None and o <= stop_px:
                reason, base = "stop", o  # gapped through the stop: fill at the open
            elif target_px is not None and o >= target_px:
                reason, base = "target", o  # gapped above the target: fill at the open
            elif stop_px is not None and lo <= stop_px:
                reason, base = "stop", stop_px
            elif target_px is not None and h >= target_px:
                reason, base = "target", target_px
            elif cfg.max_hold is not None and i - entry_i[j] >= cfg.max_hold:
                reason, base = "time", o
            if reason is not None:
                close_position(j, i, base, reason)

        # 4. Mark to the close. A missing close carries the last known price forward.
        has_close = np.isfinite(C[i])
        last_close = np.where(has_close, C[i], last_close)
        equity[i] = cash + float(np.sum(shares[held] * last_close[held]))
        exposure[i] = int(held.sum())

    for j in np.flatnonzero(held):  # still open at the end: report, but do not count as closed
        fill = last_close[j] * (1 - slip)
        proceeds = shares[j] * fill * (1 - comm)
        cost = shares[j] * entry_px[j] * (1 + comm)
        trades.append((j, entry_i[j], n - 1, entry_px[j], fill, "end", proceeds - cost, proceeds / cost - 1, True))

    table = pd.DataFrame(trades, columns=["sym", "ei", "xi", "entry_price", "exit_price", "exit_reason", "pnl", "pnl_pct", "open"])
    trade_df = pd.DataFrame(
        {
            "symbol": cols.to_numpy()[table["sym"].to_numpy(dtype=int)],
            "entry_date": dates.take(table["ei"].to_numpy(dtype=int)),
            "entry_price": table["entry_price"].to_numpy(dtype=float),
            "exit_date": dates.take(table["xi"].to_numpy(dtype=int)),
            "exit_price": table["exit_price"].to_numpy(dtype=float),
            "exit_reason": table["exit_reason"].to_numpy(),
            "bars_held": (table["xi"] - table["ei"]).to_numpy(dtype=int),
            "pnl": table["pnl"].to_numpy(dtype=float),
            "pnl_pct": table["pnl_pct"].to_numpy(dtype=float),
            "open": table["open"].to_numpy(dtype=bool),
        },
        columns=TRADE_COLUMNS,
    )
    return PortfolioResult(
        equity=pd.Series(equity, index=dates, name="equity"),
        exposure=pd.Series(exposure, index=dates, name="exposure"),
        trades=trade_df,
        skipped_entries=skipped,
    )


def portfolio_metrics(result: PortfolioResult, cfg: PortfolioConfig, periods_per_year: int = 252) -> dict[str, float]:
    """Metrics on closed trades in dollars, plus equity-curve risk figures."""
    eq = result.equity
    if len(eq) < 2:
        raise ValueError("need at least two bars to compute metrics")

    rets = eq.pct_change().dropna()
    total_return = eq.iloc[-1] / cfg.initial_cash - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else math.nan
    ret_std = rets.std(ddof=1)
    sharpe = rets.mean() / ret_std * math.sqrt(periods_per_year) if ret_std > 0 else math.nan
    max_drawdown = (eq / eq.cummax() - 1).min()

    trades = result.trades
    closed = trades.loc[~trades["open"].astype(bool)] if not trades.empty else trades
    wins = closed.loc[closed["pnl"] > 0, "pnl"]
    losses = closed.loc[closed["pnl"] <= 0, "pnl"]
    n_closed = len(closed)
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = math.inf if gross_profit > 0 else math.nan

    return {
        "final_equity": float(eq.iloc[-1]),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "round_trips": float(n_closed),
        "win_rate": float((closed["pnl"] > 0).mean()) if n_closed else math.nan,
        "profit_factor": float(profit_factor),
        "net_pnl": float(closed["pnl"].sum()) if n_closed else 0.0,
        "avg_trade_pnl_pct": float(closed["pnl_pct"].mean()) if n_closed else math.nan,
        "avg_win_pct": float(closed.loc[closed["pnl"] > 0, "pnl_pct"].mean()) if len(wins) else math.nan,
        "avg_loss_pct": float(closed.loc[closed["pnl"] <= 0, "pnl_pct"].mean()) if len(losses) else math.nan,
        "avg_bars_held": float(closed["bars_held"].mean()) if n_closed else math.nan,
        "time_in_market": float((result.exposure > 0).mean()),
        "avg_positions": float(result.exposure.mean()),
        "skipped_entries": float(result.skipped_entries),
    }
