"""Validation helpers: buy-and-hold benchmark, walk-forward evaluation and overfitting checks.

Walk-forward windows are half-open in calendar time: a window [a, b) holds the bars with a <= ts < b.
The slices returned by `walk_forward_splits` are closed label slices (`bars.loc[s]`) that cover
exactly the bars in those windows, so consecutive windows never share a bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ibbt.engine import BacktestConfig, run_backtest
from ibbt.metrics import compute_metrics
from ibbt.strategies import BuyAndHold, make_strategy


def _evaluate(bars: pd.DataFrame, signal: pd.Series, cfg: BacktestConfig) -> dict[str, float]:
    result = run_backtest(bars, signal, cfg)
    return compute_metrics(result.equity, result.trades, result.position)


def benchmark_metrics(bars: pd.DataFrame, cfg: BacktestConfig) -> dict[str, float]:
    """Metrics for buying at the first open and holding, run through the same engine and costs."""
    return _evaluate(bars, BuyAndHold().signal(bars), cfg)


def excess_return(strategy_metrics: dict[str, float], benchmark_metrics: dict[str, float]) -> float:
    """Strategy total return minus benchmark total return, as a fraction of starting capital."""
    return strategy_metrics["total_return"] - benchmark_metrics["total_return"]


def _date_slice(index: pd.DatetimeIndex, start: pd.Timestamp, stop: pd.Timestamp, label: str) -> slice:
    lo = index.searchsorted(start, side="left")
    hi = index.searchsorted(stop, side="left")  # exclusive
    if hi <= lo:
        raise ValueError(f"{label} window [{start}, {stop}) contains no bars")
    return slice(index[lo], index[hi - 1])


def walk_forward_splits(
    index: pd.DatetimeIndex,
    n_folds: int,
    train_years: int,
    test_years: int,
) -> list[tuple[slice, slice]]:
    """Rolling train/test folds ending at the last bar.

    Test windows are consecutive, each `test_years` long, and tile the final `n_folds * test_years`.
    Each fold's train window is the `train_years` immediately before its test window, so training
    always ends before testing starts. Raises if a train window would begin before the data does.
    """
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a DatetimeIndex")
    if index.empty:
        raise ValueError("cannot split an empty index")
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError("index must be sorted and free of duplicates")
    if n_folds < 1 or train_years < 1 or test_years < 1:
        raise ValueError("n_folds, train_years and test_years must all be at least 1")

    # Exclusive end at the next midnight, so the last bar falls inside the final test window.
    end = index[-1].normalize() + pd.Timedelta(days=1)
    bounds = [end - pd.DateOffset(years=test_years * (n_folds - k)) for k in range(n_folds + 1)]

    folds: list[tuple[slice, slice]] = []
    for k in range(n_folds):
        test_start, test_stop = bounds[k], bounds[k + 1]
        train_start = test_start - pd.DateOffset(years=train_years)
        if train_start < index[0]:
            raise ValueError(
                f"fold {k} needs train data from {train_start.date()}, but the index starts {index[0].date()}"
            )
        train = _date_slice(index, train_start, test_start, f"fold {k} train")
        test = _date_slice(index, test_start, test_stop, f"fold {k} test")
        folds.append((train, test))
    return folds


def _grid_results(
    bars: pd.DataFrame,
    strategy_name: str,
    grid: list[dict],
    cfg: BacktestConfig,
) -> pd.DataFrame:
    """One row per grid entry that runs (entries raising ValueError are skipped), indexed by grid position."""
    rows: dict[int, dict] = {}
    for pos, params in enumerate(grid):
        try:
            strategy = make_strategy(strategy_name, params)
            metrics = _evaluate(bars, strategy.signal(bars), cfg)
        except ValueError:
            continue
        rows[pos] = {**params, **metrics}
    return pd.DataFrame.from_dict(rows, orient="index")


def walk_forward_eval(
    bars: pd.DataFrame,
    strategy_name: str,
    grid: list[dict],
    cfg: BacktestConfig,
    n_folds: int,
    train_years: int,
    test_years: int,
) -> pd.DataFrame:
    """Pick the best grid entry by train-window Sharpe in each fold, then score it out of sample.

    The strategy is re-run on each window's own bars, so a test window's signal never sees
    bars outside that window. Returns one row per fold with the chosen params, the train Sharpe
    and the test-window metrics prefixed with `oos_`.
    """
    if not grid:
        raise ValueError("grid must contain at least one parameter set")

    param_keys = list(dict.fromkeys(key for params in grid for key in params))
    splits = walk_forward_splits(bars.index, n_folds, train_years, test_years)

    rows = []
    for k, (train_slice, test_slice) in enumerate(splits):
        train_bars = bars.loc[train_slice]
        test_bars = bars.loc[test_slice]

        fits = _grid_results(train_bars, strategy_name, grid, cfg)
        valid = fits.dropna(subset=["sharpe"]) if not fits.empty else fits
        if valid.empty:
            raise ValueError(f"fold {k}: no grid entry produced a finite train Sharpe")
        best_pos = valid["sharpe"].astype(float).idxmax()
        chosen = grid[best_pos]

        oos = _evaluate(test_bars, make_strategy(strategy_name, chosen).signal(test_bars), cfg)
        rows.append(
            {
                "fold": k,
                "train_start": train_bars.index[0],
                "train_end": train_bars.index[-1],
                "test_start": test_bars.index[0],
                "test_end": test_bars.index[-1],
                **{key: chosen.get(key) for key in param_keys},
                "train_sharpe": float(valid.loc[best_pos, "sharpe"]),
                **{f"oos_{name}": value for name, value in oos.items()},
            }
        )
    return pd.DataFrame(rows)


def overfit_warning(grid_results: pd.DataFrame, param_cols: list[str]) -> str | None:
    """Warn when the best-Sharpe grid row sits on the edge of the searched range.

    `grid_results` needs a `sharpe` column plus one column per parameter. A parameter that
    takes only one value in the grid is ignored. Returns None when no parameter is at an edge.
    """
    if "sharpe" not in grid_results.columns:
        raise ValueError("grid_results needs a 'sharpe' column")
    missing = [c for c in param_cols if c not in grid_results.columns]
    if missing:
        raise ValueError(f"grid_results is missing parameter columns: {missing}")

    sharpe = grid_results["sharpe"].astype(float).to_numpy()
    finite = ~pd.isna(sharpe)
    if not finite.any():
        raise ValueError("grid_results has no finite sharpe values")
    best = grid_results.iloc[int(np.nanargmax(sharpe))]

    messages = []
    for col in param_cols:
        values = grid_results[col].dropna()
        best_value = best[col]
        if values.nunique() < 2 or pd.isna(best_value):
            continue
        if best_value == values.min():
            edge = "minimum"
        elif best_value == values.max():
            edge = "maximum"
        else:
            continue
        messages.append(
            f"best sharpe is at the {edge} of {col!r} ({best_value}); the optimum may lie outside the searched grid"
        )
    return "; ".join(messages) if messages else None
