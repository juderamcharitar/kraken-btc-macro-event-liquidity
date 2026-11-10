#!/usr/bin/env python3
"""Public-summary internal consistency check (not empirical reproduction)."""
import csv, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with (ROOT/'results/case_metrics.csv').open(newline='',encoding='utf-8') as f:
    items=list(csv.DictReader(f))
assert len(items)==4, 'Expected four cases'
refs={
 'nov05':(0.012561748879526538,1.25449696,0.0,0.3050218496405411),
 'nov06':(19.119814116698837,0.707910365,45.779083575420565,0.03581531831903184),
 'nov09_control':(0.013390725985684077,3.39893234,0.0,0.7943868760220162),
 'nov10_cpi':(25.54562985679374,7.62364103,21.723743812841487,0.058768928560663),
}
seen=set()
for r in items:
    c=r['case']; assert c in refs and c not in seen,c;seen.add(c)
    for field,expected in zip(('release_mean_spread_bps','release_median_total10_btc','release_abs_mid_return_tplus5_bps','pre24_depth_ratio_to_baseline'),refs[c]):
        got=float(r[field]);assert math.isclose(got,expected,rel_tol=1e-11,abs_tol=1e-11),(c,field,got)
    assert r['eligible_primary']=='True',(c,'ineligible')
    print(f'{c}: aggregate metrics match archived values')
assert seen==set(refs)
with (ROOT/'results/single_control_contrasts.csv').open(newline='',encoding='utf-8') as f:
    contrasts=list(csv.DictReader(f))
assert len(contrasts)>=9
for r in contrasts:
    assert r['case'] in refs and r['control']=='nov09_control'
    if r['comparison_valid']=='True' and r['event_value'] and r['control_value']:
        assert math.isclose(float(r['event_minus_control']),float(r['event_value'])-float(r['control_value']),rel_tol=1e-9,abs_tol=1e-9)
print('PUBLIC SUMMARY CHECK: PASS (not a raw-data reanalysis)')
