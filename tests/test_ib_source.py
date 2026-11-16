"""Exercises the IB fetch loop against a fake client, so no gateway is needed."""
import asyncio

from datetime import date, datetime, timedelta

import pandas as pd
from ib_async.objects import BarData

from ibbt import ib_source


class FakeIB:
    """Returns one year of business-day bars ending before each requested endDateTime."""

    def __init__(self):
        self.requests: list[str] = []

    async def qualifyContractsAsync(self, contract):
        contract.conId = 265598
        return [contract]

    async def reqHistoricalDataAsync(self, contract, endDateTime, **kwargs):
        self.requests.append(endDateTime)
        end = datetime.strptime(endDateTime, "%Y%m%d %H:%M:%S").date()
        days = pd.bdate_range(end - timedelta(days=365), end - timedelta(days=1))
        return [
            BarData(date=d.date(), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0, average=100.2, barCount=5)
            for d in days
        ]


def test_fetch_pages_backwards_and_trims_to_range(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    ib = FakeIB()
    start, end = date(2021, 1, 1), date(2023, 3, 31)

    df = asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", start, end))

    assert df["ts"].min() >= pd.Timestamp(start)
    assert df["ts"].max() <= pd.Timestamp(end)
    assert not df["ts"].duplicated().any()
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(ib.requests) >= 3  # 2021-2023 spans several 1-year requests


def test_missing_ranges_helper_used_by_backfill():
    assert ib_source.missing_ranges(None, date(2020, 1, 1), date(2020, 1, 31)) == [
        (date(2020, 1, 1), date(2020, 1, 31))
    ]
