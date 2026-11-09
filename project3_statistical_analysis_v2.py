#!/usr/bin/env python3
"""Project 3 V2: frozen, audit-gated, receipt-time event/control analysis.

Requires project3_matched_comparison_v1.py in the same directory (already installed
on the research VM). Inputs must be observed_seconds.csv files accompanied by
PASS_FULL event_report.json files from project3_release_response_v1.py.

Read-only toward all input data. Outputs into --outdir. Python 3.10+ stdlib.
No statistical significance or causal impact is estimated from one control day.

Example (November 8, only exploratory events exist):
 python3 project3_statistical_analysis_v2.py \\
   --case nov05=research/project3_nov05/observed_seconds.csv \\
   --case nov06=research/project3_nov06/observed_seconds.csv \\
   --outdir research/project3_protocol_v2

Later add:
   --case nov09_control=research/project3_nov09/observed_seconds.csv \\
   --case nov10_cpi=research/project3_nov10/observed_seconds.csv
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median, fmean
import sys

from project3_matched_comparison_v1 import load, summarize, window_metric

PROTOCOL_ID = 'project3_fixed_outcomes_2026-11-08_v2'
EVENTS = {
    'nov05': {'date': '2026-11-05', 'role': 'exploratory_event',
              'name': 'Q3 2026 productivity and costs'},
    'nov06': {'date': '2026-11-06', 'role': 'exploratory_event',
              'name': 'October 2026 employment situation'},
    'nov09_control': {'date': '2026-11-09', 'role': 'candidate_control',
                      'name': '13:30 UTC non-BLS-release reference; Fed remarks 13:40 UTC'},
    'nov10_cpi': {'date': '2026-11-10', 'role': 'prospective_event',
                  'name': 'October 2026 CPI + Real Earnings, simultaneous BLS releases'},
}
METRICS = (
    ('release_mean_spread_bps', 'high'),
    ('release_median_total10_btc', 'low'),
    ('release_abs_mid_return_tplus5_bps', 'high'),
)
BASELINE = range(-600, -60)  # -600..-61 inclusive
PRE_MINUTE = range(-60, 0)
PRE24 = range(-24, 0)
RELEASE = range(0, 6)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def expected_timestamp(label):
    return EVENTS[label]['date'] + 'T13:30:00+00:00'


def check_provenance(path: Path, label: str, event_utc: str) -> tuple[dict, Path]:
    report_path = path.parent/'event_report.json'
    if not report_path.exists():
        raise ValueError(f'{label}: missing {report_path}; build from PASS_FULL replay first')
    rpt = json.loads(report_path.read_text(encoding='utf-8'))
    if rpt.get('audit_status') != 'PASS_FULL':
        raise ValueError(f'{label}: event_report audit_status is not PASS_FULL')
    audit_count = rpt.get('audit_updates_checked')
    replay_count = (rpt.get('replay') or {}).get('updates_replayed')
    if not isinstance(audit_count, int) or audit_count < 1 or audit_count != replay_count:
        raise ValueError(f'{label}: full-checksum count and replay count disagree')
    if rpt.get('event_utc') != event_utc:
        raise ValueError(f'{label}: event_report UTC {rpt.get("event_utc")} != CSV {event_utc}')
    if event_utc != expected_timestamp(label):
        raise ValueError(f'{label}: registered 13:30 UTC event time mismatch')
    return rpt, report_path


def missing_ranges(rows: dict, lo: int, hi: int) -> list[tuple[int,int]]:
    gaps = []
    beginning = None
    for t in range(lo, hi + 2):
        absent = t <= hi and t not in rows
        if absent and beginning is None:
            beginning = t
        if not absent and beginning is not None:
            gaps.append((beginning, t - 1))
            beginning = None
    return gaps


def valid_path(rows: dict, horizon: int) -> bool:
    return all(k in rows for k in range(-1, horizon + 1))


def quote_return(rows: dict, horizon: int):
    if not valid_path(rows, horizon):
        return None
    return 10000 * math.log(rows[horizon]['mid'] / rows[-1]['mid'])


def mean_of(rows, offsets, field):
    vals = [rows[k][field] for k in offsets if k in rows]
    return fmean(vals) if vals else None


def med_of(rows, offsets, field):
    vals = [rows[k][field] for k in offsets if k in rows]
    return median(vals) if vals else None


def ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def changed(a, b):
    return a-b if a is not None and b is not None else None


def additional_metrics(rows: dict, base: dict) -> dict:
    nbase = sum(k in rows for k in BASELINE)
    nminute = sum(k in rows for k in PRE_MINUTE)
    npre24 = sum(k in rows for k in PRE24)
    pre_eligible = nbase / len(BASELINE) >= 0.95 and nminute / len(PRE_MINUTE) >= .95 and npre24 == 24
    base_depth = med_of(rows, BASELINE, 'depth') if pre_eligible else None
    pre24_depth = med_of(rows, PRE24, 'depth') if pre_eligible else None
    base_spread = med_of(rows, BASELINE, 'spread') if pre_eligible else None
    pre24_spread = median([rows[k]['spread'] for k in PRE24]) if pre_eligible else None
    gap_ranges = missing_ranges(rows, -600, 900)
    first_gap_after = next(((a,b) for a,b in gap_ranges if a >= 0), None)
    return {
        'pre_24_depth_eligible': pre_eligible,
        'baseline_median_depth10_btc': base_depth,
        'pre24_median_depth10_btc': pre24_depth,
        'pre24_depth_ratio_to_baseline': ratio(pre24_depth, base_depth),
        'pre24_depth_change_pct': 100 * (ratio(pre24_depth,base_depth)-1) if ratio(pre24_depth,base_depth) is not None else None,
        'baseline_median_spread_bps': base_spread,
        'pre24_median_spread_bps': pre24_spread,
        'pre24_spread_ratio_to_baseline': ratio(pre24_spread,base_spread),
        'release_spread_ratio_to_baseline_median': ratio(base.get('release_mean_spread_bps'), base_spread),
        'release_depth_ratio_to_baseline_median': ratio(base.get('release_median_total10_btc'), base_depth),
        'mid_signed_return_tplus5_bps': quote_return(rows, 5),
        'mid_signed_return_tplus30_bps': quote_return(rows, 30),
        'mid_signed_return_tplus60_bps': quote_return(rows, 60),
        'mid_signed_return_tplus120_bps': quote_return(rows, 120),
        'full_path_tplus60': valid_path(rows,60),
        'full_path_tplus120': valid_path(rows,120),
        'missing_seconds_minus600_to_plus900': sum(b-a+1 for a,b in gap_ranges),
        'gap_ranges': gap_ranges,
        'first_postrelease_gap': first_gap_after,
        'post_first_gap_replay_caution': first_gap_after is not None,
    }


def write_csv(path: Path, records: list[dict]):
    if not records:
        return
    fields = list(dict.fromkeys(k for row in records for k in row))
    with path.open('w',encoding='utf-8',newline='') as fh:
        wr = csv.DictWriter(fh,fieldnames=fields,extrasaction='ignore')
        wr.writeheader()
        wr.writerows(records)


def parse_cases(items: list[str]) -> dict[str,Path]:
    result={}
    for item in items:
        if '=' not in item:
            raise ValueError('Each --case must be registered_label=/path/to/observed_seconds.csv')
        label, loc = item.split('=',1)
        if label not in EVENTS:
            raise ValueError(f'Unregistered label {label!r}; changing the registry requires versioned amendment')
        if label in result or not loc.strip():
            raise ValueError(f'Duplicate or empty case: {label}')
        result[label] = Path(loc).resolve()
    return result


def analyze_cases(cases: dict[str,Path]) -> tuple[list[dict],list[dict],dict]:
    outputs=[]
    provenance=[]
    gaps={}
    control=None
    for label, path in cases.items():
        if not path.is_file():
            raise FileNotFoundError(f'{label}: {path} not found')
        rows, evt=load(path)
        if evt != expected_timestamp(label):
            raise ValueError(f'{label}: CSV t0={evt}, expected {expected_timestamp(label)}')
        report, report_path = check_provenance(path,label,evt)
        summary=summarize(label,path,rows,evt)
        extra=additional_metrics(rows, summary)
        rec={
            'case':label,
            'role':EVENTS[label]['role'],
            'event_description':EVENTS[label]['name'],
            'event_utc':evt,
            'protocol_id':PROTOCOL_ID,
            **{k: v for k,v in summary.items() if k not in ('case','file','reference_utc')},
            **{k:v for k,v in extra.items() if k not in ('gap_ranges','first_postrelease_gap')},
        }
        # A 39-second gap after the first minute does not invalidate primary +5s results.
        outputs.append(rec)
        gaps[label] = {'missing_ranges':extra['gap_ranges'],
                       'first_postrelease_gap': extra['first_postrelease_gap']}
        provenance.append({
            'case':label,'csv_path':str(path),'csv_sha256':sha256_file(path),
            'event_report_path':str(report_path),'event_report_sha256':sha256_file(report_path),
            'manifest_path_recorded':report.get('input_manifest'),
            'audit_path_recorded':report.get('input_audit'),
            'audit_status':report.get('audit_status'),
            'audit_updates_checked':report.get('audit_updates_checked'),
            'replay_updates':report['replay'].get('updates_replayed'),
            'role':EVENTS[label]['role'],
        })
        print(f"{label}: {('ELIGIBLE' if rec['eligible_primary'] else 'INELIGIBLE')} "
              f"coverage(-600:-61)={rec['baseline_coverage_pct']}% "
              f"coverage(-60:-1)={rec['pre60_coverage_pct']}% "
              f"coverage(-1:+5)={rec['release_anchor_and_0to5_coverage_pct']}%")
        print('  spread',rec['release_mean_spread_bps'],'depth',rec['release_median_total10_btc'],
              'abs_5s_return',rec['release_abs_mid_return_tplus5_bps'],
              'pre24_depth_ratio',rec['pre24_depth_ratio_to_baseline'])
        if label == 'nov09_control': control = rec
    return outputs,provenance,gaps


def control_comparisons(reports: list[dict]) -> list[dict]:
    control=next((x for x in reports if x['case']=='nov09_control'),None)
    if not control:
        return []
    results=[]
    for r in reports:
        if r['case']=='nov09_control':continue
        for name, direction in METRICS + (('pre24_depth_ratio_to_baseline','low'),):
            x,y=r.get(name),control.get(name)
            valid=(r['eligible_primary'] and control['eligible_primary'] and
                   x is not None and y is not None)
            results.append({
                'case':r['case'], 'case_role':r['role'], 'control':'nov09_control',
                'metric':name,'event_value':x if valid else None,
                'control_value':y if valid else None,
                'event_minus_control':changed(x,y) if valid else None,
                'event_div_control':ratio(x,y) if valid else None,
                'comparison_valid':valid,
                'direction_of_extremeness':direction,
                'interpretation':'single-day descriptive contrast; NOT a p-value or causal estimate',
            })
    return results


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case',action='append',required=True,metavar='LABEL=CSV')
    p.add_argument('--outdir',type=Path,default=Path('research/project3_analysis_v2'))
    args=p.parse_args()
    try:
        cases=parse_cases(args.case)
        output=args.outdir.resolve()
        if any(output==source.parent or output in source.parents for source in cases.values()):
            raise ValueError('--outdir must not overlap a source recording folder')
        reports,provenance,gaps=analyze_cases(cases)
        controls=control_comparisons(reports)
        output.mkdir(parents=True,exist_ok=True)
        write_csv(output/'case_metrics.csv',reports)
        write_csv(output/'source_provenance.csv',provenance)
        if controls: write_csv(output/'single_control_contrasts.csv',controls)
        analysis={
            'protocol_id':PROTOCOL_ID,
            'protocol_freeze_date_utc':'2026-11-08',
            'protocol_status':'definitions selected after Nov 5/6 exploration; prospective for later sessions only if committed before they occur',
            'primary_metrics':[m for m,_ in METRICS],
            'primary_window':'six receipt-second buckets [0,+5], with last quote of [-1] as midpoint-return anchor',
            'reference':'99 non-overlapping 6s windows [-594,-1] within same session, descriptive only',
            'eligibility':'PASS_FULL replay + >=95% baseline and final minute coverage + complete [-1,+5]',
            'control_selection':'Nov 9 candidate, 13:30 UTC, no known simultaneous scheduled BLS release; Fed Bowman at 13:40 UTC; exclude t>=+600',
            'case_results':reports,
            'provenance':provenance,
            'missing_ranges':gaps,
            'single_day_control_contrasts':controls,
            'interpretation_limits':[
                'No statistical p-values: 99 within-day windows are not independent event-level replicates',
                'No causal attribution: same-clock comparison with one control day is descriptive',
                'No surprise-sign analysis without archived pre-release consensus and actual release data',
                'CPI and Real Earnings occur simultaneously on Nov 10; response cannot isolate CPI alone',
                'UTC local-receipt time buckets are not true synchronized exchange-time snapshots',
                'Clock reports NTP sync but no independently measured sub-second clock offset',
                'CRC32 validates top 10 L2 levels per Kraken spec, not proof of complete capture or all 100 levels',
                'After an unexplained raw receive gap, continuous book-path claims are not supported without resnapshot',
                'No transaction/fees/slippage/queue modeling, execution backtest, alpha or expected profitability',
            ],
        }
        (output/'analysis_report.json').write_text(json.dumps(analysis,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        with (output/'analysis_source_hashes.sha256').open('w',encoding='utf-8') as fh:
            for item in provenance:
                fh.write(f"{item['csv_sha256']}  {item['csv_path']}\n")
                fh.write(f"{item['event_report_sha256']}  {item['event_report_path']}\n")
        print('SAME-CLOCK CONTROL:', 'nov09_control descriptive only' if controls else 'not collected yet')
        print('OUTPUT:', output)
        print('NOTES: Historical Nov05/06 are exploratory; no day-level inference; no execution claims.')
    except (ValueError,FileNotFoundError,KeyError) as e:
        print('ERROR:', e,file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__':
    main()
