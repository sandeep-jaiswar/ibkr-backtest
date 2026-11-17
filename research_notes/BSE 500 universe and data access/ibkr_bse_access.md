# IBKR access to BSE-listed equities for daily OHLCV

Research date: 2026-11-17. Official IBKR contract, subscription, and India-pricing pages returned HTTP 403 to our fetch tool, so most "official" claims below come from search snippets or a mirror of the IBKR TWS API docs. Each claim is tagged as VERIFIED (fetched text), SNIPPET (seen only in search results, not fetched), INFERRED, or UNKNOWN.

Bottom line up front: we could not confirm that IBKR offers BSE equities through the API at all. One undated IBKR knowledge-base snippet says IBKR does not currently offer BSE trading. Before building a BSE pipeline on IB, someone must check Contract Search in TWS or Client Portal for a BSE stock and confirm a conId, exchange, and historical-data permission.

## What is needed to request BSE daily bars

### Exchange code, primaryExchange, currency

- Currency: INR. Basis: BSE is an INR exchange (SNIPPET: [Twelve Data exchange listing](https://support.twelvedata.com/en/articles/5070666-bombay-stock-exchange-bse)). IB's own currency for BSE contracts is UNKNOWN.
- Exchange code: UNKNOWN. Candidates are `BSE` (most plausible, INFERRED) and `BOMBAY`. No source confirmed either. The only IB-style Indian exchange code seen in sources is `NSE`, used in an old `ib` package gist and in R IBrokers threads (SNIPPET: [gist](https://gist.github.com/deependersingla/40722a6192ef785d30791abc8e5470ba), [R-SIG-Finance thread](https://r-mailing-lists.thecoatlessprofessor.com/lists/r-sig-finance/msg/msg-75f453a15cfc/raw)). These are old and not for BSE.
- primaryExchange: UNKNOWN. Must be read from `reqContractDetails` output for a real BSE contract.

### Symbol and identification

- IB's contracts page (SNIPPET, not fetched) recommends identifying a contract by conId plus exchange rather than by symbol and currency, and says conIds are static. Minimum fields are either conId + exchange, or symbol + secType + exchange + primaryExchange + currency (SNIPPET: [IBKR campus contracts](https://www.interactivebrokers.com/campus/ibkr-api-page/contracts/), [contract details docs](https://www.interactivebrokers.com/docs/tws-api/doc/contracts-financial-instruments/contract-details)).
- Whether BSE stocks are keyed by numeric scrip code, NSE-style ticker, or ISIN in IB's symbol field: UNKNOWN. No source found. Test with `reqMatchingSymbols` or Contract Search and record what IB returns.
- ib_async pattern: `Stock(symbol, 'BSE', 'INR')` then `reqContractDetails` (INFERRED from the ib_async README pattern `Stock('AAPL','SMART','USD')` (SNIPPET: [ib_async repo](https://github.com/ib-api-reloaded/ib_async)) and from NSE examples). Not verified for BSE.

### Market data subscriptions and fees

- IBKR's delayed-data table lists "National Stock Exchange of India" with a 15-minute delay and a separate real-time subscription named "National Stock Exchange of India, Capital Market Segment" (SNIPPET, from IBKR market-data pricing search result). No BSE entry was seen in any snippet. Fee amounts: UNKNOWN (pricing pages returned 403).
- Free delayed data: some exchanges allow delayed data without a subscription (SNIPPET, IBKR market-data pages). Whether that applies to any Indian exchange: UNKNOWN.
- Account minimum for market data: USD 100 or equivalent for India accounts, and subscriptions take effect the next business day (SNIPPET, IBKR market data minimum-balance page).
- Historical bars normally need the same subscription as live data for the instrument (SNIPPET, forum/IB discussion). For BSE: UNKNOWN until checked in TWS.

### Historical-data depth and pacing (VERIFIED from fetched IBKR TWS API docs mirror at interactivebrokers.github.io/tws-api/historical_limitations.html)

- Bar sizes of 30 seconds or less older than six months are unavailable.
- Hard limits for bars of 1 minute and above are lifted, but IB applies soft throttling for large or frequent requests. Cancel slow requests with `cancelHistoricalData`.
- Max 50 historical requests open at once.
- Identical requests must not repeat within 15 seconds.
- Small-bar pacing: no more than 6 requests for the same contract, exchange and tick type within 2 seconds, and no more than 60 requests in any 10-minute period. These apply to small bars only.
- Step-size table: duration 1 D allows bar sizes 1 min to 1 day; duration 1 Y allows bar sizes 1 day to 1 month. A daily-bar request with duration 1 Y is therefore allowed by the table.
- No separate "max duration per bar size" table was found. Maximum history depth for Indian stocks (for example, how many years of daily bars BSE gives): UNKNOWN. Test it directly in TWS or with `reqHistoricalData` and record the earliest bar.
- SNIPPET: IB says `reqHeadTimestamp` counts as a historical request under pacing rules. A late-2024 forum report says IB added head-timestamp pacing restrictions (anecdotal, forum).

### Adjustments for bonus issues and splits

- VERIFIED from IB spec quoted in a QuantConnect forum post: TRADES bars are split-adjusted but not dividend-adjusted (SNIPPET-quoted: [QuantConnect thread](https://www.quantconnect.com/forum/discussion/9252/inconsistency-between-backtest-historical-data-and-and-live-historical-data-over-stock-split-events-for-raw-datanormalizationmode/)).
- SNIPPET: `ADJUSTED_LAST` is adjusted for splits and dividends ([IB historical bars docs](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars)).
- Bonus issues: NOT documented in any source found. Treat as UNKNOWN. Validate by comparing IB bars with BSE corporate-action records around known bonus dates.
- Community reports conflict: one user says dividends were not reflected for SPY; another says the latest dividend was missed for some large caps (anecdotal, Wilmott forum). Do not rely on IB adjustments without a reconciliation step.

### Residency and account restrictions

- IB India accounts exist, and IB treats an Indian resident as someone living in India more than 182 days a year (SNIPPET, IBKR India pages).
- NRI accounts need Indian bank accounts such as NRO (SNIPPET, IBKR NRI application page).
- IB's India product status is contradictory: a 2009 press release says NSE stock trading was added for residents and NRIs (OLD, [Finextra](https://www.finextra.com/pressarticle/28410/interactive-brokers-adds-indian-stock-trading)); an undated IBKR FAQ says stock trading is not yet available; an undated IBKR KB snippet says BSE trading is not offered. The current status is UNKNOWN.
- Trading permission requirement for India: UNKNOWN. Check the India account application and Client Portal for permissions.

## Key questions answered

1. Exchange code / primaryExchange / currency: currency INR (INFERRED from exchange). Exchange and primaryExchange for BSE: UNKNOWN. `NSE` is the only Indian code seen in sources.
2. Identification: conId + exchange is IB's recommended approach (SNIPPET). Scrip code vs symbol vs ISIN for BSE: UNKNOWN.
3. Subscriptions and fees: NSE has a separate 15-minute-delayed and real-time subscription (SNIPPET). BSE: UNKNOWN. Historical daily bars without real-time subscription: UNKNOWN for India.
4. Depth and pacing: pacing rules VERIFIED above. Depth for Indian daily bars: UNKNOWN.
5. Restrictions: conflicting, see above.
6. Adjustments: TRADES split-adjusted, not dividend-adjusted (VERIFIED via quoted spec); bonus adjustments: UNKNOWN.

## Must check in TWS or Client Portal (we cannot log in)

1. Contract Search for a known BSE stock (for example a Sensex constituent). Record the exchange, primaryExchange, currency, conId, and local symbol.
2. Whether BSE appears as a tradable/data exchange for the account, or only NSE.
3. Market data subscriptions page for India: list the exact name, price, and whether BSE has its own entry.
4. Historical data for a BSE contract: request 1 Y of 1-day bars and record the earliest available bar.
5. Account eligibility: residency status and any India-specific permissions.
6. Bonus and split handling: compare IB daily closes with BSE corporate actions for at least one bonus event.

## Gaps

- Official IBKR pages on contracts, India exchanges, market data pricing, and India fees were not readable (HTTP 403). Re-check them manually.
- No ib_async or ibapi GitHub issue about BSE contracts was found.
- No forum post from a user who fetched BSE daily bars through IB was found.
- Bonus-issue adjustment policy is undocumented in what we found.

## Sources

- [IBKR TWS API historical limitations (mirror)](https://interactivebrokers.github.io/tws-api/historical_limitations.html) - VERIFIED (fetched)
- [IBKR TWS API historical data limitations](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-historical/historical-data-limitations/introduction) - 403, not read
- [IBKR campus: contracts](https://www.interactivebrokers.com/campus/ibkr-api-page/contracts/) - 403, search snippet only
- [IBKR India exchange fees](https://www.interactivebrokers.co.uk/en/accounts/fees/indiaStockExchangeFees.php?nhf=T) - 403, not read
- [QuantConnect forum quoting IB spec on TRADES adjustment](https://www.quantconnect.com/forum/discussion/9252/inconsistency-between-backtest-historical-data-and-and-live-historical-data-over-stock-split-events-for-raw-datanormalizationmode/) - quoted spec, secondary
- [IBKR historical bars (adjusted types)](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars) - search snippet
- [ib_async repository](https://github.com/ib-api-reloaded/ib_async) - search snippet
- [Finextra: IB adds Indian stock trading (2009)](https://www.finextra.com/pressarticle/28410/interactive-brokers-adds-indian-stock-trading) - old, fetch failed (403)
- [MotiveWave Indian market connections](https://docs.motivewave.com/knowledge-base/connection/indian-market-connections) - lists IB as a BSE/NSE connection, no detail
