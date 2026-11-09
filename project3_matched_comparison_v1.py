#!/usr/bin/env python3
"""Project 3: reproducible same-clock-time Kraken L2 comparisons (v1).

Inputs are outputs of project3_release_response_v1.py, which requires prior
PASS_FULL CRC32 validation of each event segment. This tool NEVER reads or
modifies raw recordings. No packages beyond Python 3.10+ stdlib required.

Protocol date: 2026-11-08. The metric and benchmark choices reflect prior
inspection of Nov 5/6 and are therefore NOT preregistered for those two days.
For future control/CPI observations, keep these definitions fixed.

Example (available today):
  python3 project3_matched_comparison_v1.py \
    --case nov05=research/project3_nov05/observed_seconds.csv \
    --case nov06=research/project3_nov06/observed_seconds.csv \
    --outdir research/project3_comparison

After processing Nov 9 as a placebo release at 13:30 UTC and Nov 10 CPI:
  python3 project3_matched_comparison_v1.py \
    --case nov05=research/project3_nov05/observed_seconds.csv \
    --case nov06=research/project3_nov06/observed_seconds.csv \
    --case nov09_control=research/project3_nov09/observed_seconds.csv \
    --case nov10_cpi=research/project3_nov10/observed_seconds.csv \
    --control nov09_control \
    --outdir research/project3_comparison

No statistical significance, causality, event-specific effect, or P&L claim.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
from statistics import fmean, median
from datetime import datetime, timezone

PRIMARY = (
    'release_mean_spread_bps',
    'release_median_total10_btc',
    'release_abs_mid_return_tplus5_bps',
)
RELEASE_SECONDS = tuple(range(0, 6))
PRE_REFERENCE = tuple(range(-600, -60))
PRE_LAST_MINUTE = tuple(range(-60, 0))
FINAL_24_SECONDS = tuple(range(-24, 0))
REF_STARTS = tuple(range(-594, 0, 6))  # 99 disjoint windows, -594..-1; -595 reserved for prior quote
FIELDS = {'second_utc','event_offset_s','mid','spread_bps','total10_btc'}


def finite_float(value, label):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f'{label} must be finite')
    return x


def load(path: Path):
    rows = {}
    event_epoch = None
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        reader = csv.DictReader(fh)
        missing = FIELDS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'{path}: missing fields {sorted(missing)}')
        for line, raw in enumerate(reader,2):
            off = int(raw['event_offset_s'])
            if off in rows:
                raise ValueError(f'{path}: duplicate offset {off} at line {line}')
            dt = datetime.fromisoformat(raw['second_utc'].replace('Z','+00:00'))
            if dt.tzinfo is None:
                raise ValueError('UTC offset required')
            ts = dt.astimezone(timezone.utc).timestamp()
            if not ts.is_integer():
                raise ValueError(f'{path}: second timestamp not integral at line {line}')
            candidate = int(ts)-off
            if event_epoch is None:
                event_epoch = candidate
            elif candidate != event_epoch:
                raise ValueError(f'{path}: inconsistent release offset at line {line}')
            mid = finite_float(raw['mid'],'mid')
            spread = finite_float(raw['spread_bps'],'spread_bps')
            depth = finite_float(raw['total10_btc'],'total10_btc')
            if mid<=0 or spread<0 or depth<0:
                raise ValueError(f'{path}: invalid nonpositive midpoint or negative depth/spread')
            rows[off]={'mid':mid,'spread':spread,'depth':depth}
    if not rows:
        raise ValueError(f'{path}: empty data')
    return rows,datetime.fromtimestamp(event_epoch,timezone.utc).isoformat()


def coverage(rows, offsets):
    return sum(x in rows for x in offsets)/len(offsets)


def midpoint_return(rows, first_prior, last):
    if first_prior not in rows or last not in rows:
        return None
    return 10000*math.log(rows[last]['mid']/rows[first_prior]['mid'])


def window_metric(rows, start):
    offsets = range(start, start+6)
    if (start-1) not in rows or any(k not in rows for k in offsets):
        return None
    vals = [rows[k] for k in offsets]
    move = midpoint_return(rows,start-1,start+5)
    return {
        'release_mean_spread_bps': fmean(r['spread'] for r in vals),
        'release_median_total10_btc': median(r['depth'] for r in vals),
        'release_abs_mid_return_tplus5_bps': abs(move),
    }


def summarize(label,path,rows,event_utc):
    c_baseline=coverage(rows,PRE_REFERENCE)
    c_last=coverage(rows,PRE_LAST_MINUTE)
    c_event=coverage(rows,range(-1,6))
    c_post60=coverage(rows,range(0,61))
    observed=window_metric(rows,0)
    reference=[window_metric(rows,s) for s in REF_STARTS]
    reference=[x for x in reference if x is not None]
    # Two separate eligibility checks: release and baseline coverage.
    eligible=(c_baseline >= 0.95 and c_last >= 0.95 and observed is not None)
    summary={
        'case':label,'file':str(path),'reference_utc':event_utc,
        'baseline_coverage_pct':round(100*c_baseline,3),
        'pre60_coverage_pct':round(100*c_last,3),
        'release_anchor_and_0to5_coverage_pct':round(100*c_event,3),
        'post0to60_coverage_pct':round(100*c_post60,3),
        'eligible_primary':eligible,
        'nonoverlapping_reference_windows':len(reference),
    }
    for metric in PRIMARY:
        summary[metric] = observed[metric] if eligible else None
        rv=[x[metric] for x in reference]
        summary['reference_median_'+metric] = median(rv) if rv else None
        summary['reference_min_'+metric] = min(rv) if rv else None
        summary['reference_max_'+metric] = max(rv) if rv else None
        summary['as_or_more_extreme_reference_windows_'+metric] = (
            sum(z <= observed[metric] for z in rv) if metric=='release_median_total10_btc'
            else sum(z >= observed[metric] for z in rv)) if observed and rv else None
    if c_baseline >= .95 and c_last >= .95:
        pre=[rows[k]['depth'] for k in PRE_REFERENCE if k in rows]
        last=[rows[k]['depth'] for k in PRE_LAST_MINUTE if k in rows]
        final24=[rows[k]['depth'] for k in FINAL_24_SECONDS if k in rows]
        summary['baseline_median_depth10_btc']=median(pre) if pre else None
        summary['pre60_median_depth10_btc']=median(last) if last else None
        summary['pre24_median_depth10_btc']=median(final24) if len(final24)==24 else None
        summary['pre24_to_baseline_median_depth_ratio']=(
            median(final24)/median(pre) if len(final24)==24 and median(pre)>0 else None)
    else:
        summary.update(baseline_median_depth10_btc=None,pre60_median_depth10_btc=None,
                       pre24_median_depth10_btc=None,pre24_to_baseline_median_depth_ratio=None)
    return summary


def write_table(path, rows):
    fields=[]
    for rec in rows:
        for key in rec:
            if key not in fields:
                fields.append(key)
    with path.open('w',newline='',encoding='utf-8') as fh:
        wr=csv.DictWriter(fh,fieldnames=fields)
        wr.writeheader();wr.writerows(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--case',action='append',required=True,metavar='LABEL=CSV',
                   help='May repeat. Must be an observed_seconds.csv from the verified v1 replay.')
    p.add_argument('--control',help='Label of designated no-13:30-release same-clock control')
    p.add_argument('--outdir',type=Path,default=Path('research/project3_comparison'))
    args=p.parse_args()
    cases={}
    for item in args.case:
        if '=' not in item:
            p.error('--case must be LABEL=CSV')
        label,file=item.split('=',1)
        if not label.strip() or not file.strip() or label in cases:
            p.error('Invalid or duplicate case label')
        cases[label]=Path(file)
    if args.control and args.control not in cases:
        p.error('Control label must be among --case labels')
    reports=[]
    for label,path in cases.items():
        rows,event_utc=load(path)
        report=summarize(label,path,rows,event_utc)
        reports.append(report)
        state='ELIGIBLE' if report['eligible_primary'] else 'INCOMPLETE'
        print(f"{label} ({event_utc}): {state}; prebaseline={report['baseline_coverage_pct']}% "
              f"pre60={report['pre60_coverage_pct']}% release={report['release_anchor_and_0to5_coverage_pct']}%")
        for metric in PRIMARY:
            print(f"  {metric}: {report[metric]} vs {report['reference_median_'+metric]} reference median; "
                  f"as/extremer={report['as_or_more_extreme_reference_windows_'+metric]}/"
                  f"{report['nonoverlapping_reference_windows']}")
    comparisons=[]
    if args.control:
        ctrl=next(x for x in reports if x['case']==args.control)
        for case in reports:
            if case['case']==args.control: continue
            for metric in PRIMARY:
                a,b=case[metric],ctrl[metric]
                comparisons.append({
                    'event':case['case'],'control':args.control,'metric':metric,
                    'event_value':a,'control_value':b,
                    'event_minus_control':a-b if a is not None and b is not None else None,
                    'event_to_control_ratio':a/b if a is not None and b is not None and b else None,
                    'comparison_valid':a is not None and b is not None,
                })
        print(f"SAME-CLOCK CONTROL: {args.control} (descriptive only)")
    else:
        print('SAME-CLOCK CONTROL: not available yet; within-session benchmarks only')
    args.outdir.mkdir(parents=True,exist_ok=True)
    write_table(args.outdir/'primary_metrics.csv',reports)
    if comparisons: write_table(args.outdir/'control_differences.csv',comparisons)
    report={
        'version':'project3_matched_comparison_v1',
        'protocol_date':'2026-11-08',
        'post_hoc_for':'November 5 and November 6 metrics were selected after inspecting those outcomes',
        'frozen_for':'Subsequent November 9 control and November 10 CPI sessions, subject to documented amendments',
        'primary_outcomes':list(PRIMARY),
        'reference_window':'99 nonoverlapping six-second windows starting -594,-588,...,-6; includes final minute',
        'eligibility':'At least 95% coverage in [-600,-61] and [-60,-1], and all UTC receipt seconds [-1,+5]',
        'control':args.control,
        'control_caveat':'Nov 9 Fed official discussion scheduled 13:40 UTC; restrict primary comparison to t<=+5s',
        'no_inference':'Single control day; within-session rankings are descriptive, not p-values or causal effects',
        'no_execution':'Displayed book and midpoint returns do not establish executable fills or profit',
        'cases':reports,'control_comparisons':comparisons,
    }
    (args.outdir/'comparison_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('OUTPUT:',args.outdir.resolve())

if __name__=='__main__':
    main()
