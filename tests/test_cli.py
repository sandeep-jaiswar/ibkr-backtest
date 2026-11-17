"""CLI parsing and error handling. No IB connection or MLflow server is needed."""

from ibbt import cli
from ibbt.store import Store
from ibbt.synthetic import synthetic_bars


def test_search_accepts_cost_flags_with_defaults():
    parser = cli.build_parser()

    args = parser.parse_args(["search"])
    assert (args.commission_bps, args.slippage_bps) == (5.0, 5.0)

    args = parser.parse_args(["search", "--commission-bps", "1.5", "--slippage-bps", "2"])
    assert (args.commission_bps, args.slippage_bps) == (1.5, 2.0)


def test_portfolio_holdout_force_flag_defaults_off():
    parser = cli.build_parser()
    assert parser.parse_args(["portfolio-holdout"]).force is False
    assert parser.parse_args(["portfolio-holdout", "--force"]).force is True


def test_backtest_with_bad_param_exits_1_with_error_on_stderr(tmp_path, monkeypatch, capsys):
    db = tmp_path / "cli.duckdb"
    monkeypatch.setenv("IBBT_DUCKDB", str(db))
    with Store(db) as store:
        store.upsert_bars("AAA", synthetic_bars("2022-01-03", "2022-06-30"))

    code = cli.main(
        ["backtest", "AAA", "--param", "bogus=1", "--no-track", "--start", "2022-01-03", "--end", "2022-06-30"]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("error: ")
    assert "bogus" in captured.err


def test_main_reports_bad_key_value_argument(capsys):
    code = cli.main(["backtest", "AAA", "--param", "no-equals-sign", "--no-track"])
    assert code == 1
    assert "expected KEY=VALUE" in capsys.readouterr().err
