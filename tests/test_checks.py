import argparse
from datetime import date

import pytest

from ibbt.checks import check_symbol, register
from ibbt.store import Store
from ibbt.synthetic import synthetic_bars


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "m.duckdb") as s:
        yield s


def _corrupt(store, symbol, ts, **values):
    sets = ", ".join(f"{k} = ?" for k in values)
    store.con.execute(f"UPDATE bars SET {sets} WHERE symbol = ? AND ts = ?", [*values.values(), symbol, ts])


def test_clean_series_reports_no_problems(store):
    bars = synthetic_bars("2022-01-03", "2022-03-31")
    store.upsert_bars("ABC", bars)

    report = check_symbol(store, "ABC", date(2022, 1, 3), date(2022, 3, 31))

    assert report["bars"] == len(bars)
    assert report["first"] == date(2022, 1, 3)
    assert report["last"] == date(2022, 3, 31)
    assert report["missing_business_days"] == 0
    assert report["high_below_low"] == 0
    assert report["close_outside_high_low"] == 0
    assert report["non_positive_prices"] == 0


def test_corrupted_rows_and_gaps_are_counted(store):
    bars = synthetic_bars("2022-01-03", "2022-03-31")
    store.upsert_bars("ABC", bars)
    day = lambda i: bars["ts"].iloc[i].date()  # noqa: E731

    _corrupt(store, "ABC", day(5), high=50.0, low=60.0)  # high < low, and close falls outside
    _corrupt(store, "ABC", day(10), close=float(bars["high"].iloc[10]) * 2)  # close above high
    _corrupt(store, "ABC", day(15), open=0.0)  # non-positive price
    store.con.execute("DELETE FROM bars WHERE symbol = 'ABC' AND ts = ?", [day(20)])  # one missing weekday

    report = check_symbol(store, "ABC", date(2022, 1, 3), date(2022, 3, 31))

    assert report["bars"] == len(bars) - 1
    assert report["missing_business_days"] == 1
    assert report["high_below_low"] == 1
    assert report["close_outside_high_low"] == 2
    assert report["non_positive_prices"] == 1


def test_range_limits_what_is_checked(store):
    bars = synthetic_bars("2022-01-03", "2022-03-31")
    store.upsert_bars("ABC", bars)
    _corrupt(store, "ABC", bars["ts"].iloc[5].date(), high=50.0, low=60.0)

    report = check_symbol(store, "ABC", date(2022, 2, 1), date(2022, 3, 31))

    assert report["high_below_low"] == 0
    assert report["first"] >= date(2022, 2, 1)


def test_unknown_symbol_is_all_missing(store):
    report = check_symbol(store, "NOPE", date(2022, 1, 3), date(2022, 1, 14))

    assert report["bars"] == 0
    assert report["first"] is None and report["last"] is None
    assert report["missing_business_days"] == 10


def test_inverted_range_is_rejected(store):
    with pytest.raises(ValueError):
        check_symbol(store, "ABC", date(2022, 2, 1), date(2022, 1, 1))


def _run_check(argv, db_path, monkeypatch):
    monkeypatch.setenv("IBBT_DUCKDB", str(db_path))
    parser = argparse.ArgumentParser()
    register(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(["check", *argv])
    return args.func(args)


def test_check_command_exit_codes(tmp_path, monkeypatch, capsys):
    db = tmp_path / "m.duckdb"
    with Store(db) as store:
        store.upsert_bars("GOOD", synthetic_bars("2022-01-03", "2022-03-31"))
        store.upsert_bars("BAD", synthetic_bars("2022-01-03", "2022-03-31", seed=2))
        _corrupt(store, "BAD", date(2022, 2, 1), open=-1.0)

    args = ["GOOD", "--start", "2022-01-03", "--end", "2022-03-31"]
    assert _run_check(args, db, monkeypatch) == 0
    assert "GOOD" in capsys.readouterr().out

    assert _run_check(["GOOD", "BAD", "--start", "2022-01-03", "--end", "2022-03-31"], db, monkeypatch) == 1
    out = capsys.readouterr().out
    assert "BAD" in out and "non_positive_prices=1" in out


def test_check_command_reports_missing_database(tmp_path, monkeypatch, capsys):
    assert _run_check(["ABC"], tmp_path / "absent.duckdb", monkeypatch) == 2
    assert "no database" in capsys.readouterr().err
