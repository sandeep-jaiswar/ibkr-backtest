"""Interactive Brokers historical data source (read-only).

Uses ib_async against a running TWS or IB Gateway with the API enabled. Only data
requests are made; this module never places orders.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta

import pandas as pd
from ib_async import IB, Stock, util

from ibbt.config import Settings

PACING_SECONDS = 1.0  # IB limits historical data requests; stay well under the cap


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
) -> pd.DataFrame:
    """Fetch adjusted-for-trades daily bars between start and end (inclusive).

    Returns a frame with columns: ts, open, high, low, close, volume.
    """
    qualified = await ib.qualifyContractsAsync(Stock(symbol, exchange, currency))
    if not qualified or not qualified[0].conId:
        raise ValueError(f"IB could not resolve contract for {symbol} ({exchange}/{currency})")
    contract = qualified[0]

    frames: list[pd.DataFrame] = []
    cursor = end + timedelta(days=1)  # IB's endDateTime is exclusive at midnight
    while cursor > start:
        end_str = datetime.combine(cursor, time(0)).strftime("%Y%m%d %H:%M:%S")
        raw = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime=end_str,
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        if not raw:
            break
        chunk = util.df(raw)
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
