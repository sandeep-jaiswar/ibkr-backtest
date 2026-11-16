# ibkr-backtest

Backtest equity strategies on Interactive Brokers daily history. Bars are stored in DuckDB, and every run is logged to MLflow with its parameters, metrics, equity curve and trade list.

The project is **read-only**. It requests historical data from TWS or IB Gateway and never places orders.

```
IB (TWS / Gateway) ──ib_async──▶ fetch ──▶ DuckDB (bars)
                                             │
                  strategy ──signal──▶ engine ◀┘
                                             │
                     metrics ──▶ DuckDB (runs, trades, equity) + MLflow (params, metrics, artifacts)
```

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Connecting to Interactive Brokers

1. Run TWS or IB Gateway and log in. Use paper trading while you are testing.
2. Enable API access: *File → Global Configuration → API → Settings* → tick **Enable ActiveX and Socket Clients**. Leave **Read-Only API** on, as this project only reads.
3. Check the socket port:

| App           | Paper | Live |
|---------------|-------|------|
| TWS           | 7497  | 7496 |
| IB Gateway    | 4002  | 4001 |

Historical stock data usually needs a market data subscription for the exchange, and IB enforces request pacing limits, which the fetcher respects.

Settings are read from environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `IBKR_HOST` | `127.0.0.1` | TWS / Gateway host |
| `IBKR_PORT` | `7497` | Socket port (see table) |
| `IBKR_CLIENT_ID` | `17` | API client id; must be unique per connection |
| `IBBT_DUCKDB` | `data/market.duckdb` | DuckDB file |
| `MLFLOW_TRACKING_URI` | `sqlite:///mlflow.db` | MLflow backend |
| `IBBT_MLFLOW_EXPERIMENT` | `ibkr-backtests` | MLflow experiment name |

## Usage

```bash
# Offline smoke test on synthetic data, no IB connection needed
ibbt demo

# 1. Download daily bars (only the missing date ranges are requested)
ibbt fetch AAPL MSFT --start 2015-01-01

# 2. Run one backtest
ibbt backtest AAPL --strategy sma_crossover --param fast=20 --param slow=100 --start 2015-01-01

# 3. Grid-search parameters. Each combination is an MLflow child run under one parent.
ibbt sweep AAPL --strategy sma_crossover --grid fast=10,20,50 --grid slow=100,200

# 4. Walk-forward: pick parameters on a train window, score on the next test window
ibbt walk-forward AAPL --grid fast=10,20,50 --grid slow=100,200 --folds 3 --train-years 3 --test-years 1

# 5. Check stored data for gaps and bad bars
ibbt check AAPL MSFT

# 6. Self-contained HTML tear sheet for a run
ibbt report <run_id> --out reports/run.html

# 7. Inspect stored runs
ibbt runs

# MLflow UI
mlflow ui --backend-store-uri sqlite:///mlflow.db
```

Costs are set with `--cash`, `--commission-bps` (default 5) and `--slippage-bps` (default 5). `--position-fraction` (0 to 1] sets how much cash is deployed on entry.

### Querying DuckDB directly

Open the file with the DuckDB CLI or the Python client:

```sql
SELECT run_id, symbol, strategy, params, metrics
FROM backtest_runs
ORDER BY created_at DESC;

SELECT * FROM trades WHERE run_id = '<run_id>' ORDER BY entry_date;
```

## How backtests work

- **No look-ahead.** A signal computed from bar *t*'s close becomes an order that fills at bar *t+1*'s open. Strategies must only use data up to their own bar. A test enforces this for the SMA strategy.
- **Costs.** Commission is charged on notional on each side, and slippage moves each fill against the trader.
- **Long/flat only.** Each strategy goes long or flat. Entries deploy `--position-fraction` of cash, and the rest stays idle.
- **Benchmark.** Every run also reports buy-and-hold total return and CAGR on the same dates and costs.
- **Strategies.** `sma_crossover` and `donchian_breakout` (entry above the prior high, exit below the prior low).
- **Metrics.** Total return, CAGR, annualised volatility, Sharpe (risk-free rate 0, 252 periods), max drawdown, Calmar, time in market, round trips, win rate and average trade P&L.

### Known limitations

- **Survivorship bias.** Symbols are whatever you fetch. Delisted names are not included unless you add them.
- **Adjustments.** IB's `TRADES` bars are used. Verify corporate-action handling before drawing conclusions about dividend-heavy names.
- **Daily bars only.** Intraday strategies need a different bar size and a different engine assumption.
- **Stale store.** `fetch` fills gaps at the edges of stored data. It does not revisit history, so after a corporate action re-fetch with a new DuckDB file.

## Adding a strategy

Subclass `Strategy` in `src/ibbt/strategies.py`, implement `signal(bars) -> pd.Series` returning 0/1, and register it in `REGISTRY`. Add a test that checks it does not look ahead.

## Layout

```
src/ibbt/
  cli.py         command-line entry point
  ib_source.py   read-only IB connection and historical bar download
  store.py       DuckDB schema and persistence
  strategies.py  strategy base class and built-ins
  engine.py      next-open fill simulator with costs
  metrics.py     performance statistics
  tracking.py    MLflow logging
  runner.py      run → log → persist pipeline
  synthetic.py   deterministic test data
tests/           engine, strategy, and store tests (no IB required)
```
