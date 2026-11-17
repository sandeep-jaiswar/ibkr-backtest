"""Backfill runs symbols concurrently and re-runs must never duplicate rows."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from test_ib_source import FakeIB

from ibbt import cli, ib_source
from ibbt.config import Settings
from ibbt.store import Store


class ConnectedFakeIB(FakeIB):
    def isConnected(self):
        return True


def _fake_connect(ib):
    @asynccontextmanager
    async def connect(settings):
        yield ib

    return connect


def test_concurrent_backfill_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    ib = ConnectedFakeIB()
    monkeypatch.setattr(ib_source, "connect", _fake_connect(ib))
    settings = Settings(duckdb_path=tmp_path / "t.duckdb")
    symbols = ["AAA", "BBB", "CCC"]
    start, end = date(2021, 1, 1), date(2021, 6, 30)

    with Store(settings.duckdb_path) as store:
        first = asyncio.run(cli._backfill(settings, store, symbols, start, end, "SMART", "USD", concurrency=3))
        count_after_first = store.con.execute("select count(*) from bars").fetchone()[0]
        second = asyncio.run(cli._backfill(settings, store, symbols, start, end, "SMART", "USD", concurrency=3))
        count_after_second = store.con.execute("select count(*) from bars").fetchone()[0]
        dups = store.con.execute(
            "select count(*) from (select symbol, ts from bars group by 1,2 having count(*)>1)"
        ).fetchone()[0]

    assert sorted(first["stored"]) == symbols
    assert count_after_first > 0
    assert count_after_second == count_after_first
    assert dups == 0
    assert sorted(second["covered"]) == symbols


def _requested_dates(ib):
    return [datetime.strptime(s, "%Y%m%d %H:%M:%S").date() for s in ib.requests]


class DyingIB(ConnectedFakeIB):
    """Serves `good` requests, then fails every later one (as if IB errors out mid-gap)."""

    def __init__(self, good: int):
        super().__init__()
        self.good = good

    async def reqHistoricalDataAsync(self, contract, endDateTime, **kwargs):
        if len(self.requests) >= self.good:
            self.requests.append(endDateTime)
            raise OSError("IB dropped the request")
        return await super().reqHistoricalDataAsync(contract, endDateTime, **kwargs)


class LateIPOIB(ConnectedFakeIB):
    """Symbol listed on `ipo`: IB has no bars before that date."""

    def __init__(self, ipo: date):
        super().__init__()
        self.ipo = ipo

    async def reqHistoricalDataAsync(self, contract, endDateTime, **kwargs):
        bars = await super().reqHistoricalDataAsync(contract, endDateTime, **kwargs)
        return [b for b in bars if b.date >= self.ipo]


def test_mid_gap_failure_keeps_downloaded_chunks_and_resume_skips_them(tmp_path, monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    monkeypatch.setattr(ib_source.asyncio, "sleep", _no_sleep)
    settings = Settings(duckdb_path=tmp_path / "t.duckdb")
    start, end = date(2019, 1, 1), date(2021, 6, 30)

    with Store(settings.duckdb_path) as store:
        # First request succeeds; the next three attempts (MAX_ATTEMPTS) all fail.
        broken = DyingIB(good=1)
        monkeypatch.setattr(ib_source, "connect", _fake_connect(broken))
        first = asyncio.run(cli._backfill(settings, store, ["AAA"], start, end, "SMART", "USD"))

        assert first["failed"] and first["failed"][0][0] == "AAA"
        stored_low, stored_high = store.coverage("AAA")
        assert stored_high == end  # top chunk is in the database
        assert stored_low > start  # the rest of the gap was never written
        assert store.fetched_ranges("AAA") == []  # gap not finished, so nothing logged as fetched
        partial_rows = store.con.execute("select count(*) from bars where symbol='AAA'").fetchone()[0]
        assert partial_rows > 0

        # Re-run against a healthy connection: only the missing older part is requested.
        healthy = ConnectedFakeIB()
        monkeypatch.setattr(ib_source, "connect", _fake_connect(healthy))
        second = asyncio.run(cli._backfill(settings, store, ["AAA"], start, end, "SMART", "USD"))

        assert second["stored"] == ["AAA"]
        # endDateTime is exclusive, so the resume requests end at the stored low bound and go backwards.
        requested = _requested_dates(healthy)
        assert requested and all(d <= stored_low for d in requested)
        assert store.coverage("AAA") == (start, end)
        # Only the resumed window was fetched and logged; the earlier run logged nothing.
        assert store.fetched_ranges("AAA") == [(start, stored_low - timedelta(days=1))]
        dups = store.con.execute(
            "select count(*) from (select ts from bars where symbol='AAA' group by ts having count(*) > 1)"
        ).fetchone()[0]
        assert dups == 0


def test_late_ipo_window_is_logged_once_and_not_requested_again(tmp_path, monkeypatch):
    monkeypatch.setattr(ib_source, "PACING_SECONDS", 0)
    settings = Settings(duckdb_path=tmp_path / "t.duckdb")
    start, end = date(2018, 1, 1), date(2019, 12, 31)

    with Store(settings.duckdb_path) as store:
        ib = LateIPOIB(ipo=date(2019, 6, 3))
        monkeypatch.setattr(ib_source, "connect", _fake_connect(ib))
        asyncio.run(cli._backfill(settings, store, ["LATE"], start, end, "SMART", "USD"))
        assert store.coverage("LATE")[0] == date(2019, 6, 3)
        assert store.fetched_ranges("LATE") == [(start, end)]

        rerun = ConnectedFakeIB()
        monkeypatch.setattr(ib_source, "connect", _fake_connect(rerun))
        summary = asyncio.run(cli._backfill(settings, store, ["LATE"], start, end, "SMART", "USD"))

        assert summary["covered"] == ["LATE"]
        assert rerun.requests == []  # the pre-IPO window is not asked for again


async def _no_sleep(*args, **kwargs):
    return None
