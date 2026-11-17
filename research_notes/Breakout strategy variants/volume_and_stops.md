# Volume Confirmation and Stop-Loss Design for Daily-Bar Breakouts

Scope: rules computable from daily OHLCV. Where a rule needs intraday or delivery data, it is flagged. Evidence quality is labelled as VERIFIED (primary or directly read source), SECONDARY (a summary or vendor page), or UNVERIFIED (search snippet or forum claim only). Most published numbers below are vendor, blog, or forum claims with no reproducible methodology. No study found reports a clean head-to-head of ATR stops vs swing-low stops on daily breakouts.

## (a) Volume-ratio confirmation thresholds: what is reported

### Takeaway
Thresholds of 1.5x and 2x the 20-day average volume are the common practitioner choices. The one quantitative hit-rate figure found says volume alone is a weak standalone filter, and a second source says volume ratio does not predict outcome. No credible study measured the effect of a volume ratio on hit rate or average win.

### Cited Findings
- Volume of at least 1.5x the 20-period average is used as a breakout filter, with some traders using 2x — [Forex Tester](https://forextester.com/blog/breakout-trading-strategy/) (SECONDARY; taken from a search snippet, not fetched; no hit-rate data given)
- A site uses 120% of the 20-bar average as a confirmation filter and says it improves confirmation; no hit rate given — [The Right Trader](https://therighttrader.com/learn/trend-analysis/breakout-volume) (UNVERIFIED, search snippet only)
- Vendor backtest, 14 years (2012–2025), 3,489 screening dates: standalone breakout volume (volume on signal date above a minimum multiple of its 20-day average) shows 44% "consistency" at a 1-year hold, below the vendor's 55% "useful" threshold. The vendor says the signal was useful only in combination with other signals. Market: not stated in snippet, presumably Indian or global; period 2012–2025 — [JumpStartSignal](https://jumpstartsignal.pages.dev/signals/breakout-volume/) (SECONDARY; vendor, methodology not verified; "consistency" is not a win rate)
- Volume ratio and reward-to-risk ratio are said not to predict the outcome of a breakout trade. No data given — [LuxAlgo](https://www.luxalgo.com/blog/how-volume-confirms-breakouts-in-trading/) (UNVERIFIED, claim without data)
- A trader's own breakout setups run at 30–45% win rate across several markets and years. One earlier version showed 60% win rate, which the author traced to a backtest bug (entry at a price that no longer existed after a delayed confirmation). Market and period: "all my markets and years," not specified — [MQL5 blog](https://www.mql5.com/en/blogs/post/776238) (UNVERIFIED, single-author account)
- Blume, Easley and O'Hara (1994) argue that volume carries information about the quality of the information behind a price move, and that traders who use volume information do better than those who ignore it. This is a theoretical equilibrium model, not a breakout backtest. Market: US, theoretical — [Journal of Finance 1994 (IDEAS/RePEc)](https://ideas.repec.org/a/bla/jfinan/v49y1994i1p153-81.html) (VERIFIED as to the paper's existence and main claim via abstract; the full text is paywalled)
- Lo, Mamaysky and Wang (2000) test pattern recognition on US stocks, 1962–1996. A secondary CXO summary says volume trends affect the significance of abnormal returns for a few patterns. The volume-specific result could not be read in the abstract — [MIT abstract](https://web.mit.edu/~alo/www/Papers/techanal.html) and [CXO summary](https://www.cxoadvisory.com/?p=987) (VERIFIED for the study's scope; the volume result is SECONDARY and unverified in detail)

### Inferences
- The volume-ratio threshold is not established as a profit driver by any source found. Treat 1.5x and 2x as parameters to sweep, not as known-good values.
- A threshold above 1.0 mainly reduces trade count. Whether it raises average win is an empirical question for your own data.
- Ratio should be computed against the prior 20 bars excluding the breakout bar, to avoid self-inclusion bias. This is a methodological recommendation, not a sourced finding.

### Gaps
- No primary study with reported hit rate and average win by volume-ratio bucket on daily equity breakouts was found.
- Market and period of the vendor 44% figure are not clear from the snippet.

## (b) ATR stops vs swing-low stops on daily breakouts

### Takeaway
ATR-based trailing stops are well documented as a trend-following exit, with Chandelier (22-day high minus 3 x ATR(22)) the most standard form. No source gives a comparable win rate and profit factor for ATR(14) at 2x-3x against swing-low stops on daily breakouts. The one ATR-stop backtest with numbers is single-source and uses unknown parameters.

### Cited Findings
- Chandelier Exit, attributed to Charles Le Beau: long stop = highest high (22 bars) minus 3 x ATR(22). Common defaults are 22 periods and 3x; sources give a multiplier range of 2.5–3.5 — [The Right Trader](https://therighttrader.com/learn/indicators/chandelier-exit) (SECONDARY). Several sources say the exit is triggered on a close below the line, not on an intraday touch — same source (SECONDARY). Le Beau's original trade stop uses the highest high since entry, while the plotted line uses a rolling 22-bar high — same source (SECONDARY)
- Liberated Stock Trader backtest of an ATR trailing stop: win rate 43%, average profit 8.5%, average loss -4.8%, profit factor about 1.34, 1,205 positions, Dow Jones 30 stocks. Period and ATR parameters not confirmed. Arithmetic checks: 0.43 x 8.5 / (0.57 x 4.8) = 1.34 — [Liberated Stock Trader](https://www.liberatedstocktrader.com/atr-indicator/) (SECONDARY; no methodology)
- Zarattini, Pagani and Wilcox (2025), "Does Trend-Following Still Work on Stocks?": entry on new all-time highs, trailing ATR stop updated daily and never lowered. Reported (via blog summary): 75+ years of US stock data, more than 66,000 trades, CAGR 15.02%, max drawdown 31.75%, and fewer than 7% of trades drive cumulative profit. The ATR multiple, win rate and profit factor are not given in the summary — [Harbourfront Quant summary](https://harbourfrontquant.substack.com/p/does-trend-following-still-work-on) (SECONDARY; the paper is SSRN 5084316 and was not read directly)
- Oxford Strategies R&D: a Wilder volatility breakout system on 42 futures, 1980–2013, using ATR(20) with a stop multiple of 6. Win rate and profit factor are reported in the post but the figures were not captured — [Oxford Strategies](https://oxfordstrat.com/?p=10080) (SECONDARY; not fetched; the parameters differ from ATR(14) 2x-3x)
- A search for a Zarattini–Aziz volatility-stop paper with win rate and profit factor found no matching study (UNVERIFIED search result)

### Inferences
- The trailing-stop literature (Zarattini et al.) reports that very few trades drive returns, so a trend-following exit is evaluated mainly on payoff distribution, not win rate. This suggests reporting expectancy in R and average win/loss alongside win rate.
- A structure (swing-low) stop has a width that varies per trade, so position size should be set from the actual stop distance (shares = risk per trade / (entry minus stop)). An ATR stop gives a width that scales with volatility, so the same risk unit produces comparable position sizes across stocks.
- Initial stops at 2x-3x ATR(14) are wider than many swing-low stops on quiet stocks and narrower on volatile ones. Expect the ATR stop to change the mix of which trades are stopped out, not only the average stop size. This is reasoning, not a sourced result.

### Gaps
- No head-to-head study of ATR(14) 2x-3x vs swing-low stops on daily breakouts with win rate and profit factor was found.
- The Zarattini et al. 2025 ATR multiple and trade statistics need the full paper (SSRN 5084316).

## (c) Wide vs tight stops: win rate vs profit factor

### Takeaway
No source found measures the trade-off between stop width and win rate or profit factor for daily breakouts. The only quantitative evidence is the single ATR-stop backtest above. The direction of the effect is a theoretical argument, not an empirical finding.

### Cited Findings
- The Liberated Stock Trader backtest reports a win rate of 43% with a profit factor of about 1.34 for one ATR trailing-stop setup (see section b). No comparison across stop widths is given — [Liberated Stock Trader](https://www.liberatedstocktrader.com/atr-indicator/) (SECONDARY)
- Trend-following exits are described as winning less than half the time, with expectancy in R the main metric — [Apex Edge indicator description on TradingView](https://www.tradingview.com/script/TwknQln9-Apex-Edge-Trend-Breakout/) (UNVERIFIED; vendor script description)

### Inferences
- Mechanically, a wider stop reduces the frequency of stop-outs, which tends to raise win rate on a fixed-target design. It also raises loss size per trade, which lowers average win/loss and can lower profit factor. A tighter stop does the reverse. Whether the net effect on profit factor is positive or negative depends on the entry edge and is not established here.
- This is a predicted direction, not a sourced finding, and the report writer should not present it as evidence.

### Gaps
- No study comparing multiple stop widths on the same daily breakout signals in equities was found.

## (d) Position sizing for a fixed number of slots

### Takeaway
No source found addresses this directly. The sizing interaction follows from the stop definition and is a derivation, not a cited result.

### Inferences
- With N slots and a fixed risk per trade R (for example 0.5–1% of equity), shares = R / (entry minus stop). A wider stop reduces shares for the same risk, so fewer dollars are deployed per slot. ATR stops give consistent dollar risk across names. Swing-low stops give variable dollar risk.
- A volume filter reduces the number of candidates. With a fixed slot count, this changes which candidates fill slots, so the ranking rule (for example, by volume ratio or breakout strength) matters as much as the filter threshold.

### Gaps
- No source on fixed-slot sizing for breakout systems was found. Check against the project's own portfolio code before relying on these inferences.

## Filters: relative-volume and breakout-bar strength (computable from OHLC)

### Takeaway
Breakout-bar strength filters are common practitioner rules, but no sourced evidence on their effect was found. Definitions below are computable from daily OHLCV.

### Rule definitions (UNVERIFIED as to effect)
- Relative volume: RVOL = volume(t) / mean(volume(t-20 .. t-1)). Computable from OHLCV.
- Close location in range: CLV = (close - low) / (high - low). Computable; 0 is the low, 1 is the high. High values indicate a strong close on the breakout bar.
- Breakout bar range relative to ATR: (high - low) / ATR(14). Computable; flags extended bars that may gap or reverse.
- Gap filter: open(t) - close(t-1) relative to ATR. Computable; large gaps are a common exclusion but no source was checked.

### Gaps
- No sourced backtest of CLV, RVOL or range filters on daily equity breakouts was found.

## Indian equities: volume data pitfalls

### Takeaway
Traded volume and delivery volume are different. Delivery percentage is available from NSE, but is not part of an OHLCV feed. Zero-volume bars and missing candles are reported by vendors, mainly in illiquid stocks. None of these points has an official NSE statement found in this search.

### Cited Findings
- Traded volume is total shares traded in a day. Deliverable volume is the part that moves into or out of demat accounts, excluding same-day buy-and-sell. Delivery percentage = deliverable quantity / traded quantity x 100 — [Equities India glossary](https://equitiesindia.com/glossary/delivery-percentage) and [Rupeezy](https://rupeezy.in/blogs/what-is-volume-in-share-market-with-example/) (SECONDARY; forum and blog sources)
- NSE publishes quantity traded, deliverable quantity, and delivery percentage on its website. The website updates the percentage hourly intraday; the end-of-day figure comes from the bhavcopy — [TradingQnA forum](https://tradingqna.com/t/what-is-deliverable-volume/284/3) (UNVERIFIED; forum summary of NSE; check NSE directly)
- Average delivery-to-traded volume on NSE was about 31% in April–October FY26 — [Mint, via Magzter](https://www.magzter.com/hi/stories/newspaper/Mint-Mumbai/RETAIL-SCRAMBLE-ON-NSE-DRIVES-DELIVERY-VOLUMES-TO-A-RECORD) (SECONDARY; not fetched)
- Zero-volume minute candles where TradingView records trades, mostly in SME and illiquid scrips — [Kite Connect forum](https://kite.trade/forum/discussion/16356/persistent-zero-volume-first-candles-and-ohlc-discrepancies-in-historical-api) (UNVERIFIED; user reports)
- Candles absent entirely, not only zero-volume, in some illiquid scrips — [Kite Connect forum](https://kite.trade/forum/discussion/comment/16440) (UNVERIFIED; user report)
- Zero open/low/price candles reported in historical API data — [Kite Connect forum](https://kite.trade/forum/discussion/comment/53159/) (UNVERIFIED; user report)
- Daily volume totals differ between Upstox and bhavcopy. One user suggests the bhavcopy includes post-close trades captured near 15:59 IST, while the feed uses the 15:30 close. Another reports bhavcopy matching GlobalDataFeeds but not Upstox — [Upstox community](https://community.upstox.com/t/volume-data-not-matching-with-bhavcopy/8540) (UNVERIFIED; user reports)
- The SERIES column is dropped in some vendor data, so the same scrip under different series cannot be separated — [Kite Connect forum](https://kite.trade/forum/discussion/comment/14299/) (UNVERIFIED; user report)
- NSE bhavcopy format changed: the old report was replaced by the CM-UDiFF Common Bhavcopy (zip), effective 8 July 2024. Any long history needs a format-aware loader — UNVERIFIED; stated in a search snippet, not checked against NSE

### Inferences
- Use bhavcopy volume as the single source for historical daily volume, and do not mix vendor feeds in one series. Verify against the bhavcopy before backtesting.
- Treat zero-volume bars as missing, not as zero volume, when computing the 20-day average. Exclude or flag them.
- Delivery percentage would be a useful extra filter, but it is not in a plain OHLCV feed. It is available from NSE bhavcopy, so it can be used without intraday data.

### Gaps
- No official NSE documentation on zero-volume bars or on bhavcopy volume definitions was retrieved. NSE's data-details PDFs were in the results but not read.
- No study of delivery percentage as a breakout filter in India was found.

## Summary of what can and cannot be implemented from OHLCV

| Rule | OHLCV only? | Evidence |
|---|---|---|
| Volume ratio = vol / mean(vol, 20 prior bars) | Yes | Practitioner thresholds 1.5x/2x; one vendor test weak (SECONDARY) |
| Chandelier stop: high(22) - 3 x ATR(22), close-based exit | Yes | Standard definition (SECONDARY) |
| ATR(14) initial stop at 2x-3x | Yes | No head-to-head evidence found |
| Swing-low stop | Yes | No head-to-head evidence found |
| CLV, RVOL, range/ATR filters | Yes | No sourced effect |
| Delivery percentage filter | No, needs NSE bhavcopy delivery field | No study found |
| Intraday volume or timing | No | Not researched |

## Unresolved

- The main question, whether ATR stops beat swing-low stops on daily breakouts in win rate or profit factor, is unanswered by the sources found. The practical route is to backtest the variants on the project's own daily data, using the exact entry rule, ATR(14) Wilder smoothing, the stop multiples 2x and 3x, and a swing-low stop, reporting win rate, average win/loss, profit factor and expectancy in R, out of sample and net of costs.
- The Zarattini et al. 2025 paper (SSRN 5084316) and Lo-Mamaysky-Wang (2000) volume results should be read in full before citing.
