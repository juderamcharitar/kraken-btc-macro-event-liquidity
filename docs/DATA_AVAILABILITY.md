# Data availability and publication policy

**Public edition:** excludes full-resolution per-second `observed_seconds.csv` data, detailed session event-report JSON files, original CRC32 audit files, gzip order-book recordings, raw partial segments, original recording manifests, and source-provenance files that reveal private host paths. The privately retained original archive remains unchanged.

**What is included:** methodology, open-source-readable code without a license grant, synthetic tests, five previously derived research figures, aggregate four-case metrics, and 13:30 UTC single-control contrasts.

**Why:** Kraken's API information specifies that certain commercial or otherwise non-personal use of public market data requires permission. API access does not alone authorize redistribution of snapshots or derived historical feeds. See https://docs.kraken.com/api/docs/guides/global-intro/ and contact marketdata@kraken.com for approval as needed. This is a conservative distribution choice rather than a legal determination that the withheld data are prohibited.

**Reproducibility limitation:** the public distribution can check the original frozen source-code hashes and synthetic tests and independently verify that published aggregate values are internally consistent. It **cannot** repeat the empirical analysis, CRC32 audits, or regenerate event-time traces without the private original data. The raw capture and audit claims are reported research results, not independently reconstructed by a third party from public materials.

**Preserved chronology:** original frozen protocol commit `fc51959aba9e4c242547f6001ebb3058dc6b71c3` at 2026-11-09 00:55:44 UTC, before the Nov 9 and 10 collector sessions.
