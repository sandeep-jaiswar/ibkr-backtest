# BSE-listed Equities: Trading Rules, Transaction Costs and Corporate-Action Data Issues (for a daily-bar long-only backtest)

Research date: 2026-11-17. Scope: rules and costs for BSE cash equities (delivery and intraday). Source quality is marked **[primary]** (SEBI/exchange document opened in this research), **[broker]** (broker's own published schedule), or **[secondary]** (explainer, news, forum or search-summary; the page was not always opened). Items I could not verify are in each section's Gaps.

---

## 1. Round-trip transaction costs (delivery and intraday)

### Takeaway
A BSE delivery round trip costs about **0.22% of traded value** (22 bps) in statutory charges, driven by 0.1% STT on both sides, before brokerage, DP charges and slippage. Intraday statutory costs are about 0.04% round trip, so brokerage and slippage dominate there. The BSE exchange transaction charge of 0.00375% is consistent across the sources that quote BSE. The stamp duty rate (0.015% vs an older 0.01%) and the exact IBKR India brokerage were not verified.

### Cited Findings
- Zerodha published schedule (opened; no effective date shown, copyright "2010-2026"): delivery brokerage ₹0; STT 0.1% on buy and sell; exchange charge **BSE 0.00375%** (NSE 0.00307%); SEBI ₹10 per crore; stamp 0.015% on buy side; GST 18% on (brokerage + SEBI + exchange charge); DP charge ₹15.34 per scrip per delivery sell. — [Zerodha charges](https://zerodha.com/charges) [broker]
- Zerodha intraday: brokerage 0.03% or ₹20 per executed order, whichever is lower; STT 0.025% on sell side; exchange charge 0.00375% (BSE); stamp 0.003% on buy side. — [Zerodha charges](https://zerodha.com/charges) [broker]
- BSE exchange charge 0.00375% is also quoted by HDFC Sky and Tradejini (BSE delivery). — [HDFC Sky](https://hdfcsky.com/pricing/other-trading-charges), [Tradejini](https://tradejini.com/charges) [broker]
- A news report of the revised BSE equity cash rate gives ₹3.75 per lakh (= 0.00375%), reported for groups A, B and other non-exclusive scrips. — [Secondary summary of BSE revision, Oct 2024](https://www.freepressjournal.in/amp/business/bse-and-nse-revamp-transaction-fees-here-are-the-key-changes-starting-october-1-that-will-impact-your-trading-costs) [secondary]
- Stamp duty on delivery buys: 0.015% per Zerodha and Angel One's current list. An older Angel One list shows 0.01%. — [Angel One list of charges PDF](https://mfd.angelbroking.com/Assets/PDF/List_of_Charges.pdf) [broker, older]
- SEBI uniform-fee circular of 1 July 2024 replaced volume-slab exchange charges with a uniform structure; BSE revised its charges effective 1 Oct 2024. — [Business Standard](https://www.business-standard.com/amp/markets/news/sebi-uniform-charge-rule-bse-fee-structure-concerns-125060901141_1.html) [secondary]
- June 2025 Business Standard report: brokers allege BSE still applies volume-linked differential charges by scrip group. BSE disputes this; SEBI had not responded at the time. — [Business Standard](https://www.business-standard.com/amp/markets/news/sebi-uniform-charge-rule-bse-fee-structure-concerns-125060901141_1.html) [secondary]
- IBKR India: IBKR's India fee page lists an NSE cash delivery exchange charge of about 0.00297% and stamp 0.003% on intraday buys. BSE was not in the results. A Finextra release (undated) quotes an IBKR NSE commission of 5 bps with a ₹75 minimum. — [IBKR India fees](https://www.interactivebrokers.com.sg/en/accounts/fees/indiaStockExchangeFees.php) [broker, regional page, rate differs from Zerodha]; [Finextra](https://www.finextra.com/pressarticle/28410/interactive-brokers-adds-indian-stock-trading) [secondary, undated]

### Inferences (my arithmetic on the Zerodha schedule, BSE exchange rate 0.00375%)

Delivery, per ₹100 traded (excludes brokerage, DP, slippage):
- Buy: STT 0.10 + stamp 0.015 + exchange 0.00375 + SEBI 0.0001 + GST on (exchange+SEBI) 0.00069 ≈ **0.1195%**
- Sell: STT 0.10 + exchange 0.00375 + SEBI 0.0001 + GST 0.00069 ≈ **0.1045%**
- **Round trip ≈ 0.224% (22.4 bps)**, plus ₹15.34 DP per delivery sell per scrip.
- The stamp rate choice (0.01% vs 0.015%) moves the round trip by about 0.005 percentage points. Brokerage at IBKR is not included; if IBKR charges a percentage (5 bps per the undated Finextra figure), add that per side.

Round-trip cost for the two holding patterns:
- **Next-day exit (enter at day t close, exit at day t+1 close) is a delivery trade on both sides**, so the delivery figure above applies, and the sale settles T+1.
- **Same-day round trip is an intraday trade**: buy stamp 0.003% + exchange + SEBI + GST ≈ 0.0075%; sell STT 0.025% + exchange + SEBI + GST ≈ 0.0295%; total ≈ 0.037% plus brokerage. Brokerage at 0.03% binds below about ₹66,700 per order; above that the ₹20 cap binds.

For the cost model: about 0.22% round trip for delivery is material against typical daily-bar edges. Slippage on BSE mid and small caps is not in these sources and must be modelled separately.

### Gaps
- BSE's own current exchange-charge circular was not opened; 0.00375% comes from broker schedules and one news summary.
- Stamp duty on delivery: 0.015% is consistent across current broker pages; no Indian Stamp Act notification was retrieved.
- IBKR's India cash commission for BSE was not found. The 5 bps / ₹75 figure is undated.
- DP charge levels differ by depository and broker; ₹15.34 is Zerodha's only.

---

## 2. Settlement cycle (T+1) and implications for a daily breakout

### Takeaway
Cash equity settlement is T+1 (one business day after trade). Sale proceeds are credited T+1, so a model that recycles sale cash into a same-day buy is an assumption to test, not a rule I could confirm. Optional T+0 is limited to Qualified Stock Brokers (QSBs) and remains in a timeline-extension cycle: the SEBI circular of 30 Oct 2025 extended the QSB systems deadline again, with no new date.

### Cited Findings
- SEBI circular SEBI/HO/MRD2/DCAP/P/CIR/2021/628 (7 Sept 2021) allowed exchanges to offer T+1 as an option from 1 Jan 2022. — [Nishith Desai note](https://www.nishithdesai.com/default.aspx?id=4914) [secondary; circular number cited from this summary]
- Optional T+0 (beta) introduced by SEBI/HO/MRD/MRD-PoD-3/P/CIR/2024/20 (March 2024) and expanded by SEBI/HO/MRD/MRD-PoD-3/P/CIR/2024/172 (10 Dec 2024). — [NSDL circular PDF on beta T+0](https://nsdl.co.in/downloadables/pdf/2024-0038-Policy-SEBI_Circular_on_Introduction_of_Beta_version_of_T+0_rolling_settlement_cycle_on_optional_basis_in_Equity_Cash_Markets.pdf) [secondary-depository copy]
- **SEBI circular dated 30 Oct 2025 (opened, primary):** Subject "Further extension of timeline for mandatory implementation of systems and processes by QSBs with respect to T+0 settlement cycle." Para 2 quotes the 10 Dec 2024 circular's requirement that QSBs with the minimum active-client count as of 31 Dec 2024 put systems in place for optional T+0, effective 1 May 2025. Para 3 notes the 29 Apr 2025 circular (SEBI/HO/MRD/MRD-PoD-3/P/CIR/2025/58) extended the deadline to 1 Nov 2025. Para 4 extends it again with "further guidance ... at a later date." Para 5 leaves other provisions of the 10 Dec 2024 circular unchanged. — [SEBI circular PDF](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2025/1761825190101.pdf) [primary]
- NSE forwarded a SEBI T+0 circular for QSBs on 3 Nov 2025 (NSE/INSP/71103); the forwarded text was not opened. — [NSE circular PDF](https://nsearchives.nseindia.com/content/circulars/INSP71103.pdf) [primary link, text not opened]
- Margin collection in the cash segment aligned to T+1 by a SEBI circular of 28 Apr 2025. — [KS&K note](https://ksandk.com/corporate/t2-t1-sebi-new-margin-norms-and-market-impact/) [secondary]

### Inferences
- Answer for a breakout that "enters and exits daily": a next-day exit is delivery on both legs (T+1 settlement); a same-day exit is intraday (different STT, stamp and brokerage). A daily-bar model must pick one per trade and must not use intraday rates for next-day exits.
- A conservative backtest blocks reuse of sale proceeds until the next trading day. Whether brokers permit same-day use of unsettled proceeds was not verified; make this a configurable assumption.
- Optional T+0 is not available to a retail long-only daily strategy on general terms; it does not change the base case.

### Gaps
- The full-rollout T+1 date (January 2023) comes from one secondary summary, not a primary circular; not verified.
- The payout-timing circular (SEBI/HO/MRD/MRD-PoD-2/P/CIR/2024/137, Oct 2024) appears only in a search summary; not opened and not verified.
- The 3 Nov 2025 NSE forwarded circular text was not opened.
- Current status of optional T+0 after the 30 Oct 2025 extension (new deadline) is unknown.

---

## 3. Daily price bands (circuit limits)

### Takeaway
BSE securities without derivative products have fixed daily bands set as a percentage of the previous close. The maximum is 20%, and BSE and the exchanges reduce bands to 10%, 5% (and 1% or 2% in 2026 surveillance actions) as surveillance measures. Stocks with F&O products are treated differently, and I did not confirm their band rules. A stop placed below the lower limit cannot fill until the band resets, so the exit model needs a gap-fill assumption.

### Cited Findings
- BSE surveillance page: maximum price band 20%; exchanges revise bands to 10% and 5% as a surveillance action; securities without derivative products have fixed price bands based on the previous closing price. — [BSE surveillance page](https://bseindia.com/static/markets/equity/EQReports/sur_Surveillance.html) [primary; search excerpt only, not opened in full]
- Explainers state standard stock-level bands of 2%, 5%, 10%, 20% computed from the previous close. — [Rupeezy](https://support.rupeezy.in/support/solutions/articles/21000004845-what-are-circuit-limits-or-price-bands) [secondary]
- Aggregator reports of 2026 BSE surveillance revisions: circular effective 28 Apr 2026 (24 scrips, bands 2% to 20%); 19 May 2026 (29+ scrips, most to 5%); 18 May 2026 (35 scrips to 1/2/5/10%). — [rhnvrm circular mirror tag page](https://rhnvrm.github.io/stock-market-circulars/tags/price-band-revision/) [secondary mirror]
- BSE's Add-on Price Band Framework applies extra price restrictions to securities listed exclusively on BSE (37 securities per a secondary summary). — [search summary of BSE circular, not opened] [secondary]
- Index-level circuit breakers (Sensex, stages at 10/15/20%) halt all equity and derivative trading; separate from stock bands. — [search summary, source not opened] [secondary]

### Inferences
- Bands are per-scrip and time-varying. A backtest needs the band in force on each day; where unavailable, flag scrips that were on restricted bands.
- F&O constituents of the BSE 500 are not in the fixed-tier regime described by the surveillance page; their band treatment is a gap (see below).
- Stop trap: when a stock is at its lower limit, sells do not fill until the band resets. A stop below the lower limit should fill at the lower limit or at the next open that trades, with a record of the locked day. This exit assumption is my inference, not a sourced rule.
- Upper-circuit entry: if the day's close equals the upper limit, assume no buy fill for a breakout entry at that close. This is my inference and should be a backtest rule.
- Bands are computed from the previous close: limits = previous close × (1 ± band). Whether BSE uses the adjusted or unadjusted previous close after a corporate action is not verified.

### Gaps
- BSE's primary band-tier circulars were not opened; the mirror circular page returned HTTP 404.
- Band treatment for F&O-listed BSE stocks was not found; the BSE 500 includes such names.
- Mapping of ASM/GSM/ESM categories to bands 1/2/5/10/20% was not confirmed.
- No historical per-scrip band dataset was found.
- Zerodha Varsity circuit-limits page returned 404; no primary order-handling text was retrieved.

---

## 4. Short selling and fractional shares (long-only relevance)

### Takeaway
Naked short selling is prohibited in the Indian cash market, and deliveries must be honoured at settlement. A long-only strategy is not affected, but the model should not allow cash shorts. Overnight shorts are possible only via the SEBI Securities Lending and Borrowing (SLB) mechanism. Fractional shares of NSE/BSE-listed stocks are not available, so positions must be whole shares.

### Cited Findings
- Naked short selling prohibited in cash; delivery honoured at T+1; intraday shorts must be closed the same day with broker auto-squaring. — [onetradejournal](https://onetradejournal.com/glossary/short-selling) [secondary]
- Overnight shorts require borrowing through SLB with a lending fee. — [share.market](https://www.share.market/buzz/learn/short-selling/) [secondary]
- January 2024 SEBI short-selling framework: institutional investors barred from day trading; short sales disclosed upfront; brokers report scrip-wise short-sell data daily. — [Taxmann](https://taxmann.com/post/blog/sebi-strengthens-short-selling-norms-tightening-norms-particularly-for-institutional-investors) [secondary]
- SEBI consultation paper (Jan 2026) on short selling and SLB: text not readable in the tool. — [SEBI PDF](https://www.sebi.gov.in/sebi_data/commondocs/jan-2026/Consultation%20paper%20Annexure_A_p.pdf) [primary, not readable]
- Fractional trading of NSE/BSE shares not available; depositories accept whole-share holdings. Zerodha's SEBI sandbox application for fractional trading was rejected. — [Zerodha Z-Connect](https://zerodha.com/z-connect/rainmatter/is-fractional-share-investing-possible-in-india) [broker]; [Tickertape, updated Aug 2026](https://www.tickertape.in/blog/?p=18206) [secondary]
- Cash board lot is one share, except SME stocks. — [efghermes BSE market info](https://tg.efghermes.com/Market/GetById/2637) [secondary]

### Inferences
- Size positions in whole shares, rounding down; a fractional-share rule is needed for any percentage-weighted allocation.
- Short eligibility is irrelevant to this long-only model; a future long-short extension must check the current SLB-eligible list, which sources dispute.

### Gaps
- Current SLB-eligible list not retrieved.
- Outcome of the January 2026 SEBI consultation not confirmed.

---

## 5. Lot size and tick size (cash segment)

### Takeaway
Board lot in cash is one share (SME excluded). The minimum price increment is ₹0.01 for lower-priced stocks. The price cutoff for the ₹0.01 tier is disputed (₹100 in older summaries, ₹250 in later NSE and explainer coverage), and BSE's own threshold was not confirmed.

### Cited Findings
- Board lot one share in cash, except SME. — [efghermes](https://tg.efghermes.com/Market/GetById/2637) [secondary]
- NSE lowered tick size to ₹0.01 for stocks below ₹250 (May 2024). — [Business Standard](https://www.business-standard.com/markets/capital-market-news/nse-lowers-tick-size-for-stocks-below-rs-250-124052700731_1.html) [secondary]
- Explainer: revised tick bands effective 15 Apr 2025; BSE's lowest band also ₹0.01. — [Jainam](https://www.jainam.in/blog/what-is-tick-size/) [secondary]
- Older BSE-era summary: ₹0.01 for stocks below ₹100, ₹0.05 above; Zerodha's June 2024 note repeats ₹100. — [Geojit notifications](https://notifications.geojit.com/exchange-circulars/cash-segment) [secondary]; [Zerodha Z-Connect](https://zerodha.com/z-connect/?p=380462) [broker]

### Inferences
- Round prices to ₹0.01 for all stocks as a safe lower bound; for prices above the threshold, use ₹0.05 as a conservative assumption. Keep the threshold as a parameter.

### Gaps
- BSE's current tick-size circular and the exact threshold (₹100 vs ₹250) were not retrieved.

---

## 6. Corporate actions: how bonus, split and rights issues appear in price history

### Takeaway
Exchange price series are raw: a bonus or split appears as a discontinuity on the ex-date. Bonus and split adjustments follow a fixed formula. Rights issues have no fixed formula in the sources found. Whether BSE publishes back-adjusted series was not found, and vendors differ in what they adjust, so each data source needs a spot-check.

### Cited Findings
- SEBI educational deck: bonus adjustment factor = (A+B)/B; ₹15 share with 2:1 bonus gives factor 3 and ₹5 post-adjustment price. — [SEBI corporate-actions deck](https://investor.sebi.gov.in/pdf/reference-material/ppt/PPT-5%20Corporate%20Actions%20-%20Dividends,%20Bonus,%20Splits,%20etc_.pdf) [primary, educational]
- MSEI circular 17190 (May 2025) applies the same formula to BSE's 2:1 bonus: factor 3; derivatives strike divided by 3 and lot multiplied by 3. — [MSEI circular 17190](https://www.msei.in/SX-Content/Circulars/2025/May/Circular-17190.pdf) [exchange circular, primary]
- BSE's 2:1 bonus went ex on 23 May 2025; prior close ₹7,015 and open ₹2,358, reported as a mechanical adjustment. — [Business Today](https://www.businesstoday.in/markets/stocks/story/bse-shares-surge-7-as-stock-turns-ex-bonus-analysts-weigh-in-477481-2025-05-23) [secondary]
- Splits: price and face value scale in proportion; Zerodha example ₹900 at 1:2 split becomes ₹450 with twice the shares. Rights: issued below market price; the Zerodha article gives no adjustment formula. — [Zerodha Varsity](https://zerodha.com/varsity/chapter/five-corporate-actions-and-its-impact-on-stock-prices/) [broker educational, first 100k chars read]
- Kite (Zerodha) states its charts are adjusted for splits, bonuses, rights issues, spin-offs and extraordinary dividends, and therefore differ from raw exchange records. — [Zerodha support](https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/charts/articles/kite-charts-not-matching-as-per-the-records-in-nse-or-bse) [broker; search summary, article not opened]
- Vendor claims (not verified): Dhan says its daily historical data is adjusted for bonuses and splits; Freefincal reports Yahoo adjusts for splits and dividends but not bonuses, cautioning this may be outdated. — [Dhan](https://dhan.co/support/platforms/dhanhq-api/is-the-historical-data-from-dhan-s-data-api-adjusted-for-corporate-actions-like-bonuses-and-splits/) [vendor claim]; [Freefincal](https://freefincal.com/historical-stock-price-downloader/) [secondary]
- Practitioner report: yfinance mishandled the HDFCBANK demerger, distorting two years of backtest returns. — [TradingQnA forum](https://tradingqna.com/t/has-anyone-found-wrong-adjusted-prices-in-nse-historical-data-for-backtesting/192938) [anecdote]

### Inferences
- Ex-date price ratio = B/(A+B) for a bonus A:B. Examples: 1:1 bonus gives ~-50% on the ex-date; 2:1 gives -66.7%; 1:2 gives -33.3%. A raw series therefore produces false breakouts and false stop-outs at these points.
- Screen: flag any daily return within a small tolerance of these ratios on or near a known ex-date, and cross-check against the corporate-action file. Preferably adjust prices by the factors above.
- Rights issues need a theoretical ex-rights price adjustment (not in sources). Treat rights issues as a known gap and screen them separately.
- Use ex-date (not record date) as the adjustment date.
- Vendor adjustment coverage (splits, bonuses, rights, demergers, dividends, adjustment-history start) must be checked for the specific source used; the demerger anecdote shows that adjustments can be wrong.

### Gaps
- BSE's own corporate-action methodology and whether it publishes back-adjusted series: not found.
- Whether the project's price source back-adjusts splits and bonuses: not verified; check the vendor documentation or spot-check known events.
- Rounding of fractional entitlements (bonus, rights) on BSE: not found.
- Rights-issue adjustment formula: not found in any retrieved source.
