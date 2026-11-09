# Project 3 — Fixed analysis protocol (v2)

**Working title:** Information Diffusion and Displayed Liquidity Dynamics Around Scheduled U.S. Economic Releases in Kraken BTC/USD

**Protocol authored:** 2026-11-08 (UTC; before the planned 2026-11-09 control recording and 2026-11-10 CPI recording)

**Research classification:** exploratory observational microstructure event study. This is **not** peer reviewed, an econometric causal design, a trading strategy, or proof of predictable returns.

**Transparency:** The November 5 and November 6 recordings and their findings **had already been examined** when the measures and inclusion rules below were selected. Those two sessions are retrospective/exploratory, not preregistered observations. The same rules are intended to be fixed for the November 9 and November 10 sessions, subject to publicly dated versioned amendments. A file's authored date alone is not proof it was frozen before collection; commit/archive its cryptographic hash now.

## 1. Research questions and hypotheses

- **H1 (release-time spread):** Mean displayed best-bid/ask spread in the first six receipt-time seconds ([0,+5]) is greater on macro-release days than at the same time on pre-screened non-release days.
- **H2 (release-time depth):** Median sum of displayed top-ten-level bid/ask depth (BTC) in [0,+5] is lower on macro-release days than at the same time on non-release days.
- **H3 (price response):** Absolute BTC/USD midpoint log return between the **last observed quote in second −1** and the **last observed quote in second +5** is larger on macro-release days than on non-release days.
- **Secondary H4 (anticipatory behavior):** The median top-ten-level depth in seconds [−24,−1], divided by the median in [−600,−61], is lower on scheduled release days than on control days. This assesses changes **before** the release, rather than presuming the release triggered all of the liquidity reduction.

H1–H3 are the fixed primary measurement family; H4 is a prespecified **secondary descriptive** comparison. They reflect prior Nov 5–6 inspection, so no post-hoc claims of independent hypothesis confirmation are permitted on those two events.

## 2. Event registry and clock alignment

| Case ID | UTC anchor | Role | Concurrent timing/contamination note |
|---|---|---|---|
| `nov05` | 2026-11-05 13:30:00 | Retrospective exploratory release | Q3 preliminary Productivity and Costs |
| `nov06` | 2026-11-06 13:30:00 | Retrospective exploratory release | October Employment Situation |
| `nov09_control` | 2026-11-09 13:30:00 | Candidate control | No BLS release at that time; Fed official discussion at 13:40 UTC (= t+600), so do not use t≥+600 as a clean control response |
| `nov10_cpi` | 2026-11-10 13:30:00 | New prospective release | CPI and Real Earnings are scheduled **simultaneously**, so a response cannot be isolated to CPI alone |

Calendar sources, checked 2026-11-08: [BLS selected releases](https://www.bls.gov/schedule/2026/11_sched_list.htm); [Federal Reserve Nov 2026 calendar](https://www.federalreserve.gov/newsevents/2026-november.htm). Calendar screening must be rechecked for late schedule changes and non-BLS announcements before treating `nov09_control` as clean.

- All clocks in UTC. The recorder provides **local UTC receipt timestamps**, not a physical exchange-clock event arrival timestamp. Each feature uses the **last reconstructed order book message received within the indicated second**; do not interpret the bucket as the order book *exactly* on the second boundary.
- Depth is Kraken BTC/USD Spot WS v2, **100 displayed levels recorded**, but the provider CRC32 book checksum checks the **top 10** levels. There are no order IDs or participant identities.
- Segment boundaries are book-state resets; do not carry state across segments. A fresh subscription snapshot is needed for reconstruction following a reset.

## 3. Eligibility and data-integrity gates

**Primary eligible** only if all hold:

1. The exact event-containing segment's all-update CRC32 audit is `PASS_FULL` (full update count, no CRC or crossed-book error, and zero clock-regression warnings for these cases), and the independently produced event report replay count equals that audited count.
2. Replayed `observed_seconds.csv` timestamps align with the case's frozen UTC anchor. No duplicate second and no non-finite spread, depth, or price.
3. At least **95%** of receipt seconds are observed in the baseline interval [−600,−61] and final pre-release minute [−60,−1].
4. **Every receipt second from −1 through +5 inclusive** is observed for the release-window measurement. Never carry forward an unobserved book second.

Interpretation of `PASS_FULL`: every *recorded* book update has checksum-consistent top-ten state. It is **not** evidence of a perfectly complete feed across silence or proof of 100-level depth integrity following any undiagnosed gap.

Report all missing-second ranges within [−600,+900]. For +30, +60, +120 supplemental returns, require **all** receipt seconds from −1 to the horizon. Missing path segments disqualify continuous-path analyses. After an unexplained raw feed gap, quarantine post-gap *continuous* book path estimates until verified resnapshot / new segment; do not bridge the gap even if both endpoints exist.

The known November 6 raw gap is t+264…t+302 inclusive (39 absent complete seconds). It does **not** overlap the required primary or +120-second analysis windows, but invalidates a continuous +300-second path. Avoid attributing the interruption to Kraken or Azure without additional evidence.

## 4. Frozen variables and calculations

- **Spread (bps)** per second = 10,000 × (best ask − best bid) / midquote. H1 = **arithmetic mean** of seconds 0,1,2,3,4,5.
- **Displayed top-ten depth (BTC)** per second = sum of quantities on the best ten bid levels and best ten ask levels. H2 = **median** of seconds 0…5.
- **Midquote** per second = (best bid + best ask)/2. H3 = **absolute** 10,000 × ln(mid(+5)/mid(−1)). Keep signed return separately for interpretation.
- **Pre-release depth ratio (H4)** = median(depth(−24…−1)) / median(depth(−600…−61)). Only available if the full 24 pre-release seconds exist and the usual 95% baseline/last-minute conditions pass. Also retain the pre-release spread ratio as descriptive diagnostics.
- **Secondary path returns** = signed midquote log returns to +30, +60, and +120, but only if every intermediate second from −1 onward is observed.
- **Within-session reference** = 99 non-overlapping six-second windows starting at −594,−588,…,−6; each requires its immediately prior quote. These were used already in exploratory studies. The proportion exceeding an event value is a **descriptive rank only**; these blocks are not 99 independent event replicates.
- **Same-clock control** = at 13:30 UTC on Nov 9, using identical measurement formulas and coverage criteria, subject to calendar contamination screening. Raw between-day differences are descriptive only. A single control day cannot support robust variance estimation or causal attribution.

## 5. Fixed analysis hierarchy

**Stage A — present (Nov 5–6 only):** Describe pre-release depth shift, [0,+5] spread, depth, absolute/signed midpoint return, within-session reference ranks; explicitly mark as in-sample exploration. No significance tests.

**Stage B — after Nov 9:** Run independent all-update checksum validation and replay of Nov 9 event-containing segment (UTC 13:30 anchor). Produce one additional control-day measurement and simple Nov 5/6-minus-Nov 9 contrasts. No p-values; verify the Fed speech at t+600 does not contaminate chosen windows. Classify the day as a *candidate control*, not clean by assertion.

**Stage C — after Nov 10:** Independently audit/replay the CPI/Real Earnings concurrent release segment and run the identical code without changing formulas based on results. Compare new event, old exploratory releases and candidate control. Keep Nov 10 outcomes prospective **only if** the protocol was timestamp-archived before the recording and not revised in response to those outcomes.

**Stage D — before statistical inference:** Collect sufficiently many **independent event dates** and **independent, calendar-screened control dates** at matched UTC anchors (preferably matched on weekday, volatility regime, and market conditions); avoid selecting controls using future outcome information. Analyze uncertainty clustered/resampled by **day or event**, not by raw book messages or overlapping seconds. Predefine a multiplicity-adjustment approach (e.g., Holm across H1–H3) only once a defensible event-level testing design is available. This stage is **not implemented** by the current script and must not be misrepresented as completed.

**Prospective sensitivity checks (descriptive until Stage D):** [0,+2] vs [0,+5] response horizons; median versus mean spread; depth at top 1 versus top 10; signed versus absolute midpoint returns; alternative pre-release baselines ([−300,−61], [−600,−61]); comparisons to matched non-release times; filtering days with overlapping announcements or network anomalies. Label all alternative specifications separately; do not quietly substitute a more favorable one.

## 6. Source provenance and reproducibility

- Never alter original compressed JSONL, `.partial` files or manifests. Protect recording artifacts and report data gaps transparently.
- Run `validate_kraken_l2_checksums_v2.py --full --segment N` first for the relevant event-containing segment. A sampled CRC run is insufficient.
- Run `project3_release_response_v1.py` with the frozen 13:30 UTC date and event-containing segment; keep its `event_report.json` alongside `observed_seconds.csv`.
- Run `project3_statistical_analysis_v2.py` with registered labels. It requires matching `event_report.json`, checks audit/replay counts and timestamp anchor, then generates `case_metrics.csv`, `source_provenance.csv`, `analysis_report.json`, `analysis_source_hashes.sha256`, and a `single_control_contrasts.csv` only when the control is included.
- Archive SHA-256 of this protocol and both analysis scripts **now**; if possible, commit the protocol and code to version control before collecting new data. Log any protocol amendment with date, changed line, motivation, and affected endpoints.
- Source scripts and tests compile on Python 3.10+ with only the standard library. Synthetic test fixtures **do not** establish correctness on unshared raw user files; actual full checks are run on the Azure VM.

## 7. Threats to validity and claims not warranted

- **Causality:** Coinciding macro releases and book changes are not a randomized experiment; simultaneous announcements, other news, leverage unwinds, and general risk-on/risk-off flows are potential confounders.
- **Event surprises:** Do not infer expected-vs-actual news surprise from the direction of the BTC move. Forecast/actual/revision values require archived, time-stamped independent data; not part of the current primary model.
- **Clock latency:** NTP reports synchronized host time but does not independently establish microsecond timing accuracy. Release gaps are spacings between recorded messages, not exchange-to-collector latencies.
- **Liquidity:** Posted order quantities can be cancelled before a trade. Depth in top ten levels is not executable liquidity or proven trading capacity.
- **Statistics:** Millions of messages do not create millions of independent macro events. No inferential p-value is computed with one or two events and one control day.
- **Trading:** Midquote price changes omit fees, spreads paid, queue priority, latency, slippage, rejected orders and adverse selection; no profitability conclusion follows.

## 8. Paper outline (when additional independent events exist)

1. Abstract and research question
2. Kraken book data acquisition and integrity audit
3. Clock alignment and event-calendar registry
4. Pre-specified event-study variables / eligibility
5. Event-level descriptive outcomes and raw path gaps
6. Same-clock and multi-date controls
7. Day/event clustered inference, uncertainty and robustness (only after data permit)
8. Limitations, reproducibility, ethics / non-execution caveat
9. Appendices: manifests, checksum summaries, software hashes, release calendars, excluded windows

**Recommended factual abstract language for now:** “We describe receipt-time BTC/USD order-book response around two scheduled November 2026 U.S. macroeconomic releases and document a large short-horizon spread and midquote movement on November 6. Our initial results are descriptive and do not establish causality, statistical replication, or executable returns.”
