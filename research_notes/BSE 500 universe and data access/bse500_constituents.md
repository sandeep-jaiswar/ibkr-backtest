# BSE 500 Constituents and Data Access

## Which constituents list is current, and as of when?

### Takeaway
A machine-readable snapshot of 500 BSE 500 members was retrieved on 2026-11-17 from the Dhan index page (embedded data), with BSE scrip code (Sid), ISIN, and NSE-style symbol. The list is a third-party capture, not BSE's own file; its effective date and the BSE official constituent file could not be verified.

### Cited Findings
- Snapshot: 500 rows, 500 unique ISINs, 500 unique BSE scrip codes (Sid), all with Exch=BSE. Retrieved 2026-11-17 from [Dhan BSE 500 sector weightage page](https://dhan.co/indices/bse-500-sector-weightage); the page's index record is titled BSE 500 with last price 37,297.24 at capture.
- BSE's own index pages (bseindia.com/indices/IndexArchiveData.html) and BSE API endpoints returned a JavaScript shell or HTTP 403 Access Denied to scripted download; no official BSE constituent CSV/PDF was downloaded. [BSE index archive page](https://www.bseindia.com/indices/IndexArchiveData.html?idx=16)
- Secondary sources say the exhaustive list is on the exchange website: [Bajaj AMC BSE 500 page](https://www.bajajamc.com/knowledge-centre/bse-500-index).
- Investing.com shows 488 constituents for the BSE 500 index, which conflicts with the 500 target count: [Investing.com BSE 500 components](https://uk.investing.com/indices/s-p-bse-500-components). The Dhan capture has 500 rows, so the two sources are dated differently and cannot be reconciled from here.

### Inferences
- The Dhan list is a reasonable working snapshot for a backtest of the current universe only. It is not a historical membership file.

### Gaps
- The official BSE list as of a stated date was not verified against bseindia.com.
- The Dhan page gives no effective date or rebalance reference.

## How does BSE scrip code map to NSE symbol and ISIN?

### Takeaway
ISIN is the reliable join key. Against NSE's live EQUITY_L.csv (2,633 rows, pulled 2026-11-17), 498 of 500 snapshot ISINs match; the NSE symbol matched the snapshot's symbol in every matched case.

### Cited Findings
- NSE EQUITY_L.csv fetched from [NSE archives](https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv); fields include SYMBOL and ISIN NUMBER.
- BSE scrip code is a numeric code (e.g., 500325 for Reliance Industries); BSE's scrip master is BSE_EQ_SCRIP_DDMMYYYY.csv per BSE's bhav copy page, but the direct file was not retrieved (404 for a constructed date URL): [BSE bhav copy page](https://bseindia.com/markets/marketinfo/BhavCopy.aspx). BSE also states that a CAS indicator field update is effective 31 July 2026 (per a search summary, not verified).
- Equity-with-ISIN file EQ_ISINCODE was discontinued on 2024-07-08 per the same BSE bhav copy page; do not rely on it.

### Inferences
- BSE scrip code, NSE symbol and ISIN can be joined through ISIN for this snapshot. Two rows, flagged below, have no NSE match.

### Gaps
- No BSE scrip master file was downloaded, so the BSE scrip code is taken from the Dhan Sid field and not independently checked against BSE.

## What is the rebalancing schedule and how is membership changed?

### Takeaway
Secondary sources say the BSE 500 is reviewed semi-annually (June and December). The methodology was changed effective 22 December 2025 per a circular summary, and 2026 changes touched BSE 500 family indices.

### Cited Findings
- Semi-annual June/December review: [Kotak Securities BSE 500](https://www.kotaksecurities.com/indices/indian-indices/bse-500) and search summaries; not checked against BSE's methodology PDF.
- Methodology change effective 22 Dec 2025: top 750 stocks ranked by annualized traded value and free-float market cap, eligible universe moved from BSE AllCap to BSE 1000, target count 500 with relaxation if short. Source: [rhnvrm BSE circular mirror](https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2025/bse-2025-08-01-70954565938a712e-change-in-methodology-to-the-bse-indices) (secondary summary).
- Earlier BSE consultation paper proposed a liquidity screen with 2% buffer at each semi-annual rebalance (proposal, adoption not confirmed): [BSE market consultation](https://www.bseindia.com/downloads1/Market_Consultation_BSE_Indices.pdf).
- 2026 events touching BSE 500 family: March 23 (BSE SMALLCAP 500 four drops/adds), April 30 Vedanta demerger reconstitution affecting 30+ indices including BSE 500 (secondary, per [multibagg note](https://www.multibagg.ai/market-pulse/articles/bse-indices-rejig-june-2026-cmph0932q8qkytg0j656l81ob) and [rhnvrm circular mirror](https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2026/bse-2026-04-23-ae04e2dcd105df92-changes-to-the-bse-indices/)). A June 2026 semi-annual review was reported, but no BSE 500 list was found for it.
- BSE publishes reconstitution media releases with add/delete Excel files, e.g., [June 2024 reconstitution](https://bseindia.com/downloads/SPDJ_ANN/MediaReleasePDF/Reconstitution_of_BSE_Indices_June_2024.pdf).

### Inferences
- A survivorship-safe backtest needs the add/delete history from these reconstitution notices, which can be reconstructed from BSE press releases and circular mirrors.

### Gaps
- The exact effective dates for each BSE 500 review, and the full add/delete list since 2015, were not retrieved.

## Is there point-in-time history (2015, 2018, 2021) and third-party sources for it?

### Takeaway
No public point-in-time BSE 500 membership archive was found. History has to be built from BSE reconstitution notices and circular archives, which were only partly reachable.

### Cited Findings
- BSE reconstitution notices exist as PDFs on bseindia.com: [June 2024 notice](https://bseindia.com/downloads/SPDJ_ANN/MediaReleasePDF/Reconstitution_of_BSE_Indices_June_2024.pdf); [BSE 2018 methodology change](https://bseindia.com/downloads/SPDJ_ANN/MediaReleasePDF/789358_mediarelease-s&pbsethematicindices-methodologychange-20180928.pdf).
- A third-party circular archive lists BSE reconstitution notices by year, including 2026 (e.g., [2026-03-13](https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2026/bse-2026-03-13-346cafda430026ee-reconstitution-of-bse-indices), [2026-05-08](https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2026/bse-2026-05-08-2a87d6795ebdeb10-changes-to-the-bse-indices/)). Coverage before 2025 was not checked.
- Asia Index (BSE Index Services) publishes methodology and master data PDFs: [BSE Indices Methodology](https://www.asiaindex.co.in/Downloads/BSE_Indices_Methodology.pdf); the master data PDF was unreachable from this environment.

### Inferences
- For 2015, 2018 and 2021 membership, the reconstitution PDFs and circular archives are the best routes, but completeness is uncertain.

### Gaps
- No verified membership lists for 2015, 2018 or 2021 were found or downloaded.

## Data-quality issues and survivorship

### Takeaway
The snapshot has a few visible problems, and it cannot show delisted or merged names, so it biases a backtest toward survivors.

### Cited Findings
- Two rows have no NSE match by ISIN: NSE (National Stock Exchange of India, ISIN INE721I01024) and NSDL (INE301O01023). NSE is not a listed company, so this row looks like a data error in the source. Source: [Dhan BSE 500 page](https://dhan.co/indices/bse-500-sector-weightage).
- The Vedanta demerger (April 30, 2026) and March 2026 SMALLCAP changes mean names in older lists may be absent now (e.g., Vedanta demerged entity handled by secondary sources): [multibagg note](https://www.multibagg.ai/market-pulse/articles/bse-indices-rejig-june-2026-cmph0932q8qkytg0j656l81ob).
- Counts differ by source (500 vs 488): [Investing.com](https://uk.investing.com/indices/s-p-bse-500-components).

### Inferences
- Using only the current snapshot will introduce survivorship bias. Delisted and removed names need the reconstitution history.

### Gaps
- No delisted-company list for BSE 500 was found.

## Constituent table (Dhan capture, 2026-11-17, sorted by market cap, 500 rows)

Columns: company name, BSE scrip code (Sid), NSE symbol (matched via ISIN to NSE EQUITY_L.csv 2026-11-17; blank if no match), ISIN, sector.

| # | Company | BSE scrip code | NSE symbol | ISIN | Sector |
|---|---|---|---|---|---|
| 1 | Reliance Industries | 500325 | RELIANCE | INE002A01018 | Energy |
| 2 | Bharti Airtel | 532454 | BHARTIARTL | INE397D01024 | Telecom |
| 3 | HDFC Bank | 500180 | HDFCBANK | INE040A01034 | Financial Services |
| 4 | ICICI Bank | 532174 | ICICIBANK | INE090A01021 | Financial Services |
| 5 | State Bank of India | 500112 | SBIN | INE062A01020 | Financial Services |
| 6 | Tata Consultancy Services | 532540 | TCS | INE467B01029 | Information Technology |
| 7 | Bajaj Finance | 500034 | BAJFINANCE | INE296A01032 | Financial Services |
| 8 | Larsen & Toubro | 500510 | LT | INE018A01030 | Industrials |
| 9 | LIC of India | 543526 | LICI | INE0J1Y01017 | Financial Services |
| 10 | National Stock Exchange of India | 544937 |  | INE721I01024 | Financial Services |
| 11 | Kotak Bank | 500247 | KOTAKBANK | INE237A01036 | Financial Services |
| 12 | Hindustan Unilever | 500696 | HINDUNILVR | INE030A01027 | FMCG |
| 13 | Infosys | 500209 | INFY | INE009A01021 | Information Technology |
| 14 | Sun Pharmaceutical | 524715 | SUNPHARMA | INE044A01036 | Healthcare |
| 15 | Adani Ports & SEZ | 532921 | ADANIPORTS | INE742F01042 | Services |
| 16 | Titan | 500114 | TITAN | INE280A01028 | Consumer Discretionary |
| 17 | Axis Bank | 532215 | AXISBANK | INE238A01034 | Financial Services |
| 18 | Mahindra & Mahindra | 500520 | M&M | INE101A01026 | Consumer Discretionary |
| 19 | Maruti Suzuki | 532500 | MARUTI | INE585B01010 | Consumer Discretionary |
| 20 | Adani Power | 533096 | ADANIPOWER | INE814H01029 | Utilities |
| 21 | HCL Technologies | 532281 | HCLTECH | INE860A01027 | Information Technology |
| 22 | ITC | 500875 | ITC | INE154A01025 | FMCG |
| 23 | UltraTech Cement | 532538 | ULTRACEMCO | INE481G01011 | Construction Materials |
| 24 | Adani Enterprises | 512599 | ADANIENT | INE423A01024 | Metals & Mining |
| 25 | Eternal | 543320 | ETERNAL | INE758T01015 | Consumer Services |
| 26 | JSW Steel | 500228 | JSWSTEEL | INE019A01038 | Metals & Mining |
| 27 | Hindustan Aeronautics | 541154 | HAL | INE066F01020 | Capital Goods |
| 28 | NTPC | 532555 | NTPC | INE733E01010 | Utilities |
| 29 | Bajaj Finserv | 532978 | BAJAJFINSV | INE918I01026 | Financial Services |
| 30 | Divis Laboratories | 532488 | DIVISLAB | INE361B01024 | Healthcare |
| 31 | Bajaj Auto | 532977 | BAJAJ-AUTO | INE917I01010 | Consumer Discretionary |
| 32 | Bharat Electronics | 500049 | BEL | INE263A01024 | Capital Goods |
| 33 | Oil & Natural Gas Corporation | 500312 | ONGC | INE213A01029 | Energy |
| 34 | Asian Paints | 500820 | ASIANPAINT | INE021A01026 | Consumer Discretionary |
| 35 | Nestle | 500790 | NESTLEIND | INE239A01024 | FMCG |
| 36 | Coal India | 533278 | COALINDIA | INE522F01014 | Energy |
| 37 | Power Grid Corporation of India | 532898 | POWERGRID | INE752E01010 | Utilities |
| 38 | Adani Green Energy | 541450 | ADANIGREEN | INE364U01010 | Utilities |
| 39 | Shriram Finance | 511218 | SHRIRAMFIN | INE721A01047 | Financial Services |
| 40 | Hindustan Zinc | 500188 | HINDZINC | INE267A01025 | Metals & Mining |
| 41 | Tata Steel | 500470 | TATASTEEL | INE081A01020 | Metals & Mining |
| 42 | Avenue Supermarts DMart | 540376 | DMART | INE192R01011 | Consumer Services |
| 43 | Interglobe Aviation | 539448 | INDIGO | INE646L01027 | Services |
| 44 | Eicher Motors | 505200 | EICHERMOT | INE066A01021 | Consumer Discretionary |
| 45 | TVS Motors | 532343 | TVSMOTOR | INE494B01023 | Consumer Discretionary |
| 46 | Grasim Industries | 500300 | GRASIM | INE047A01021 | Construction Materials |
| 47 | Hindalco Industries | 500440 | HINDALCO | INE038A01020 | Metals & Mining |
| 48 | Indian Oil Corporation | 530965 | IOC | INE242A01010 | Energy |
| 49 | DLF | 532868 | DLF | INE271C01023 | Consumer Discretionary |
| 50 | Wipro | 507685 | WIPRO | INE075A01022 | Information Technology |
| 51 | SBI Life Insurance | 540719 | SBILIFE | INE123W01016 | Financial Services |
| 52 | Adani Energy Solutions | 539254 | ADANIENSOL | INE931S01010 | Utilities |
| 53 | Torrent Pharmaceuticals | 500420 | TORNTPHARM | INE685A01028 | Healthcare |
| 54 | Hyundai Motor India | 544274 | HYUNDAI | INE0V6F01027 | Consumer Discretionary |
| 55 | Samvardhana Motherson International | 517334 | MOTHERSON | INE775A01035 | Consumer Discretionary |
| 56 | Tech Mahindra | 532755 | TECHM | INE669C01036 | Information Technology |
| 57 | Trent | 500251 | TRENT | INE849A01020 | Consumer Services |
| 58 | Punjab National Bank | 532461 | PNB | INE160A01022 | Financial Services |
| 59 | Solar Industries | 532725 | SOLARINDS | INE343H01029 | Chemicals |
| 60 | Tata Motors | 544569 | TMCV | INE1TAE01010 | Capital Goods |
| 61 | Cholamandalam Investment | 511243 | CHOLAFIN | INE121A01024 | Financial Services |
| 62 | Union Bank of India | 532477 | UNIONBANK | INE692A01016 | Financial Services |
| 63 | Pidilite Industries | 500331 | PIDILITIND | INE318A01026 | Chemicals |
| 64 | Vedanta Aluminium Metal | 544780 | VAML | INE1CDF01017 | Metals & Mining |
| 65 | Bharat Heavy Electricals | 500103 | BHEL | INE257A01026 | Capital Goods |
| 66 | Jio Financial Services | 543940 | JIOFIN | INE758E01017 | Financial Services |
| 67 | ICICI Prudential Asset Management | 544658 | ICICIAMC | INE346A01027 | Financial Services |
| 68 | ABB | 500002 | ABB | INE117A01022 | Capital Goods |
| 69 | Varun Beverages | 540180 | VBL | INE200M01039 | FMCG |
| 70 | Tata Capital | 544574 | TATACAP | INE976I01016 | Financial Services |
| 71 | Bosch | 500530 | BOSCHLTD | INE323A01026 | Consumer Discretionary |
| 72 | Groww | 544603 | GROWW | INE0HOQ01053 | Financial Services |
| 73 | Bank of Baroda | 532134 | BANKBARODA | INE028A01039 | Financial Services |
| 74 | Hitachi Energy | 543187 | POWERINDIA | INE07Y701011 | Capital Goods |
| 75 | Vodafone Idea | 532822 | IDEA | INE669E01016 | Telecom |
| 76 | Bharat Petroleum | 500547 | BPCL | INE029A01011 | Energy |
| 77 | HDFC Life Insurance | 540777 | HDFCLIFE | INE795G01014 | Financial Services |
| 78 | Lenskart Solutions | 544600 | LENSKART | INE956O01016 | Consumer Services |
| 79 | Indian Hotels Company | 500850 | INDHOTEL | INE053A01029 | Consumer Services |
| 80 | Apollo Hospitals | 508869 | APOLLOHOSP | INE437A01024 | Healthcare |
| 81 | CG Power & Industrial Solutions | 500093 | CGPOWER | INE067A01029 | Capital Goods |
| 82 | Indian Bank | 532814 | INDIANB | INE562A01011 | Financial Services |
| 83 | Siemens | 500550 | SIEMENS | INE003A01024 | Capital Goods |
| 84 | Laurus Labs | 540222 | LAURUSLABS | INE947Q01028 | Healthcare |
| 85 | Bajaj Holdings & Investments | 500490 | BAJAJHLDNG | INE118A01012 | Financial Services |
| 86 | GAIL | 532155 | GAIL | INE129A01019 | Energy |
| 87 | LTM | 540005 | LTM | INE214T01019 | Information Technology |
| 88 | Canara Bank | 532483 | CANBK | INE476A01022 | Financial Services |
| 89 | One 97 Communications | 543396 | PAYTM | INE982J01020 | Financial Services |
| 90 | Lodha Developers | 543287 | LODHA | INE670K01029 | Consumer Discretionary |
| 91 | Zydus Life Science | 532321 | ZYDUSLIFE | INE010B01027 | Healthcare |
| 92 | Marico | 531642 | MARICO | INE196A01026 | FMCG |
| 93 | Polycab | 542652 | POLYCAB | INE455K01017 | Capital Goods |
| 94 | HDFC AMC | 541729 | HDFCAMC | INE127D01025 | Financial Services |
| 95 | LG Electronics | 544576 | LGEINDIA | INE324D01010 | Consumer Discretionary |
| 96 | Meesho | 544632 | MEESHO | INE0VDM01015 | Consumer Services |
| 97 | Jindal Steel | 532286 | JINDALSTEL | INE749A01030 | Metals & Mining |
| 98 | Dr Reddys Laboratories | 500124 | DRREDDY | INE089A01031 | Healthcare |
| 99 | Britannia Industries | 500825 | BRITANNIA | INE216A01030 | FMCG |
| 100 | Aditya Birla Capital | 540691 | ABCAPITAL | INE674K01013 | Financial Services |
| 101 | Cummins | 500480 | CUMMINSIND | INE298A01020 | Capital Goods |
| 102 | Cipla | 500087 | CIPLA | INE059A01026 | Healthcare |
| 103 | Muthoot Finance | 533398 | MUTHOOTFIN | INE414G01012 | Financial Services |
| 104 | GE Vernova T&D | 522275 | GVT&D | INE200A01026 | Capital Goods |
| 105 | GMR Airports | 532754 | GMRAIRPORT | INE776C01039 | Services |
| 106 | Tata Consumer Products | 500800 | TATACONSUM | INE192A01025 | FMCG |
| 107 | Tata Power | 500400 | TATAPOWER | INE245A01021 | Utilities |
| 108 | Siemens Energy | 544390 | ENRIN | INE1NPP01017 | Capital Goods |
| 109 | Power Finance Corporation | 532810 | PFC | INE134E01011 | Financial Services |
| 110 | Mankind Pharma | 543904 | MANKIND | INE634S01028 | Healthcare |
| 111 | IRFC | 543257 | IRFC | INE053F01010 | Financial Services |
| 112 | Hero Motocorp | 500182 | HEROMOTOCO | INE158A01026 | Consumer Discretionary |
| 113 | United Spirits | 532432 | UNITDSPR | INE854D01024 | FMCG |
| 114 | Indus Towers | 534816 | INDUSTOWER | INE121J01017 | Telecom |
| 115 | Aurobindo Pharma | 524804 | AUROPHARMA | INE406A01037 | Healthcare |
| 116 | Nykaa | 543384 | NYKAA | INE388Y01029 | Consumer Services |
| 117 | Max Healthcare Institute | 543220 | MAXHEALTH | INE027H01010 | Healthcare |
| 118 | Lloyds Metals & Energy | 512455 | LLOYDSME | INE281B01032 | Metals & Mining |
| 119 | Ashok Leyland | 500477 | ASHOKLEY | INE208A01029 | Capital Goods |
| 120 | Ambuja Cements | 500425 | AMBUJACEM | INE079A01024 | Construction Materials |
| 121 | Tata Motors Passenger Vehicles | 500570 | TMPV | INE155A01022 | Consumer Discretionary |
| 122 | MCX | 534091 | MCX | INE745G01043 | Financial Services |
| 123 | Persistent Systems | 533179 | PERSISTENT | INE262H01021 | Information Technology |
| 124 | JSW Energy | 533148 | JSWENERGY | INE121E01018 | Utilities |
| 125 | Godrej Consumer Products | 532424 | GODREJCP | INE102D01028 | FMCG |
| 126 | Coforge | 532541 | COFORGE | INE591G01025 | Information Technology |
| 127 | Shree Cement | 500387 | SHREECEM | INE070A01015 | Construction Materials |
| 128 | Federal Bank | 500469 | FEDERALBNK | INE171A01029 | Financial Services |
| 129 | Lupin | 500257 | LUPIN | INE326A01037 | Healthcare |
| 130 | Oracle Financial Services Software | 532466 | OFSS | INE881D01027 | Information Technology |
| 131 | ICICI Lombard General Insurance | 540716 | ICICIGI | INE765G01017 | Financial Services |
| 132 | IDBI Bank | 500116 | IDBI | INE008A01015 | Financial Services |
| 133 | Bharti Hexacom | 544162 | BHARTIHEXA | INE343G01021 | Telecom |
| 134 | Bharat Forge | 500493 | BHARATFORG | INE465A01025 | Consumer Discretionary |
| 135 | Hindustan Petroleum | 500104 | HINDPETRO | INE094A01015 | Energy |
| 136 | Dixon Technologies | 540699 | DIXON | INE935N01020 | Consumer Discretionary |
| 137 | UNO Minda | 532539 | UNOMINDA | INE405E01023 | Consumer Discretionary |
| 138 | Phoenix Mills | 503100 | PHOENIXLTD | INE211B01039 | Consumer Discretionary |
| 139 | JSW Infrastructure | 543994 | JSWINFRA | INE880J01026 | Services |
| 140 | REC | 532955 | RECLTD | INE020B01018 | Financial Services |
| 141 | Ather Energy | 544397 | ATHERENERG | INE0LEZ01016 | Consumer Discretionary |
| 142 | Info Edge | 532777 | NAUKRI | INE663F01032 | Consumer Services |
| 143 | Mazagon Dock Shipbuilders | 543237 | MAZDOCK | INE249Z01020 | Capital Goods |
| 144 | Motilal Oswal Financial Services | 532892 | MOTILALOFS | INE338I01027 | Financial Services |
| 145 | NHPC | 533098 | NHPC | INE848E01016 | Utilities |
| 146 | AU Small Finance Bank | 540611 | AUBANK | INE949L01017 | Financial Services |
| 147 | Glenmark Pharmaceuticals | 532296 | GLENMARK | INE935A01035 | Healthcare |
| 148 | Havells | 517354 | HAVELLS | INE176B01034 | Consumer Discretionary |
| 149 | SRF | 503806 | SRF | INE647A01010 | Chemicals |
| 150 | Bank of Maharashtra | 532525 | MAHABANK | INE457A01014 | Financial Services |
| 151 | Bank of India | 532149 | BANKINDIA | INE084A01016 | Financial Services |
| 152 | Indusind Bank | 532187 | INDUSINDBK | INE095A01012 | Financial Services |
| 153 | Prestige Estates Projects | 533274 | PRESTIGE | INE811K01011 | Consumer Discretionary |
| 154 | IDFC First Bank | 539437 | IDFCFIRSTB | INE092T01019 | Financial Services |
| 155 | Steel Authority of India | 500113 | SAIL | INE114A01011 | Metals & Mining |
| 156 | Waaree Energies | 544277 | WAAREEENER | INE377N01017 | Capital Goods |
| 157 | L&T Finance | 533519 | LTF | INE498L01015 | Financial Services |
| 158 | Kalyan Jewellers | 543278 | KALYANKJIL | INE303R01014 | Consumer Discretionary |
| 159 | Oil India | 533106 | OIL | INE274J01014 | Energy |
| 160 | Nippon Life India AMC | 540767 | NAM-INDIA | INE298J01013 | Financial Services |
| 161 | NTPC Green Energy | 544289 | NTPCGREEN | INE0ONG01011 | Utilities |
| 162 | Bajaj Housing Finance | 544252 | BAJAJHFL | INE377Y01014 | Financial Services |
| 163 | Dabur India | 500096 | DABUR | INE016A01026 | FMCG |
| 164 | ICICI Life Insurance | 540133 | ICICILIFE | INE726G01019 | Financial Services |
| 165 | Oberoi Realty | 533273 | OBEROIRLTY | INE093I01010 | Consumer Discretionary |
| 166 | Aster DM Quality Care | 540975 | ASTERDM | INE914M01019 | Healthcare |
| 167 | Adani Total Gas | 542066 | ATGL | INE399L01023 | Energy |
| 168 | Radico Khaitan | 532497 | RADICO | INE944F01028 | FMCG |
| 169 | Alkem Laboratories | 539523 | ALKEM | INE540L01014 | Healthcare |
| 170 | Torrent Power | 532779 | TORNTPOWER | INE813H01021 | Utilities |
| 171 | NMDC | 526371 | NMDC | INE584A01023 | Metals & Mining |
| 172 | Indian Overseas Bank | 532388 | IOB | INE565A01014 | Financial Services |
| 173 | Welspun Corp | 532144 | WELCORP | INE191B01025 | Capital Goods |
| 174 | APL Apollo Tubes | 533758 | APLAPOLLO | INE702C01027 | Capital Goods |
| 175 | Fortis Healthcare | 532843 | FORTIS | INE061F01013 | Healthcare |
| 176 | RBL Bank | 540065 | RBLBANK | INE976G01028 | Financial Services |
| 177 | GIC of India | 540755 | GICRE | INE481Y01014 | Financial Services |
| 178 | Jindal Stainless | 532508 | JSL | INE220G01021 | Metals & Mining |
| 179 | Apar Industries | 532259 | APARINDS | INE372A01015 | Capital Goods |
| 180 | NALCO | 532234 | NATIONALUM | INE139A01034 | Metals & Mining |
| 181 | Biocon | 532523 | BIOCON | INE376G01013 | Healthcare |
| 182 | Coromandel International | 506395 | COROMANDEL | INE169A01031 | Chemicals |
| 183 | Linde | 523457 | LINDEINDIA | INE473A01011 | Chemicals |
| 184 | Schaeffler India | 505790 | SCHAEFFLER | INE513A01022 | Consumer Discretionary |
| 185 | Godrej Properties | 533150 | GODREJPROP | INE484J01027 | Consumer Discretionary |
| 186 | Sona BLW Precision Forgings | 543300 | SONACOMS | INE073K01018 | Consumer Discretionary |
| 187 | Yes Bank | 532648 | YESBANK | INE528G01035 | Financial Services |
| 188 | Berger Paints | 509480 | BERGEPAINT | INE463A01038 | Consumer Discretionary |
| 189 | Abbott | 500488 | ABBOTINDIA | INE358A01014 | Healthcare |
| 190 | MRF | 500290 | MRF | INE883A01011 | Consumer Discretionary |
| 191 | SBI Cards | 543066 | SBICARD | INE018E01016 | Financial Services |
| 192 | Gland Pharma | 543245 | GLAND | INE068V01023 | Healthcare |
| 193 | Anthem Biosciences | 544449 | ANTHEM | INE0CZ201020 | Healthcare |
| 194 | Gujarat Fluorochemicals | 542812 | FLUOROCHEM | INE09N301011 | Chemicals |
| 195 | Swiggy | 544285 | SWIGGY | INE00H001014 | Consumer Services |
| 196 | Tata Communications | 500483 | TATACOMM | INE151A01013 | Telecom |
| 197 | Suzlon Energy | 532667 | SUZLON | INE040H01021 | Capital Goods |
| 198 | Navin Fluorine International | 532504 | NAVINFLUOR | INE048G01026 | Chemicals |
| 199 | Max Financial Services | 500271 | MFSL | INE180A01020 | Financial Services |
| 200 | Petronet LNG | 532522 | PETRONET | INE347G01014 | Energy |
| 201 | Piramal Finance | 544597 | PIRAMALFIN | INE202B01038 | Financial Services |
| 202 | 360 One WAM | 542772 | 360ONE | INE466L01038 | Financial Services |
| 203 | PB FinTech | 543390 | POLICYBZR | INE417T01026 | Financial Services |
| 204 | Authum Inv & Infr | 539177 | AIIL | INE206F01022 | Financial Services |
| 205 | HDB Financial Services | 544429 | HDBFS | INE756I01012 | Financial Services |
| 206 | UPL | 512070 | UPL | INE628A01036 | Chemicals |
| 207 | Aditya Infotech | 544466 | CPPLUS | INE819V01029 | Capital Goods |
| 208 | IPCA Laboratories | 524494 | IPCALAB | INE571A01038 | Healthcare |
| 209 | Colgate Palmolive | 500830 | COLPAL | INE259A01022 | FMCG |
| 210 | Mphasis | 526299 | MPHASIS | INE356A01018 | Information Technology |
| 211 | GlaxoSmithKline Pharmaceuticals | 500660 | GLAXO | INE159A01016 | Healthcare |
| 212 | Balkrishna Industries | 502355 | BALKRISIND | INE787D01026 | Consumer Discretionary |
| 213 | L&T Technology Services | 540115 | LTTS | INE010V01017 | Information Technology |
| 214 | Emcure Pharmaceuticals | 544210 | EMCURE | INE168P01015 | Healthcare |
| 215 | Vishal Mega Mart | 544307 | VMM | INE01EA01019 | Consumer Services |
| 216 | Patanjali Foods | 500368 | PATANJALI | INE619A01035 | FMCG |
| 217 | Poonawalla Fincorp | 524000 | POONAWALLA | INE511C01022 | Financial Services |
| 218 | Tube Investment | 540762 | TIINDIA | INE974X01010 | Consumer Discretionary |
| 219 | Aegis Logistics | 500003 | AEGISLOG | INE208C01025 | Energy |
| 220 | Ajanta Pharma | 532331 | AJANTPHARM | INE031B01049 | Healthcare |
| 221 | Hindustan Copper | 513599 | HINDCOPPER | INE531E01026 | Metals & Mining |
| 222 | KPR Mill | 532889 | KPRMILL | INE930H01031 | Consumer Discretionary |
| 223 | Supreme Industries | 509930 | SUPREMEIND | INE195A01028 | Capital Goods |
| 224 | JK Cement | 532644 | JKCEMENT | INE823G01014 | Construction Materials |
| 225 | M&M Financial Services | 532720 | M&MFIN | INE774D01024 | Financial Services |
| 226 | Rail Vikas Nigam | 542649 | RVNL | INE415G01027 | Industrials |
| 227 | Anand Rathi Wealth | 543415 | ANANDRATHI | INE463V01026 | Financial Services |
| 228 | Global Health | 543654 | MEDANTA | INE474Q01031 | Healthcare |
| 229 | Narayana Hrudayalaya | 539551 | NH | INE410P01011 | Healthcare |
| 230 | Premier Energies | 544238 | PREMIERENE | INE0BS701011 | Capital Goods |
| 231 | PTC Industries | 539006 | PTCIL | INE596F01018 | Capital Goods |
| 232 | Physicswallah | 544609 | PWL | INE0LP301011 | Consumer Services |
| 233 | Voltas | 500575 | VOLTAS | INE226A01021 | Consumer Discretionary |
| 234 | Bharat Dynamics | 541143 | BDL | INE171Z01026 | Capital Goods |
| 235 | ITC Hotels | 544325 | ITCHOTELS | INE379A01028 | Consumer Services |
| 236 | Sai Life Sciences | 544306 | SAILIFE | INE570L01029 | Healthcare |
| 237 | KEI Industries | 517569 | KEI | INE878B01027 | Capital Goods |
| 238 | Shyam Metalics & Energy | 543299 | SHYAMMETL | INE810G01011 | Capital Goods |
| 239 | Godrej Industries | 500164 | GODREJIND | INE233A01035 | Diversified |
| 240 | IRCTC | 542830 | IRCTC | INE335Y01020 | Consumer Services |
| 241 | Endurance Technologies | 540153 | ENDURANCE | INE913H01037 | Consumer Discretionary |
| 242 | Page Industries | 532827 | PAGEIND | INE761H01022 | Consumer Discretionary |
| 243 | Nuvama Wealth Management | 543988 | NUVAMA | INE531F01023 | Financial Services |
| 244 | Delhivery | 543529 | DELHIVERY | INE148O01028 | Services |
| 245 | LIC Housing Finance | 500253 | LICHSGFIN | INE115A01026 | Financial Services |
| 246 | Container Corporation of India | 531344 | CONCOR | INE111A01025 | Services |
| 247 | Astral | 532830 | ASTRAL | INE006I01046 | Capital Goods |
| 248 | Dr. Lal Path Labs | 539524 | LALPATHLAB | INE600L01024 | Healthcare |
| 249 | IREDA | 544026 | IREDA | INE202E01016 | Financial Services |
| 250 | Blue Star | 500067 | BLUESTARCO | INE472A01039 | Consumer Discretionary |
| 251 | Wockhardt | 532300 | WOCKPHARMA | INE049B01025 | Healthcare |
| 252 | Star Health Insurance | 543412 | STARHEALTH | INE575P01011 | Financial Services |
| 253 | HUDCO | 540530 | HUDCO | INE031A01017 | Financial Services |
| 254 | Thermax | 500411 | THERMAX | INE152A01029 | Capital Goods |
| 255 | Piramal Pharma | 543635 | PPLPHARMA | INE0DK501011 | Healthcare |
| 256 | Acutaas Chemicals | 543349 | ACUTAAS | INE00FF01025 | Healthcare |
| 257 | Angel One | 543235 | ANGELONE | INE732I01021 | Financial Services |
| 258 | NLC India | 513683 | NLCINDIA | INE589A01014 | Utilities |
| 259 | Exide Industries | 500086 | EXIDEIND | INE302A01020 | Consumer Discretionary |
| 260 | Krishna Institute of Medical Sciences | 543308 | KIMS | INE967H01025 | Healthcare |
| 261 | United Breweries | 532478 | UBL | INE686F01025 | FMCG |
| 262 | 3M India | 523395 | 3MINDIA | INE470A01017 | Diversified |
| 263 | CRISIL | 500092 | CRISIL | INE007A01025 | Financial Services |
| 264 | UCO Bank | 532505 | UCOBANK | INE691A01018 | Financial Services |
| 265 | Aegis Vopak Terminals | 544407 | AEGISVOPAK | INE0INX01018 | Energy |
| 266 | Mangalore Refinery & Petroleum | 500109 | MRPL | INE103A01014 | Energy |
| 267 | Cochin Shipyard | 540678 | COCHINSHIP | INE704P01025 | Capital Goods |
| 268 | AIA Engineering | 532683 | AIAENG | INE212H01026 | Capital Goods |
| 269 | Tata Investment Corporation | 501301 | TATAINVEST | INE672A01026 | Financial Services |
| 270 | Hexaware Technologies | 544362 | HEXT | INE093A01041 | Information Technology |
| 271 | Asahi India Glass | 515030 | ASAHIINDIA | INE439A01020 | Consumer Discretionary |
| 272 | PNB Housing Finance | 540173 | PNBHOUSING | INE572E01012 | Financial Services |
| 273 | Craftsman Automation | 543276 | CRAFTSMAN | INE00LO01017 | Consumer Discretionary |
| 274 | Central Bank of India | 532885 | CENTRALBK | INE483A01010 | Financial Services |
| 275 | Dalmia Bharat | 542216 | DALBHARAT | INE00R701025 | Construction Materials |
| 276 | HFCL | 500183 | HFCL | INE548A01028 | Telecom |
| 277 | Himadri Speciality Chemical | 500184 | HSCL | INE019C01026 | Chemicals |
| 278 | ACME Solar Holdings | 544283 | ACMESOLAR | INE622W01025 | Financial Services |
| 279 | Jubilant FoodWorks | 533155 | JUBLFOOD | INE797F01020 | Consumer Services |
| 280 | Manappuram Finance | 531213 | MANAPPURAM | INE522D01027 | Financial Services |
| 281 | Bandhan Bank | 541153 | BANDHANBNK | INE545U01014 | Financial Services |
| 282 | Godfrey Phillips | 500163 | GODFRYPHLP | INE260B01028 | FMCG |
| 283 | Inventurus Knowledge Solutions | 544309 | IKS | INE115Q01022 | Information Technology |
| 284 | Syrma SGS | 543573 | SYRMA | INE0DYJ01015 | Capital Goods |
| 285 | Neuland Laboratories | 524558 | NEULANDLAB | INE794A01010 | Healthcare |
| 286 | Honeywell Automation | 517174 | HONAUT | INE671A01010 | Capital Goods |
| 287 | Redington | 532805 | REDINGTON | INE891D01026 | Services |
| 288 | Escorts Kubota | 500495 | ESCORTS | INE042A01014 | Capital Goods |
| 289 | Cholamandalam Financial Holdings | 504973 | CHOLAHLDNG | INE149A01033 | Financial Services |
| 290 | IIFL Finance | 532636 | IIFL | INE530B01024 | Financial Services |
| 291 | Aditya Birla Sun Life AMC | 543374 | ABSLAMC | INE404A01024 | Financial Services |
| 292 | Tata Technologies | 544028 | TATATECH | INE142M01025 | Information Technology |
| 293 | Gabriel | 505714 | GABRIEL | INE524A01029 | Consumer Discretionary |
| 294 | Apollo Tyres | 500877 | APOLLOTYRE | INE438A01022 | Consumer Discretionary |
| 295 | Motherson Sumi Wiring | 543498 | MSUMI | INE0FS801015 | Consumer Discretionary |
| 296 | Force Motors | 500033 | FORCEMOT | INE451A01017 | Consumer Discretionary |
| 297 | Urban Company | 544515 | URBANCO | INE0CAZ01013 | Consumer Services |
| 298 | Sun TV Network | 532733 | SUNTV | INE424H01027 | Media Entertainment & Publication |
| 299 | The New India Assurance Company | 540769 | NIACL | INE470Y01017 | Financial Services |
| 300 | PI Industries | 523642 | PIIND | INE603J01030 | Chemicals |
| 301 | Cemindia Projects | 509496 | CEMPRO | INE686A01026 | Industrials |
| 302 | ZF Commercial | 533023 | ZFCVINDIA | INE342J01019 | Consumer Discretionary |
| 303 | TVS Holdings | 520056 | TVSHLTD | INE105A01035 | Financial Services |
| 304 | Welspun Living | 514162 | WELSPUNLIV | INE192B01031 | Consumer Discretionary |
| 305 | Schneider Electric Infra | 534139 | SCHNEIDER | INE839M01018 | Capital Goods |
| 306 | Garden Reach Shipbuilders | 542011 | GRSE | INE382Z01011 | Capital Goods |
| 307 | Kirloskar Oil Engines | 533293 | KIRLOSENG | INE146L01010 | Capital Goods |
| 308 | Netweb Technologies | 543945 | NETWEB | INE0NT901020 | Information Technology |
| 309 | Jyoti CNC Automation | 544081 | JYOTICNC | INE980O01024 | Capital Goods |
| 310 | Timken | 522113 | TIMKEN | INE325A01013 | Capital Goods |
| 311 | Data Patterns | 543428 | DATAPATTNS | INE0IX101010 | Capital Goods |
| 312 | Capri Global Capital | 531595 | CGCL | INE180C01042 | Financial Services |
| 313 | ACC | 500410 | ACC | INE012A01025 | Construction Materials |
| 314 | Tata Elxsi | 500408 | TATAELXSI | INE670A01012 | Information Technology |
| 315 | Gillette | 507815 | GILLETTE | INE322A01010 | FMCG |
| 316 | City Union Bank | 532210 | CUB | INE491A01021 | Financial Services |
| 317 | Kalpataru Projects International | 522287 | KPIL | INE220B01022 | Industrials |
| 318 | Belrise Industries | 544405 | BELRISE | INE894V01022 | Consumer Discretionary |
| 319 | P&G Hygiene and Health Care | 500459 | PGHH | INE179A01014 | FMCG |
| 320 | Go Digit General Insurance | 544179 | GODIGIT | INE03JT01014 | Financial Services |
| 321 | Leela Palaces Hotels & Resorts | 544408 | THELEELA | INE0AQ201015 | Consumer Services |
| 322 | Aether Industries | 543534 | AETHER | INE0BWX01014 | Chemicals |
| 323 | Allied Blenders & Distillers | 544203 | ABDL | INE552Z01027 | FMCG |
| 324 | Amber Enterprises | 540902 | AMBER | INE371P01015 | Consumer Discretionary |
| 325 | HBL Engineering | 517271 | HBLENGINE | INE292B01021 | Capital Goods |
| 326 | Great Eastern Shipping Company | 500620 | GESHIP | INE017A01032 | Services |
| 327 | SJVN | 533206 | SJVN | INE002L01015 | Utilities |
| 328 | Affle 3i | 542752 | AFFLE | INE00WC01027 | Information Technology |
| 329 | IRB Infrastructure Developers | 532947 | IRB | INE821I01022 | Industrials |
| 330 | Deepak Nitrite | 506401 | DEEPAKNTR | INE288B01029 | Chemicals |
| 331 | AWL Agri Business | 543458 | AWL | INE699H01024 | FMCG |
| 332 | Gujarat Energy | 539336 | GUJENERGY | INE844O01030 | Energy |
| 333 | NBCC | 534309 | NBCC | INE095N01031 | Industrials |
| 334 | Chennai Petroleum Corporation | 500110 | CHENNPETRO | INE178A01016 | Energy |
| 335 | RR Kabel | 543981 | RRKABEL | INE777K01022 | Capital Goods |
| 336 | Prime Focus | 532748 | PFOCUS | INE367G01038 | Media Entertainment & Publication |
| 337 | Sagility | 544282 | SAGILITY | INE0W2G01015 | Information Technology |
| 338 | Indraprastha Gas | 532514 | IGL | INE203G01027 | Energy |
| 339 | Grindwell Norton | 506076 | GRINDWELL | INE536A01023 | Capital Goods |
| 340 | Granules | 532482 | GRANULES | INE101D01020 | Healthcare |
| 341 | Firstsource Solutions | 532809 | FSL | INE684F01012 | Services |
| 342 | Pine Labs | 544606 | PINELABS | INE15B701018 | Financial Services |
| 343 | Carborundum Universal | 513375 | CARBORUNIV | INE120A01034 | Capital Goods |
| 344 | Ramco Cements | 500260 | RAMCOCEM | INE331A01037 | Construction Materials |
| 345 | Kaynes Technology India | 543664 | KAYNES | INE918Z01012 | Capital Goods |
| 346 | EIH Hotels | 500840 | EIHOTEL | INE230A01023 | Consumer Services |
| 347 | Emmvee Photovoltaic Power | 544608 | EMMVEE | INE1C6T01020 | Capital Goods |
| 348 | International Gemological Institute | 544311 | IGIL | INE0Q9301021 | Services |
| 349 | Castrol | 500870 | CASTROLIND | INE172A01027 | Energy |
| 350 | Finolex Cables | 500144 | FINCABLES | INE235A01022 | Capital Goods |
| 351 | Elgi Equipments | 522074 | ELGIEQUIP | INE285A01027 | Capital Goods |
| 352 | CAMS | 543232 | CAMS | INE596I01020 | Financial Services |
| 353 | Eris Lifesciences | 540596 | ERIS | INE406M01024 | Healthcare |
| 354 | Aadhar Housing Finance | 544176 | AADHARHFC | INE883F01010 | Financial Services |
| 355 | Kajaria Ceramics | 500233 | KAJARIACER | INE217B01036 | Consumer Discretionary |
| 356 | Brigade Enterprises | 532929 | BRIGADE | INE791I01019 | Consumer Discretionary |
| 357 | Onesource Specialty Pharma | 544292 | ONESOURCE | INE013P01021 | Healthcare |
| 358 | Caplin Point Laboratories | 524742 | CAPLIPOINT | INE475E01026 | Healthcare |
| 359 | Chalet Hotels | 542399 | CHALET | INE427F01016 | Consumer Services |
| 360 | Deepak Fertilisers & Petrochemicals | 500645 | DEEPAKFERT | INE501A01019 | Chemicals |
| 361 | Tenneco Clean Air | 544612 | TENNIND | INE19RI01016 | Consumer Discretionary |
| 362 | Emami | 531162 | EMAMILTD | INE548C01032 | FMCG |
| 363 | Engineers India | 532178 | ENGINERSIN | INE510A01028 | Industrials |
| 364 | Credit Access Grameen | 541770 | CREDITACC | INE741K01010 | Financial Services |
| 365 | Syngene International | 539268 | SYNGENE | INE398R01022 | Healthcare |
| 366 | Cohance Lifesciences | 543064 | COHANCE | INE03QK01018 | Healthcare |
| 367 | BEML | 500048 | BEML | INE258A01024 | Capital Goods |
| 368 | TBO Tek | 544174 | TBOTEK | INE673O01025 | Consumer Services |
| 369 | Aarti Industries | 524208 | AARTIIND | INE769A01020 | Chemicals |
| 370 | JSW Cement | 544480 | JSWCEMENT | INE718I01012 | Construction Materials |
| 371 | Sumitomo Chemical | 542920 | SUMICHEM | INE258G01013 | Chemicals |
| 372 | Minda Corporation | 538962 | MINDACORP | INE842C01021 | Consumer Discretionary |
| 373 | Mamaearth | 544014 | HONASA | INE0J5401028 | FMCG |
| 374 | Poly Medicure | 531768 | POLYMED | INE205C01021 | Healthcare |
| 375 | Jindal SAW | 500378 | JINDALSAW | INE324A01032 | Capital Goods |
| 376 | CESC | 500084 | CESC | INE486A01021 | Utilities |
| 377 | KFin Technologies | 543720 | KFINTECH | INE138Y01010 | Financial Services |
| 378 | Anant Raj | 515055 | ANANTRAJ | INE242C01024 | Consumer Discretionary |
| 379 | IFCI | 500106 | IFCI | INE039A01010 | Financial Services |
| 380 | PVR Inox | 532689 | PVRINOX | INE191H01014 | Media Entertainment & Publication |
| 381 | Choice International | 531358 | CHOICEIN | INE102B01014 | Financial Services |
| 382 | Natco Pharma | 524816 | NATCOPHARM | INE987B01026 | Healthcare |
| 383 | Tata Chemicals | 500770 | TATACHEM | INE092A01019 | Chemicals |
| 384 | Kansai Nerolac Paints | 500165 | KANSAINER | INE531A01024 | Consumer Discretionary |
| 385 | National Securities Depository (NSDL) | 544467 |  | INE301O01023 | Financial Services |
| 386 | Sarda Energy & Minerals | 504614 | SARDAEN | INE385C01021 | Metals & Mining |
| 387 | Indegene | 544172 | INDGN | INE065X01017 | Healthcare |
| 388 | Graphite | 509488 | GRAPHITE | INE371A01025 | Capital Goods |
| 389 | Devyani International | 543330 | DEVYANI | INE872J01023 | Consumer Services |
| 390 | Zen Technologies | 533339 | ZENTEC | INE251B01027 | Capital Goods |
| 391 | Nava | 513023 | NAVA | INE725A01030 | Utilities |
| 392 | Travel Food Services | 544443 | TRAVELFOOD | INE103V01028 | Consumer Services |
| 393 | Sammaan Capital | 535789 | SAMMAANCAP | INE148I01020 | Financial Services |
| 394 | Vardhman Textiles | 502986 | VTL | INE825A01020 | Consumer Discretionary |
| 395 | Ola Electric Mobility | 544225 | OLAELEC | INE0LXG01040 | Consumer Discretionary |
| 396 | Jammu & Kashmir Bank | 532209 | J&KBANK | INE168A01041 | Financial Services |
| 397 | Bayer Crop Science | 506285 | BAYERCROP | INE462A01022 | Chemicals |
| 398 | Triveni Turbines | 533655 | TRITURBINE | INE152M01016 | Capital Goods |
| 399 | Jubilant Pharmova | 530019 | JUBLPHARMA | INE700A01033 | Healthcare |
| 400 | PG Electroplast | 533581 | PGEL | INE457L01029 | Consumer Discretionary |
| 401 | Gujarat Mineral Development Corporation | 532181 | GMDCLTD | INE131A01031 | Metals & Mining |
| 402 | Chambal Fertilisers & Chemicals | 500085 | CHAMBLFERT | INE085A01013 | Chemicals |
| 403 | Atul | 500027 | ATUL | INE100A01010 | Chemicals |
| 404 | LT Foods | 532783 | LTFOODS | INE818H01020 | FMCG |
| 405 | Zydus Wellness | 531335 | ZYDUSWELL | INE768C01028 | FMCG |
| 406 | KPIT Technologies | 542651 | KPITTECH | INE04I401011 | Information Technology |
| 407 | eClerx Services | 532927 | ECLERX | INE738I01010 | Services |
| 408 | Godawari Power & Ispat | 532734 | GPIL | INE177H01039 | Capital Goods |
| 409 | Ramkrishna Forgings | 532527 | RKFORGE | INE399G01023 | Consumer Discretionary |
| 410 | Paradeep Phosphates | 543530 | PARADEEP | INE088F01024 | Chemicals |
| 411 | CEAT | 500878 | CEATLTD | INE482A01020 | Consumer Discretionary |
| 412 | Usha Martin | 517146 | USHAMART | INE228A01035 | Capital Goods |
| 413 | CIE Automotive | 532756 | CIEINDIA | INE536H01010 | Consumer Discretionary |
| 414 | Aditya Birla Real Estate | 500040 | ABREL | INE055A01016 | Forest Materials |
| 415 | DCM Shriram Consolidated | 523367 | DCMSHRIRAM | INE499A01024 | Diversified |
| 416 | Sobha | 532784 | SOBHA | INE671H01015 | Consumer Discretionary |
| 417 | Action Construction Equipment | 532762 | ACE | INE731H01025 | Capital Goods |
| 418 | Balrampur Chini Mills | 500038 | BALRAMCHIN | INE119A01028 | FMCG |
| 419 | Amara Raja Energy & Mobility | 500008 | ARE&M | INE885A01032 | Consumer Discretionary |
| 420 | Crompton Greaves | 539876 | CROMPTON | INE299U01018 | Consumer Discretionary |
| 421 | CCL Products | 519600 | CCL | INE421D01022 | FMCG |
| 422 | Rainbow Childrens Medicare | 543524 | RAINBOW | INE961O01016 | Healthcare |
| 423 | Gallantt Ispat | 532726 | GALLANTT | INE297H01019 | Capital Goods |
| 424 | Five Star Business Finance | 543663 | FIVESTAR | INE128S01021 | Financial Services |
| 425 | JSW Dulux | 500710 | JSWDULUX | INE133A01029 | Consumer Discretionary |
| 426 | Kirloskar Brothers | 500241 | KIRLOSBROS | INE732A01036 | Capital Goods |
| 427 | Nuvoco Vistas Corporation | 543334 | NUVOCO | INE118D01016 | Construction Materials |
| 428 | DOMS Industries | 544045 | DOMS | INE321T01012 | FMCG |
| 429 | Bikaji Foods International | 543653 | BIKAJI | INE00E101023 | FMCG |
| 430 | Zensar Technologies | 504067 | ZENSARTECH | INE520A01027 | Information Technology |
| 431 | Trident | 521064 | TRIDENT | INE064C01022 | Consumer Discretionary |
| 432 | JSW Holdings | 532642 | JSWHL | INE824G01012 | Financial Services |
| 433 | NMDC Steel | 543768 | NSLNISP | INE0NNS01018 | Metals & Mining |
| 434 | Concord Biotech | 543960 | CONCORDBIO | INE338H01029 | Healthcare |
| 435 | EID Parry | 500125 | EIDPARRY | INE126A01031 | Chemicals |
| 436 | JBM Auto | 532605 | JBMA | INE927D01051 | Consumer Discretionary |
| 437 | Signatureglobal | 543990 | SIGNATURE | INE903U01023 | Consumer Discretionary |
| 438 | Vedant Fashions | 543463 | MANYAVAR | INE825V01034 | Consumer Services |
| 439 | Cyient | 532175 | CYIENT | INE136B01020 | Information Technology |
| 440 | Home First Finance Company | 543259 | HOMEFIRST | INE481N01025 | Financial Services |
| 441 | Godrej Agrovet | 540743 | GODREJAGRO | INE850D01014 | FMCG |
| 442 | Gravita India | 533282 | GRAVITA | INE024L01027 | Metals & Mining |
| 443 | Techno Electric & Engineering | 542141 | TECHNOE | INE285K01026 | Industrials |
| 444 | UTI AMC | 543238 | UTIAMC | INE094J01016 | Financial Services |
| 445 | Mahanagar Gas | 539957 | MGL | INE002S01010 | Energy |
| 446 | JM Financial | 523405 | JMFINANCIL | INE780C01023 | Financial Services |
| 447 | PCBL Chemical | 506590 | PCBL | INE602A01031 | Chemicals |
| 448 | Blue Dart Express | 526612 | BLUEDART | INE233B01017 | Services |
| 449 | Whirlpool | 500238 | WHIRLPOOL | INE716A01013 | Consumer Discretionary |
| 450 | Can Fin Homes | 511196 | CANFINHOME | INE477A01020 | Financial Services |
| 451 | Inox Wind | 539083 | INOXWIND | INE066P01011 | Capital Goods |
| 452 | Indian Energy Exchange | 540750 | IEX | INE022Q01020 | Financial Services |
| 453 | Ircon International | 541956 | IRCON | INE962Y01021 | Industrials |
| 454 | Elecon Engineering Company | 505700 | ELECON | INE205B01031 | Capital Goods |
| 455 | India Cements | 530005 | INDIACEM | INE383A01012 | Construction Materials |
| 456 | Titagarh Rail Systems | 532966 | TITAGARH | INE615H01020 | Capital Goods |
| 457 | Lemon Tree Hotels | 541233 | LEMONTREE | INE970X01018 | Consumer Services |
| 458 | Aptus Value Housing Finance | 543335 | APTUS | INE852O01025 | Financial Services |
| 459 | Jaiprakash Power Ventures | 532627 | JPPOWER | INE351F01018 | Utilities |
| 460 | Aditya Birla Lifestyle Brands | 544403 | ABLBL | INE14LE01019 | Consumer Services |
| 461 | IndiaMART InterMesh | 542726 | INDIAMART | INE933S01016 | Consumer Services |
| 462 | Jubilant Ingrevia | 543271 | JUBLINGREA | INE0BY001018 | Chemicals |
| 463 | BLS International Services | 540073 | BLS | INE153T01027 | Consumer Services |
| 464 | HEG Advanced Materials | 509631 | HEGAM | INE545A01024 | Capital Goods |
| 465 | Firstcry (Brainbees Solutions) | 544226 | FIRSTCRY | INE02RE01045 | Consumer Services |
| 466 | RITES | 541556 | RITES | INE320J01015 | Industrials |
| 467 | Transformers & Rectifiers | 532928 | TARIL | INE763I01026 | Capital Goods |
| 468 | Finolex Industries | 500940 | FINPIPE | INE183A01024 | Capital Goods |
| 469 | Aavas Financiers | 541988 | AAVAS | INE216P01012 | Financial Services |
| 470 | Bombay Burmah Trading | 501425 | BBTC | INE050A01025 | FMCG |
| 471 | Jupiter Wagons | 533272 | JWL | INE209L01016 | Capital Goods |
| 472 | Birlasoft | 532400 | BSOFT | INE836A01035 | Information Technology |
| 473 | KEC International | 532714 | KEC | INE389H01022 | Industrials |
| 474 | NCC | 500294 | NCC | INE868B01028 | Industrials |
| 475 | Olectra Greentech | 532439 | OLECTRA | INE260D01016 | Consumer Discretionary |
| 476 | Cello World | 544012 | CELLO | INE0LMW01024 | Consumer Discretionary |
| 477 | Bata | 500043 | BATAINDIA | INE176A01028 | Consumer Discretionary |
| 478 | Afcons Infrastructure | 544280 | AFCONS | INE101I01011 | Industrials |
| 479 | Railtel Corporation of India | 543265 | RAILTEL | INE0DD101019 | Telecom |
| 480 | Intellect Design Arena | 538835 | INTELLECT | INE306R01017 | Information Technology |
| 481 | Clean Science & Technology | 543318 | CLEAN | INE227W01023 | Chemicals |
| 482 | Reliance Power | 532939 | RPOWER | INE614G01033 | Utilities |
| 483 | Medplus Health Services | 543427 | MEDPLUS | INE804L01022 | Consumer Services |
| 484 | Tejas Networks | 540595 | TEJASNET | INE010J01012 | Telecom |
| 485 | Swan Corp | 503310 | SWANCORP | INE665A01038 | Diversified |
| 486 | Jyothy Laboratories | 532926 | JYOTHYLAB | INE668F01031 | FMCG |
| 487 | RHI Magnesita | 534076 | RHIM | INE743M01012 | Capital Goods |
| 488 | Embassy Developments | 532832 | EMBDL | INE069I01010 | Consumer Discretionary |
| 489 | Gujarat Narmada Valley Fert & Chem | 500670 | GNFC | INE113A01013 | Chemicals |
| 490 | Maharashtra Seamless | 500265 | MAHSEAMLES | INE271B01025 | Capital Goods |
| 491 | Sapphire Foods | 543397 | SAPPHIRE | INE806T01020 | Consumer Services |
| 492 | Sonata Software | 532221 | SONATSOFTW | INE269A01021 | Information Technology |
| 493 | JK Lakshmi Cement | 500380 | JKLAKSHMI | INE786A01032 | Construction Materials |
| 494 | Cera Sanitaryware | 532443 | CERA | INE739E01017 | Consumer Discretionary |
| 495 | Newgen Software Technologies | 540900 | NEWGEN | INE619B01017 | Information Technology |
| 496 | Rashtriya Chemicals & Fertilizers | 524230 | RCF | INE027A01015 | Chemicals |
| 497 | Gujarat State Fertilizers & Chemicals | 500690 | GSFC | INE026A01025 | Chemicals |
| 498 | CE Info Systems | 543425 | MAPMYINDIA | INE0BV301023 | Information Technology |
| 499 | Aditya Birla Fashion & Retail | 535755 | ABFRL | INE647O01011 | Consumer Services |
| 500 | Latent View Analytics | 543398 | LATENTVIEW | INE0I7C01011 | Information Technology |
