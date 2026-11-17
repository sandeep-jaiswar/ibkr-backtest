"""Interactive Brokers historical data source (read-only).

Uses ib_async against a running TWS or IB Gateway with the API enabled. Only data
requests are made; this module never places orders.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
from ib_async import IB, Stock, util

from ibbt.config import Settings

logger = logging.getLogger(__name__)

PACING_SECONDS = 1.0  # IB limits historical data requests; stay well under the cap
MAX_ATTEMPTS = 3  # tries per chunk before the error is raised to the caller
BACKOFF_SECONDS = 2.0  # transient errors: doubled after each failed attempt
PACING_BACKOFF_SECONDS = 60.0  # IB pacing violations need a full minute to clear
PACING_ERROR_CODE = 162


@asynccontextmanager
async def connect(settings: Settings) -> AsyncIterator[IB]:
    ib = IB()
    try:
        await ib.connectAsync(
            settings.ib_host,
            settings.ib_port,
            clientId=settings.ib_client_id,
            timeout=20,
            readonly=True,
        )
    except (TimeoutError, OSError) as exc:
        raise ConnectionError(
            f"could not connect to IB at {settings.ib_host}:{settings.ib_port}. "
            "Is TWS or IB Gateway running with API access enabled?"
        ) from exc
    try:
        yield ib
    finally:
        ib.disconnect()


def _is_pacing_error(exc: BaseException) -> bool:
    return getattr(exc, "code", None) == PACING_ERROR_CODE or "pacing" in str(exc).lower()


def duration_str(days: int) -> str:
    """IB duration for a daily-bar request covering `days` calendar days (one request per symbol)."""
    if days <= 365:
        return "1 Y"
    return f"{math.ceil(days / 365.25)} Y"


async def _request_chunk(ib: IB, contract: Any, end_str: str, duration: str = "1 Y") -> Any:
    """One historical-data request, retried on errors up to MAX_ATTEMPTS times."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end_str,
                durationStr=duration,
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
            )
        except Exception as exc:
            if attempt == MAX_ATTEMPTS:
                raise
            if _is_pacing_error(exc):
                delay = PACING_BACKOFF_SECONDS
            else:
                delay = BACKOFF_SECONDS * 2 ** (attempt - 1)
            logger.warning(
                "historical request ending %s failed (attempt %d/%d): %s; retrying in %.0fs",
                end_str,
                attempt,
                MAX_ATTEMPTS,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def missing_ranges(
    coverage: tuple[date, date] | None,
    start: date,
    end: date,
    fetched: Iterable[tuple[date, date]] = (),
) -> list[tuple[date, date]]:
    """Sub-ranges of [start, end] not yet covered.

    `coverage` is the stored (first, last) bar date, assumed contiguous. `fetched` holds
    (start, end) windows that were already requested from IB, including empty ones (IB had
    no bars there, e.g. before a late IPO), so those windows are not re-requested.
    Both inputs are inclusive; the result is sorted, non-overlapping and inclusive.
    """
    covered: list[tuple[date, date]] = []
    if coverage is not None:
        covered.append(coverage)
    covered.extend(fetched)

    # Clip each covered window to the requested range, drop empties, then merge overlapping or adjacent ones.
    clipped = sorted((max(a, start), min(b, end)) for a, b in covered if a <= b and a <= end and b >= start)
    merged: list[tuple[date, date]] = []
    for a, b in clipped:
        if merged and a <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    gaps: list[tuple[date, date]] = []
    cursor = start
    for a, b in merged:
        if cursor < a:
            gaps.append((cursor, a - timedelta(days=1)))
        cursor = max(cursor, b + timedelta(days=1))
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


async def fetch_daily_bars(
    ib: IB,
    symbol: str,
    start: date,
    end: date,
    exchange: str = "SMART",
    currency: str = "USD",
    on_chunk: Callable[[pd.DataFrame], None] | None = None,
) -> pd.DataFrame:
    """Fetch adjusted-for-trades daily bars between start and end (inclusive).

    Returns a frame with columns: ts, open, high, low, close, volume.
    `on_chunk` receives each raw (untrimmed) chunk as it arrives, so callers can
    persist progress before the whole range is done. Chunks may extend beyond
    [start, end]; callers that persist them must filter to the range themselves.
    The returned frame is already trimmed to [start, end] and sorted by ts.
    """
    raw = await ib.qualifyContractsAsync(Stock(symbol, exchange, currency))
    candidates: list[Any] = list(raw) if isinstance(raw, list) else [raw]
    resolved = [c for c in candidates if c is not None and c.conId]
    if not resolved:
        raise ValueError(f"IB could not resolve contract for {symbol} ({exchange}/{currency})")
    contract = resolved[0]

    frames: list[pd.DataFrame] = []
    cursor = end + timedelta(days=1)  # IB's endDateTime is exclusive at midnight
    while cursor > start:
        end_str = datetime.combine(cursor, time(0)).strftime("%Y%m%d %H:%M:%S")
        raw = await _request_chunk(ib, contract, end_str, duration_str((cursor - start).days))
        if not raw:
            break
        chunk = util.df(raw)
        if on_chunk is not None:
            on_chunk(chunk)
        frames.append(chunk)
        earliest = pd.Timestamp(chunk["date"].min()).date()
        if earliest >= cursor:  # no backward progress; stop rather than loop forever
            break
        cursor = earliest
        if cursor > start:  # pace only before another request, not after the last one
            await asyncio.sleep(PACING_SECONDS)

    columns = ["ts", "open", "high", "low", "close", "volume"]
    if not frames:
        return pd.DataFrame(columns=columns)

    df = pd.concat(frames).drop_duplicates("date")
    df["ts"] = pd.to_datetime(df["date"])
    df = df[(df["ts"] >= pd.Timestamp(start)) & (df["ts"] <= pd.Timestamp(end))]
    return df[columns].sort_values("ts").reset_index(drop=True)
