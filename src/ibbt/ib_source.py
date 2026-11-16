"""Interactive Brokers historical data source (read-only).

Uses ib_async against a running TWS or IB Gateway with the API enabled. Only data
requests are made; this module never places orders.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
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
    except (OSError, asyncio.TimeoutError) as exc:
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


async def _request_chunk(ib: IB, contract: Any, end_str: str) -> Any:
    """One historical-data request, retried on errors up to MAX_ATTEMPTS times."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end_str,
                durationStr="1 Y",
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
                end_str, attempt, MAX_ATTEMPTS, exc, delay,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def missing_ranges(
    coverage: tuple[date, date] | None, start: date, end: date
) -> list[tuple[date, date]]:
    """Date ranges not yet in the store. Assumes stored data is contiguous."""
    if coverage is None:
        return [(start, end)]
    lo, hi = coverage
    gaps: list[tuple[date, date]] = []
    if start < lo:
        gaps.append((start, min(end, lo - timedelta(days=1))))
    if end > hi:
        gaps.append((max(start, hi + timedelta(days=1)), end))
    return [(a, b) for a, b in gaps if a <= b]


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
    persist progress before the whole range is done.
    """
    qualified = await ib.qualifyContractsAsync(Stock(symbol, exchange, currency))
    if not qualified or not qualified[0].conId:
        raise ValueError(f"IB could not resolve contract for {symbol} ({exchange}/{currency})")
    contract = qualified[0]

    frames: list[pd.DataFrame] = []
    cursor = end + timedelta(days=1)  # IB's endDateTime is exclusive at midnight
    while cursor > start:
        end_str = datetime.combine(cursor, time(0)).strftime("%Y%m%d %H:%M:%S")
        raw = await _request_chunk(ib, contract, end_str)
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
        await asyncio.sleep(PACING_SECONDS)

    columns = ["ts", "open", "high", "low", "close", "volume"]
    if not frames:
        return pd.DataFrame(columns=columns)

    df = pd.concat(frames).drop_duplicates("date")
    df["ts"] = pd.to_datetime(df["date"])
    df = df[(df["ts"] >= pd.Timestamp(start)) & (df["ts"] <= pd.Timestamp(end))]
    return df[columns].sort_values("ts").reset_index(drop=True)
