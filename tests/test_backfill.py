"""Backfill runs symbols concurrently and re-runs must never duplicate rows."""

import asyncio
from contextlib import asynccontextmanager
from datetime import date

from ibbt import cli, ib_source
from ibbt.config import Settings
from ibbt.store import Store
from test_ib_source import FakeIB


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
        dups = store.con.execute("select count(*) from (select symbol, ts from bars group by 1,2 having count(*)>1)").fetchone()[0]

    assert sorted(first["stored"]) == symbols
    assert count_after_first > 0
    assert count_after_second == count_after_first
    assert dups == 0
    assert sorted(second["covered"]) == symbols
