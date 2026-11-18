"""Parameter-space expansion, shared by every search and sweep."""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from typing import Any


def expand_space(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of a grid, as a list of dicts in key order. An empty grid gives one empty dict."""
    keys = list(grid)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*(grid[k] for k in keys))]
