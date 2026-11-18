"""One ordered process pool for every compute-heavy loop.

Workers compute only. They never write to DuckDB or MLflow: a DuckDB connection must be opened per worker
(never inherited across fork), and MLflow's sqlite backend is single-writer, so the parent records results.

Workers are forked, so data set in module globals before the call is visible to them without pickling.
Results come back in input order, so sums and tables built from them match a serial run exactly.

Worker count: `IBBT_WORKERS` (default: CPU count), capped at the number of items. Each worker holds its own
copy of whatever data the caller loads, so the cap bounds memory as well as CPU.
"""

from __future__ import annotations

import multiprocessing as mp
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def default_workers() -> int:
    return max(1, int(os.getenv("IBBT_WORKERS", str(os.cpu_count() or 1))))


def pmap(
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int | None = None,
    *,
    min_items: int = 2,
) -> list[R]:
    """Apply `fn` to each item, in parallel when it helps, returning results in input order.

    Runs serially when there are fewer than `min_items` items, since forking costs more than a small batch saves.
    """
    work = list(items)
    n = min(workers or default_workers(), len(work))
    if n <= 1 or len(work) < min_items:
        return [fn(item) for item in work]
    with ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("fork")) as pool:
        return list(pool.map(fn, work))
