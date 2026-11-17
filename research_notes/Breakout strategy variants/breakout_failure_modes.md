# Why 20-day and 55-day Channel Breakouts Lose Edge on Daily Bars, and Evidence-Backed Fixes

Scope note: this is a short literature pass (about 13 tool calls). Most primary papers were read only via abstracts and search snippets, not full text. Anything not reached in a source is marked as a gap. Practitioner and vendor claims are labeled as such. Target universe is NSE mid and large caps, 2015 to 2026. Almost none of the cited evidence covers that universe, so transfer is flagged in each section.

## 1. Do volume-confirmed breakouts outperform unconfirmed ones on daily data?

### Takeaway
No reliable, peer-reviewed daily-bar study was found that quantifies profit factor or win rate for volume-confirmed versus unconfirmed channel breakouts. The only directional evidence is a secondhand O'Neil-style result and a vendor claim. Treat the volume filter as a hypothesis to test in our own backtest.

### Cited Findings
- Brock, Lakonishok and LeBaron (1992) tested moving-average and trading-range break rules on Dow Jones data, 1897 to 1986. They found buy signals followed by higher returns and lower volatility than sell signals; the paper does not test volume as a filter. Source: [RePEc/JoF record](https://econpapers.repec.org/RePEc:bla:jfinan:v:47:y:1992:i:5:p:1731-64); full text is JSTOR-restricted, so the summary is from the abstract and secondary citations.
- A third-party summary reports an O'Neil-style study where the highest-volume-change bucket had higher 63-day cumulative alpha but a slightly lower hit rate than the lowest bucket. Source: [The Right Trader, breakout volume page](https://therighttrader.com/learn/trend-analysis/breakout-volume). Unverified; original study not located.
- AvaTrade cites a TradingMarkets study claiming low-volume breakouts failed to continue more than 58% of the time. Source: [AvaTrade](https://avatrade.com.au/education/online-trading-strategies/trading-breakout-stocks). Original not located; unverified.
- The Right Trader states there is no reliable published win rate or return for "high volume breakouts" as a single class. Source: [The Right Trader](https://therighttrader.com/learn/trend-analysis/breakout-volume). Practitioner view, consistent with our search result.
- Practitioner claim (unverified, low quality): a 20-day close with 1.5x volume plus a 10-day stop produces a set of results, but no reference backtest is given. Source: [The Right Trader](https://therighttrader.com/learn/trading-strategies/breakout-trading-strategy).

### Inferences
- The volume evidence is mostly about intraday or single-stock momentum. Daily Indian mid caps have thinner and more event-driven volume, so a fixed multiple of the 20-day average may fire on news spikes that fail. A relative volume filter (for example volume over 1.5x its 20-day median) should be tested, not assumed.
- The volume filter reduces trade count. The net effect on profit factor depends on whether it removes losers more than winners. Expect fewer trades and wider confidence intervals.

### Gaps
- No peer-reviewed study on NSE daily breakouts with a volume filter was found.
- Original TradingMarkets and O'Neil studies were not located.

## 2. Which stop designs have been tested on channel breakouts, and what did they show?

### Takeaway
The Turtle rules (as described in secondary sources) use a 2 x ATR(20) stop with a 10-day or 20-day opposite-channel exit. No independent published test was found that compares support-low, ATR and percentage stops on 20 and 55-day channels with profit factor reported. One practitioner Scribd test found that a 55-day Turtle variant lost money and that a daily-moved 4% trailing stop did worse than a one-day exit. That is weak, undated evidence.

### Cited Findings
- Turtle system description: System 1 enters on a 20-day breakout and exits on a 10-day opposite breakout; System 2 enters on a 55-day breakout and exits on a 20-day opposite breakout. Stops are 2N, where N is the 20-day ATR. Sources: [TradingView Turtle indicator description](https://www.tradingview.com/script/dvVHQyPW-Turtle-Trading-Strategy-Indicator) and [TrendSpider](https://trendspider.com/learning-center/richard-dennis-turtle-trading-strategy/). These are secondary descriptions; primary Turtle documentation was not retrieved. Verified only as "described by these sources."
- Source disagreement on the Turtle rules: one description says risk is 2% of capital per trade, another says 1% equity-unit sizing; pyramid caps differ (4 vs 5 units). Sources conflict and the original is unverified.
- A Scribd test (undated, author unknown) reported that the 55-day Turtle breakout lost money and that a 4% trailing stop moved up daily performed worse than a one-day exit. Source: [Scribd PDF](https://www.scribd.com/document/431858664/donchian-channel-breakout-pdf). Low quality; used only as a negative signal to test.
- A TradingView 55/20 script uses entryN 55, exitN 20, atrLen 20, stopMult 2.0 as an ATR trailing stop on the opposite channel. It shows no profit factor. Source: [TradingView script](https://it.tradingview.com/script/fVg6KT1K). Code, not a study.
- Liberated Stock Trader reports an expectancy of 0.2 on a 20-period Donchian test on DJIA stocks, with exits at the next day's HL2. Source: [Liberated Stock Trader](https://liberatedstocktrader.com/?p=28271). Different design; unverified.

### Inferences
- Support-low stops on a 20-day breakout are often far from entry, which raises risk per unit and makes sizing mandatory. ATR stops adapt to volatility and are the design the original Turtle rules used. Percentage stops ignore volatility, so on mid caps with different ATR they produce uneven risk. These are reasoned points; not supported by a tested study here.
- Tighter stops increase whipsaw exits in ranging markets. This is the mechanism behind the "exits too narrow" failure mode.

### Gaps
- No tested comparison of support-low vs ATR vs percent stops on 20 and 55-day channels with profit factor was found.

## 3. Does ranking breakout signals by relative strength or reward-to-risk improve results with a few slots?

### Takeaway
Relative-strength ranking has the strongest support in the cross-sectional momentum literature, but that literature is about monthly or weekly rebalancing, not daily breakout entry. No study was found that tests ranking daily breakout signals by RS or reward-to-risk with a capped number of slots. Clenow-style momentum ranking has a third-party replication with positive results and a skeptical forum replication.

### Cited Findings
- Clenow's momentum approach (as described by secondary sources): regression-slope momentum on S&P 500 stocks, weekly rebalancing, a 100-day moving-average filter, naive risk parity sizing. Source: [TuringTrader summary](https://turingtrader-com.web.app/portfolios/clenow-stocks-on-the-move). Vendor summary; unverified against the book.
- The Chartist blog reports a 1999 to 2014 replication: about 12.3% annual return vs 5.2% for the S&P 500, max drawdown about -24% vs -55%. Source: [The Chartist](https://www.thechartist.com.au/?p=5829). Third-party, not the book's own numbers; its author says results were consistent across momentum calculations.
- A Quantopian-era forum thread reproduced the strategy, hit a negative-cash rebalancing problem, and concluded "I don't see the allure of the strategy." Source: [Quantopian archive](https://quantopian-archive.netlify.app/forum/threads/stocks-on-the-move-by-andreas-clenow). Skeptical, informal.
- Reward-to-risk ranking: the Right Trader says there is no reliable published win rate or return for its specific breakout card, which includes a 2R target. Source: [The Right Trader](https://therighttrader.com/learn/trading-strategies/breakout-trading-strategy). Practitioner claim; no evidence.

### Inferences
- With a few slots, ranking the day's breakout candidates by RS (for example 6-month return rank) is a cheap way to concentrate capital in the strongest names. This is a sensible design but unproven for daily breakouts. The key test is whether profit factor holds when the slot cap binds.
- Reward-to-risk ranking uses an ex-ante stop distance. It favors tight-stop signals, which can bias toward the whipsaw failure mode. It should be tested against plain RS rank.

### Gaps
- No peer-reviewed test of daily breakout ranking under a slot cap was found.

## 4. Are time stops or trailing stops reported to help or hurt breakout expectancy?

### Takeaway
Trailing channel exits are part of the classic design (the 10-day and 20-day opposite-channel exits act as trailing stops). Evidence on time stops was not found. The only direct negative signal on trailing stops is the undated Scribd test: a daily-moved 4% trail did worse than a one-day exit. That is one unverified result.

### Cited Findings
- Turtle exits are opposite-channel exits (10-day for System 1, 20-day for System 2), a trailing structure. Source: [TradingView Turtle description](https://www.tradingview.com/script/dvVHQyPW-Turtle-Trading-Strategy-Indicator). Secondary description.
- Scribd test: 4% trailing stop moved up daily underperformed a one-day exit. Source: [Scribd PDF](https://www.scribd.com/document/431858664/donchian-channel-breakout-pdf). Undated, low quality.
- Park and Irwin (2007) survey: 95 studies, 56 report profits, 20 report negative results, the rest mixed; profitability is weakest on daily stock data in later periods. Source: [Park and Irwin, J. Economic Surveys](https://econpapers.repec.org/RePEc:bla:jecsur:v:21:y:2007:i:4:p:786-826). Verified via abstract and a secondary summary; full text not read.

### Inferences
- A time stop would exit stalled breakouts (a common failure: price breaks, then drifts sideways). This is a plausible fix but no tested evidence was found; test it as a parameter, not a rule.
- Trailing exits give back profit when they are too tight. The 10-day exit in System 1 is shorter than the 20-day entry, so it is already fairly tight, which can explain high turnover and small average winners.

### Gaps
- No study on time stops for channel breakouts was found.

## 5. Sample-size and overfitting pitfalls

### Takeaway
The most relevant warnings are from Bailey, Borwein, López de Prado and Zhu (probability of backtest overfitting), and from Brock et al.'s own replication history. These point to multiple testing across channel lengths, stops and filters, plus short samples and costs. Several Indian studies find the edge disappears after costs.

### Cited Findings
- Bailey et al. propose the probability of backtest overfitting (PBO) using combinatorially symmetric cross-validation, and state that hold-out methods are unreliable for investment backtests. Published in Journal of Computational Finance (2017), after SSRN preprints. Sources: [SSRN](https://papers.ssrn.com/abstract=2326253) and [Risk.net](https://www.risk.net/2471206). Verified via abstract only. The same group developed the Deflated Sharpe Ratio for multiple testing and Minimum Backtest Length for single testing (per a secondary source; not independently read).
- Brock et al. (1992) results were questioned in later replications, with diminishing profits after the paper and concern about data snooping. Source: [RePEc record](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html) and secondary citation. Full text not read.
- Hudson, Dempsey and Keasey (1996) found the Brock et al. rules have predictive ability on UK FT30 data (1935 to 1994), but that they would not earn excess returns after costly trading. Source: [Journal of Banking & Finance record](https://econpapers.repec.org/RePEc:eee:jbfina:v:20:y:1996:i:6:p:1121-1132). Verified via abstract and secondary summary.
- Indian studies: Agarwal (2006, unpublished Nottingham dissertation) reports moving-average and range-break rules still profitable after costs on Indian indices. Source: [Nottingham record](https://cendekia.unisza.edu.my/neuaxis-e/Record/nottingham-20281/Details). Unpublished; treat with caution. Muruganandan (2020, Colombo Business Journal) finds technical rules on BSE Sensex 2000 to 2018 fail to deliver abnormal returns consistently. Source: [CBJ](https://mgmt.cmb.ac.lk/cbj/index.php/testing-the-profitability-of-technical-trading-rules-across-market-cycles-evidence-from-india/). Focused on MACD and RSI. Bhama (2025) reports transaction costs can significantly reduce SMA and EMA portfolio performance on NSE 500 firms over 27 years. Source: [IMFI 2025 PDF](https://businessperspectives.org/images/pdf/applications/publishing/templates/article/assets/23350/IMFI_2025_04_Bhama.pdf). The fetch failed; this rests on the search snippet only.
- Practitioner Nifty test (tradingqna): Donchian 20 on daily Nifty, long-only drawdown about 5 years, no transaction costs, author concludes "both are to be dumped." Source: [TradingQnA](https://tradingqna.com/t/trend-following-in-india-part-1-testing-donchian-s-classic-rules/188234). Index only, no period, costs excluded.
- Schulmeister (2007), via a secondary summary, argues technical profitability shifted from daily to intraday data rather than vanishing. Source: [Park and Irwin summary, WP 2007](https://wifo.ac.at/wp-content/uploads/upload-4606/WP_2007_289.pdf). Not read directly.

### Inferences
- The practical overfitting risks for us: (a) choosing among 20, 55 and other channel lengths plus stops and filters inflates apparent edge; (b) with 2015 to 2026 NSE data, one bull phase can dominate results; (c) costs and STT or impact on mid caps can erase small per-trade edges (Bhama, Hudson et al.).
- Minimum controls to report: out-of-sample split by year, parameter neighborhoods rather than single peaks, a PBO or deflated-Sharpe style correction, and costs with slippage.

### Gaps
- No study specifically on overfitting for channel breakouts on NSE was found.

## Modifications: evidence summary

| Modification | Evidence found | Strength |
|---|---|---|
| Volume confirmation | Secondhand O'Neil-style and TradingMarkets claims; no daily-bar NSE test | Weak, unverified |
| ATR stop (2N) | Turtle rules as described by secondary sources; no independent test found | Design precedent, untested here |
| Support-low or percent stop | Only undated practitioner negative result for a 4% trail | Very weak |
| RS ranking | Clenow-style cross-sectional momentum, third-party replication positive, forum replication skeptical; monthly/weekly, not daily breakouts | Moderate for momentum, not for breakouts |
| Reward-to-risk ranking | Vendor claim only | None |
| Time stop | None found | None |
| Trailing exits | Turtle opposite-channel exits; one negative undated test | Weak |
| Trend filter (for example price above 100-day MA) | Used in Clenow-style rules (vendor and forum description) | Weak, unverified |
| Minimum breakout size | Not searched; no evidence found | None |
| Pullback entry after breakout | Not searched; no evidence found | None |

## Failure modes: what the evidence supports

- Whipsaw in ranging markets: consistent with Hudson et al. and Park and Irwin's finding that profitability weakens over time in daily stock data. Verified direction, not magnitude.
- Late entries and gap fills: no sources found. Reasoned only; test with a gap-aware fill model.
- Exits too wide or too narrow: the Turtle 10-day exit is tight relative to the 20-day entry, and the undated 4% trail underperformed a one-day exit. Direction only.
- False breakouts: the volume and minimum-size literature was not found in usable form. Gap.

## Transfer caveats for NSE mid and large caps, 2015 to 2026

- Most studies use US indices or stocks (Dow 1897 to 1986, S&P 500), UK FT30 (1935 to 1994), or intraday futures. None cover NSE single stocks in 2015 to 2026.
- Indian results are mixed and often run on indices, without costs, or in unpublished form.
- Mid caps have wider spreads, more event-driven volume, and circuit limits. These affect fills, stop execution and volume-filter behavior, which the cited studies do not address.
- Turtle parameters were set for futures and 1980s markets; the same lengths do not carry over automatically.

## Recommended tests for our own backtest (from the gaps above)

1. Baseline 20 and 55-day channels with ATR(20) x 2 stop, 10 and 20-day exits, with costs and slippage.
2. Volume filter variants (relative volume over 1.25x, 1.5x, 2x of 20-day median).
3. Stop variants: support-low, ATR multiples 1.5, 2, 3, percent.
4. RS-rank selection under slot caps (1 to 5 slots), versus first-come selection.
5. Time stop and trend filter variants, reported with year-by-year splits.
6. Report PBO or deflated Sharpe across all variants to control multiple testing.

## Verification status

- Verified via abstract or search snippet: Brock et al. (1992), Hudson et al. (1996), Park and Irwin (2007), Bailey et al. (PBO).
- Secondary or practitioner only: Turtle rules, Clenow replications, Scribd and TradingQnA tests, TradingMarkets and O'Neil volume claims, Agarwal (2006), Muruganandan (2020), Bhama (2025, snippet only).
- Not verified: any primary Turtle document, any full-text study of volume or time stops, any NSE daily breakout test with profit factor.
