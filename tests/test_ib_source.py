"""Exercises the IB fetch loop against a fake client, so no gateway is needed."""

import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from ib_async.objects import BarData
from ib_async.wrapper import RequestError

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
            BarData(
                date=d.date(), open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0, average=100.2, barCount=5
            )
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


class FlakyIB(FakeIB):
    """Fails the first `failures` requests with `errors[i]`, then behaves like FakeIB."""

    def __init__(self, errors: list[Exception]):
        super().__init__()
        self.errors = list(errors)

    async def reqHistoricalDataAsync(self, contract, endDateTime, **kwargs):
        if self.errors:
            self.requests.append(endDateTime)
            raise self.errors.pop(0)
        return await super().reqHistoricalDataAsync(contract, endDateTime, **kwargs)


class _Sleeps:
    def __init__(self, monkeypatch):
        self.delays: list[float] = []

        async def fake_sleep(delay, *args, **kwargs):
            self.delays.append(delay)

        monkeypatch.setattr(ib_source.asyncio, "sleep", fake_sleep)


def test_transient_error_is_retried_with_backoff(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    sleeps = _Sleeps(monkeypatch)
    ib = FlakyIB([ConnectionResetError("socket dropped")])

    df = asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", date(2022, 1, 3), date(2022, 6, 30)))

    assert not df.empty
    assert len(ib.requests) == 2  # one failure, one success for the same chunk
    assert ib.requests[0] == ib.requests[1]
    assert sleeps.delays[0] == ib_source.BACKOFF_SECONDS  # then the normal inter-chunk pause


def test_pacing_violation_waits_sixty_seconds(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    sleeps = _Sleeps(monkeypatch)
    pacing = RuntimeError("Historical data request pacing violation")
    ib = FlakyIB([pacing])

    asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", date(2022, 1, 3), date(2022, 6, 30)))

    assert sleeps.delays[0] == 60


def test_error_code_162_counts_as_pacing(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    sleeps = _Sleeps(monkeypatch)
    err = RequestError(1, 162, "Historical Market Data Service error message:")
    ib = FlakyIB([err])

    asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", date(2022, 1, 3), date(2022, 6, 30)))

    assert sleeps.delays[0] == 60


def test_gives_up_after_three_attempts(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    sleeps = _Sleeps(monkeypatch)
    ib = FlakyIB([OSError("down")] * 5)

    with pytest.raises(OSError, match="down"):
        asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", date(2022, 1, 3), date(2022, 6, 30)))

    assert len(ib.requests) == ib_source.MAX_ATTEMPTS
    assert sleeps.delays == [2.0, 4.0]  # exponential: 2s after attempt 1, 4s after attempt 2


def test_on_chunk_receives_each_raw_chunk(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    seen: list[pd.DataFrame] = []
    ib = FakeIB()

    df = asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", date(2021, 1, 1), date(2023, 3, 31), on_chunk=seen.append))

    assert len(seen) == len(ib.requests)
    assert all(isinstance(c, pd.DataFrame) and not c.empty for c in seen)
    assert len(df) <= sum(len(c) for c in seen)  # trimming never adds rows


@pytest.mark.parametrize(
    "days, expected",
    [(1, "1 Y"), (365, "1 Y"), (366, "2 Y"), (4383, "12 Y"), (4400, "13 Y")],
)
def test_duration_str_covers_span_in_one_request(days, expected):
    assert ib_source.duration_str(days) == expected


def test_single_request_covers_full_range(monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)

    class LongIB(FakeIB):
        async def reqHistoricalDataAsync(self, contract, endDateTime, durationStr, **kwargs):
            self.requests.append((endDateTime, durationStr))
            return await super().reqHistoricalDataAsync(contract, endDateTime, **kwargs)

    ib = LongIB()
    asyncio.run(ib_source.fetch_daily_bars(ib, "AAPL", date(2015, 1, 1), date(2026, 11, 15)))
    assert ib.requests[0][1] == "12 Y"
