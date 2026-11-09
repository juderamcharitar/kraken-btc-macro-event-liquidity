#!/usr/bin/env python3
"""Synthetic unit/integration tests for project3_statistical_analysis_v2.py.
No network or raw Kraken data needed. Python 3.10+ stdlib.
"""
import csv
import json
import math
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import project3_statistical_analysis_v2 as v2


def fixture(root, label, *, missing=(), corrupt_report=False, omit_pre_anchor=False):
    date=v2.EVENTS[label]['date']
    timestamp=datetime.fromisoformat(f'{date}T13:30:00+00:00')
    folder=root/label
    folder.mkdir(parents=True)
    observed=folder/'observed_seconds.csv'
    fields=['second_utc','event_offset_s','mid','spread_bps','total10_btc']
    with observed.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for k in range(-600,901):
            if k in missing or (omit_pre_anchor and k==-1):
                continue
            ts=(timestamp+timedelta(seconds=k)).isoformat()
            spread=.01 if k<0 else (1.0 if 0<=k<=5 else .01)
            depth=10.0 if k<-24 else (2.0 if k<0 else (1.0 if k<=5 else 10.0))
            mid=100.0 if k<0 else (99.9 if k<=5 else 100.0)
            writer.writerow(dict(second_utc=ts,event_offset_s=k,mid=mid,
                                 spread_bps=spread,total10_btc=depth))
    report={
        'audit_status':'PASS_FULL' if not corrupt_report else 'PASS_SAMPLE',
        'audit_updates_checked':1000,
        'replay':{'updates_replayed':1000},
        'event_utc':timestamp.isoformat(),
        'input_manifest':'synthetic/manifest.json',
        'input_audit':'synthetic/pass_full.csv'
    }
    (folder/'event_report.json').write_text(json.dumps(report),encoding='utf-8')
    return observed

class PipelineTests(unittest.TestCase):
    def test_both_events_and_differences(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            nov5=fixture(root,'nov05')
            control=fixture(root,'nov09_control')
            before=v2.sha256_file(nov5)
            result,provenance,gaps=v2.analyze_cases({'nov05':nov5,'nov09_control':control})
            self.assertEqual(len(result),2)
            self.assertEqual(len(provenance),2)
            self.assertEqual(before,v2.sha256_file(nov5))
            first=result[0]
            self.assertTrue(first['eligible_primary'])
            self.assertEqual(first['missing_seconds_minus600_to_plus900'],0)
            self.assertTrue(first['full_path_tplus120'])
            self.assertAlmostEqual(first['pre24_depth_ratio_to_baseline'],0.2)
            self.assertAlmostEqual(first['release_mean_spread_bps'],1.0)
            self.assertAlmostEqual(first['release_median_total10_btc'],1.0)
            self.assertAlmostEqual(first['mid_signed_return_tplus5_bps'],10000*math.log(.999))
            self.assertEqual(len(v2.control_comparisons(result)),4)

    def test_raw_gap_excludes_long_contiguous_path(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td),'nov06',missing=range(264,303))
            reports,_,gaps=v2.analyze_cases({'nov06':path})
            r=reports[0]
            self.assertTrue(r['eligible_primary'])
            self.assertEqual(r['missing_seconds_minus600_to_plus900'],39)
            self.assertTrue(r['full_path_tplus120'])
            self.assertIsNone(v2.quote_return(v2.load(path)[0],300))
            self.assertEqual(gaps['nov06']['first_postrelease_gap'],(264,302))

    def test_bad_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td),'nov10_cpi',corrupt_report=True)
            with self.assertRaisesRegex(ValueError,'PASS_FULL'):
                v2.analyze_cases({'nov10_cpi':path})

    def test_missing_anchor_ineligible(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td),'nov05',omit_pre_anchor=True)
            report,_,_=v2.analyze_cases({'nov05':path})
            self.assertFalse(report[0]['eligible_primary'])
            self.assertIsNone(report[0]['release_abs_mid_return_tplus5_bps'])

    def test_cli_writes_required_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=fixture(root,'nov05')
            out=root/'output'
            script=Path(v2.__file__).resolve()
            completed=subprocess.run(
                [sys.executable,str(script),'--case',f'nov05={source}',
                 '--outdir',str(out)],capture_output=True,text=True,check=True)
            self.assertIn('SAME-CLOCK CONTROL: not collected yet',completed.stdout)
            for filename in ('case_metrics.csv','source_provenance.csv',
                             'analysis_report.json','analysis_source_hashes.sha256'):
                self.assertTrue((out/filename).is_file(),filename)
            report=json.loads((out/'analysis_report.json').read_text())
            self.assertEqual(report['protocol_id'],v2.PROTOCOL_ID)
            self.assertEqual(len(report['case_results']),1)
            self.assertEqual(len(report['single_day_control_contrasts']),0)

    def test_unknown_label_requires_amendment(self):
        with self.assertRaisesRegex(ValueError,'Unregistered label'):
            v2.parse_cases(['nov11_control=whatever.csv'])

if __name__=='__main__':
    unittest.main(verbosity=2)
