# Project 3: statistics framework v2 — runbook

Files in the accompanying package:

- `PROJECT3_FROZEN_PROTOCOL_2026-11-08.md`: hypotheses, fixed metrics, gates, calendar controls, analysis hierarchy, caveats.
- `project3_statistical_analysis_v2.py`: reproducible audit-gated second-level analyzer. **Requires the existing** `project3_matched_comparison_v1.py` beside it on the Azure VM.
- `test_project3_statistical_analysis_v2.py`: synthetic Python unittest suite (no Kraken data needed).

## Use now (Nov 8)

Place the v2 script and test in `~/kraken_project3/`, beside the existing v1 script, then:

```bash
cd ~/kraken_project3
python3 -m unittest -v test_project3_statistical_analysis_v2.py
python3 project3_statistical_analysis_v2.py \
  --case nov05=research/project3_nov05/observed_seconds.csv \
  --case nov06=research/project3_nov06/observed_seconds.csv \
  --outdir research/project3_framework_v2
```

This is read-only toward source data. It should report both as `ELIGIBLE`, and write protocol-v2 metrics, provenance hashes and coverage/gap diagnostics. It will **not** claim same-clock controls exist today.

## Add controls after collection and checksum validation

Create a full-audit report and an `observed_seconds.csv` for **the segment containing 13:30 UTC**, using the existing v1 replay script with `--event-utc 2026-11-09T13:30:00Z` for the control day and `2026-11-10T13:30:00Z` for the CPI/Real Earnings day. Output to distinct folders, e.g. `research/project3_nov09` and `research/project3_nov10`. Then rerun the v2 analyzer adding:

```bash
  --case nov09_control=research/project3_nov09/observed_seconds.csv \
  --case nov10_cpi=research/project3_nov10/observed_seconds.csv
```

Do not invoke these two cases before those files exist. There is no need to rerun or alter the old recordings today.

## Archive protocol integrity before tomorrow

```bash
cd ~/kraken_project3
sha256sum project3_statistical_analysis_v2.py \
  project3_matched_comparison_v1.py \
  PROJECT3_FROZEN_PROTOCOL_2026-11-08.md \
  | tee project3_protocol_hashes_2026-11-08.sha256
```

Store that hash file in a dated Git commit or another independently timestamped archive. This makes the prospective portion more credible. Merely claiming a file was written on Nov 8 is not independently verifiable.

**Constraints:** No p-values with one control session; November 5/6 are exploratory; November 9 is a candidate control with a known Fed event at 13:40 UTC; November 10 includes simultaneous CPI and Real Earnings; receipt-second midquotes are not executions.
