# NSE Execution Specifics for Daily Breakout Strategies (as of Nov 2026)

Source labels: **[P]** = primary (NSE/SEBI document or NSE's own page), **[S]** = secondary (broker, news, aggregator, or academic summary). Where I could not open the primary document, this is stated explicitly.

Verification status: NSE's equity-market-price-bands page fetch timed out. The April 2026 circular mirror returned 404. The Zerodha FAQ and the NSE LPP FAQ fetch also timed out or were not retrieved. Everything below marked [S] rests on secondary summaries of NSE circulars, not the circular text.

---

## Key question 1: Current NSE price band rules (2%, 5%, 10%, 20%) and which stocks have which band. Do F&O stocks have no bands?

### Takeaway
Non-F&O equities are assigned a periodic daily price band from a fixed set of categories, and NSE revises the assignments every few months. F&O stocks do not have a fixed daily circuit. They have a dynamic band or operating range of about 10% that flexes as price approaches it. Exact current counts per band could not be verified from NSE's own pages.

### Cited Findings
- NSE's own price-bands page lists daily bands of 2%, 5% and 10%, and states that no price bands apply to scrips on which derivative products are available — [P, per search snippet only; page fetch timed out](https://www.nseindia.com/products-services/equity-market-price-bands)
- NSE circular on the April 8, 2026 revision (Circular 250/2026 per secondary summary): 3,162 securities revised; 23 at 2%, 367 at 5%, 170 at 10%, 213 with no band — [S, aggregator summary](https://rhnvrm.github.io/stock-market-circulars/circulars/nse/2026/nse-2026-04-07-b7f93c9c96e0244b-changes-in-price-bands-from-april-08-2026) (page returned 404 when I tried to open it; figures come from the search snippet). Also reported by a search summary of the same circular set: [TeamLease RegTech](https://teamleaseregtech.com/updates/article/56591/nse-revises-price-bands-for-securities-from-june-05-2026/)
- June 5, 2026 revision (Circular 414/2026 per secondary summary): 42 at 2%, 565 at 5%, 177 at 10%, 211 with no band. NSE reportedly clarified that securities with derivative products keep a 10% daily operating range even when classified "no band" — [S](https://teamleaseregtech.com/updates/article/56591/nse-revises-price-bands-for-securities-from-june-05-2026/)
- February 5, 2026 revision: about 3,108 securities, bands reported as ranging from 2% to 40% — [S](https://rhnvrm.github.io/stock-market-circulars/circulars/nse/2026/nse-2026-02-04-db6bd23472481d0c-changes-in-price-bands-from-february-05-2026). **The 40% figure is unverified** and conflicts with the 2%–20% range stated by Zerodha, so treat the band set as not fully settled from these sources.
- Zerodha FAQ: circuit limits "range from 2% to 20%, depending on liquidity, volume, and category." It states F&O equities "don't have fixed circuit limits for the day" and instead have "a dynamic price band of 10%," with a 15-minute cooling period before new limits are added — [S](https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/what-does-circuit-limits-i-e-price-bands-mean). The FAQ gives no effective dates.
- Chittorgarh's circuit-filter list says no circuit filter is defined for F&O stocks. This conflicts with the 10% operating range in the NSE circular summaries; I weight the NSE-based sources more heavily — [S](https://www.chittorgarh.com/newportal/stock-nse-circuit-filters.asp)
- Dynamic band flexing (per Fyers and Zerodha summaries of the Nov 2024 / 2024 SEBI framework): when price approaches the band, the band is relaxed (reported as 15% and 20% steps in one summary). When bands flex in one direction the other side flexes by an equal amount. Pending orders with limit prices outside the flexed band are auto-cancelled; untriggered stop-loss orders are reportedly left alone — [S](https://fyers.in/notice-board/revised-dynamic-price-bands-and-fo-segment-rules/), [S](https://angelone.in/announcements/market/clarification-on-relaxing-the-dynamic-price-bands). **Exact flex steps not verified against the primary circular.**
- Limit Price Protection (LPP): NSE's FAQ describes LPP as a validation applied in addition to the operating price range (OPR). Example in the search snippet: OPR 50–150 with LPP 80–120, so a buy limit above 120 is rejected. LPP is flexed automatically when at least 10 orders are rejected for LPP between two LPP revision events — [P per NSE FAQ PDF, text from search snippet only; fetch timed out](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQs_on_Limit_Price_Protection.pdf)
- Pending regulatory change: a 5paisa report (April 2026) says SEBI is considering applying dynamic bands to any stock in F&O on any exchange, so NSE and BSE may differ today. Not settled — [S](https://www.5paisa.com/news/sebi-to-enforce-dynamic-price-bands-for-all-fo-stocks-equally-on-exchanges)
- ETF change (Circular 122/2026, per summary): ETFs move to dynamic bands with an initial ±10% (Gold/Silver ETFs ±6%), effective September 7, 2026. Relates to ETFs, not equities — [S](https://teamleaseregtech.com/updates/article/59215/nse-update-in-trading-parameters-for-etfs/)

### Inferences
- For a backtest, an F&O stock should be modelled with a ~10% dynamic band rather than "no limit." A non-F&O stock should use its assigned band, which can change at each revision, so band history must be point-in-time.
- The band is set off a reference price that is revised, so a historical band must be taken from the circular in force on that date, not the current list.
- The "no band" category includes F&O stocks, but the 10% operating range still applies to them, so "no band" does not mean unlimited movement.

### Gaps
- Could not open the NSE price-bands page or the April 2026 circular PDF (timeout / 404). Band counts above are from secondary summaries.
- The exact band set (whether 20% is currently used, and whether 40% exists) is unverified.
- The exact dynamic-band flex steps and the cooling-period rule were not confirmed from the primary circular.
- Point-in-time band history for the universe was not found in any source; this needs NSE archive access.

---

## Key question 2: When a stock hits its upper circuit, can a breakout entry fill? When a stock hits its lower circuit, can a stop fill?

### Takeaway
A stock at its upper circuit is typically one-sided: buy orders queue and sellers are scarce, so a breakout buy may not fill. A stop-sell in a stock at its lower circuit can fail to fill for the same reason. Orders placed outside the band are rejected, and orders at the band stay pending. This comes from broker explainers, not from NSE rule text.

### Cited Findings
- Orders outside the price band are rejected; orders that reach the band remain pending until the exchange relaxes the limits — [S, Zerodha FAQ](https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/what-does-circuit-limits-i-e-price-bands-mean)
- At the upper circuit, buy orders pile up while sellers are scarce; buying is effectively blocked when there are no sellers — [S, search summaries of broker pages (Mastertrust, Wright Research, Jainam)](https://mastertrust.co.in/blog/upper-circuit-and-lower-circuit-in-the-share-market-explained). I did not confirm the exact wording in Fyers' "What happens at the upper/lower circuits?" article, which is listed but was not opened: [S](https://support.fyers.in/portal/en/kb/articles/what-happens-to-buy-and-sell-orders-when-a-stock-hits-the-upper-or-lower-circuit)
- Stop-losses can fail to execute at a lower circuit when buyers are absent. A stop placed near the circuit can be skipped on a gap, and the stock then locks — [S, Kotak Securities support](https://www.kotaksecurities.com/support/how-is-it-possible-for-the-price-to-hit-the-market-but-the-stop-loss-sl-was-not-triggered) (page not opened in full; statement from search snippet)
- For F&O stocks, the relevant constraint is the operating range plus LPP. A buy limit above the LPP upper bound is rejected, and orders outside a flexed band can be cancelled — [P per NSE FAQ snippet / S](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQs_on_Limit_Price_Protection.pdf)

### Inferences
- Entry fill logic for breakouts: a buy-stop or buy-limit at a price at or above the circuit cannot fill until the band is relaxed or sellers appear. A backtest that assumes the bar's high was achieved at the breakout price overstates fills on locked days. Model these as "no fill" when the day's close equals the band price and the volume at the band is low.
- Stop-exit logic: on a lower-circuit day, a stop-sell may not fill at all for that day. A backtest should record the stop as unfilled, not fill it at the stop price or at the low.
- A stock that closes at a circuit has no real discovery of the next day's range from that bar. The next-bar open can be far from the prior close (gap through a stop), so gap-risk should be measured separately.
- Because these are inferences from broker explainers, they should be checked against NSE trade data for locked-band days (lots of zero-volume bars at the band price).

### Gaps
- No primary NSE document specifies fill rules at the circuit. The rules are inferred from order-validation behaviour described by brokers.
- Whether a buy-side fill is possible at the upper band in continuous trading (versus the pre-open or call-auction) was not confirmed in any source.
- Not verified: how often stops are skipped on NSE locked stocks. No dataset or study was found.

---

## Key question 3: Published studies of momentum or breakout strategies on NSE or BSE, and the profit factors / win rates reported

### Takeaway
I did not find any published study of daily breakout rules on NSE or BSE that reports a profit factor or win rate. The Indian momentum evidence is mostly for monthly portfolio momentum, not daily breakouts. The best-known US trading-rule study (Brock, Lakonishok and LeBaron, 1992) does not report profit factors. The direct comparison requested cannot be made from the sources available.

### Cited Findings
- Brock, Lakonishok and LeBaron (1992), Journal of Finance 47: 1731–1764. Tested moving-average and trading-range-break rules on the Dow Jones Index, 1897–1986. Reported buy-signal returns above sell-signal returns, and results not explained by random-walk, AR(1), GARCH-M and EGARCH nulls. No profit factor reported in the abstract or sources I saw — [Econpapers/RePEc listing](https://econpapers.repec.org/RePEc:bla:jfinan:v:47:y:1992:i:5:p:1731-64); [Santa Fe listing](https://www.santafe.edu/research/results/working-papers/simple-technical-trading-rules-and-the-stochastic-)
- Bessembinder and Chan (1998) argued the BLL profits would be largely offset by transaction costs — cited in [Bohrium abstract page](https://www.bohrium.com/paper-details/simple-technical-trading-rules-and-the-stochastic-properties-of-stock-returns/813313297775329282-10567) (secondary; original not opened)
- Indian momentum, monthly portfolios: a 2019 Capitalmind study found a 30-stock monthly momentum portfolio beat the Nifty and Nifty 500 from 2007, with higher volatility and deeper drawdowns. No profit factor — [S](https://www.capitalmind.in/insights/momentum-investing-basics-india)
- Indian momentum liquidity question: a 19-year NSE backtest of Nifty 200 Momentum 30, split by liquidity, asks whether the premium is a liquidity premium rather than momentum. Hypothetical educational backtest — [S](https://freefincal.com/is-indian-momentum-investing-just-a-liquidity-illusion/)
- Thuztra (June 2026), 10-year test: top-3 momentum beat the index; top-1 underperformed and failed a luck test (p = 0.711). Retail blog, not peer-reviewed — [S](https://thuztra.pages.dev/research/momentum-investing-india-honest-backtest)
- IMMR-H study (2015–2024, 77 Nifty 500 stocks): gross signal strong, transaction costs consumed most of the alpha; profit factor reportedly fell below 1.3 in recent years, attributed to implementation drag. **Self-published, survivorship bias acknowledged by the author only partially; profit-factor figure not verified** — [S](https://anirudh-vadrevu.github.io/Quant-Journals/IMMR-Hybrid.html)
- Breakout rules: only generic TradingView educational content found; no backtest results — [S](https://in.tradingview.com/chart/GOLD/qnrawb3p-Momentum-Trading/) (not verified in detail)

### Inferences
- The Indian evidence that exists points to diversified, low-turnover momentum with costs as the main drag. It does not support or refute concentrated daily breakout trading.
- Any profit factor or win-rate claim for NSE daily breakouts would have to come from our own backtest, with NSE-specific costs (STT, brokerage, impact) and band-aware fills.
- A US breakout result (e.g. BLL-style rules) cannot be directly compared to NSE without the same cost and fill model.

### Gaps
- No peer-reviewed NSE/BSE study of daily breakout or intraday momentum with reported profit factor or win rate was found.
- Did not find a study comparing NSE and US momentum/breakout effect sizes on a common basis.
- Survivorship and point-in-time index membership issues are unaddressed in the Indian sources found.

---

## Key question 4: Typical delivery vs intraday split, and whether delivery percentage matters for signal quality

### Takeaway
Market-wide delivery share is roughly 44% of volume in FY25 (Business Standard). Delivery percentage is a descriptive measure of how much volume is held overnight. I found no study linking delivery percentage to subsequent returns on NSE, so its value as a signal is unproven.

### Cited Findings
- Delivery-based trades were 44.1% of FY25 volume; the rest were squared off intraday. Market volatility strongly influences the split — [S, Business Standard](https://www.business-standard.com/amp/industry/news/delivery-based-trades-moderate-in-april-after-hitting-eight-year-high-125043000455_1.html)
- Delivery percentage rose in 2022 alongside new margin norms that moved activity from intraday cash to derivatives. A bullish market tends to lift delivery share — [S, Business Standard](https://www.business-standard.com/article/markets/delivery-percentage-improved-in-2022-amid-new-margin-norms-shows-data-123010800460_1.html)
- Intraday activity tends to rise in volatile, directionless markets; intraday trading is not allowed in many smaller stocks — [S, Magzter/Business Standard](https://www.magzter.com/en/stories/newspaper/Business-Standard/DELIVERYBASED-TRADES-COOL-OFF-IN-APRIL)
- Context on participants: SEBI's study of FY22 found 89% of individual equity F&O traders incurred losses (some outlets report 90%); only about 11% made a profit. A follow-up for FY22–FY24 reports 93% of individual traders lost money, with a combined loss of about ₹1.81 lakh crore. These are individual F&O traders, not breakout-signal evidence — [S, Outlook Business](https://www.outlookbusiness.com/news/90-individual-traders-incurred-net-losses-in-equity-f-o-trading-in-fy22-sebi-news-256796); [S, Business Today](https://www.businesstoday.in/markets/story/93-of-individual-traders-incurred-losses-in-equity-fo-during-fy22-fy24-sebi-study-447102-2024-09-23). The SEBI primary PDFs were not opened.

### Inferences
- Delivery % is partly a function of regulation (margin rules) and market regime, so it may proxy for regime more than for stock-level conviction. Any use as a filter should be tested with a regime control.
- A reasonable test: add delivery % (vs its own 20-day median) as a filter on breakout entries and compare hit rate and expectancy with and without it, with costs included.

### Gaps
- No academic study of NSE delivery percentage and subsequent returns was found.
- Delivery data for the universe (NSE bhavcopy, security-wise delivery) was not accessed; the file format and availability need checking.

---

## Date log of rule changes (as found; to be verified against NSE archive)
- Nov 2024: NSE dynamic price band relaxation levels (reported 15%/20%) — secondary
- Feb 5, 2026: periodic band revision (~3,108 securities) — secondary
- Apr 8, 2026: periodic band revision (3,162 securities; 213 no-band) — secondary
- Jun 5, 2026: periodic band revision (42 at 2%, 565 at 5%, 177 at 10%, 211 no-band) — secondary
- Apr 2026: SEBI consideration of uniform F&O dynamic bands across exchanges — secondary, not settled
- Sep 7, 2026: ETF dynamic band change (Circular 122/2026) — secondary

## Overall gaps and what to check next
1. Download the NSE price-band circulars (nsearchives.nseindia.com) for Feb, Apr and Jun 2026 and confirm the band counts and band set.
2. Obtain the 2024 SEBI dynamic-band circular and NSE's LPP FAQ text for exact flex and cooling-period rules.
3. Build point-in-time band history from the circulars for the universe.
4. Test fills on locked-band days using NSE trade/bhavcopy data before trusting any breakout backtest.
5. No published NSE/BSE breakout profit factors were found; produce these from our own backtest.
