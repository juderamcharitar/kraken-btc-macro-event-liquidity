#!/usr/bin/env python3
"""Independent per-segment Kraken WS v2 L2 state/CRC32 validator (v2: diagnose time regressions).

Read-only: never modifies recordings or manifest. Uses original complete .jsonl.gz
and separately recovered .recovered.jsonl.gz for interrupted segments.

By default validates only the first 1,000 updates in each segment, a quick
compatibility/sanity check. Supply --full to validate *all* updates and counts.
No order-book state is carried across reconnects/segment boundaries.
Backward received_utc jumps are reported as warnings; CRC validation continues.

The supplied recorder serialized JSON exchange numbers as Python floats. For
BTC/USD, this uses price=1 decimal and quantity=8 decimals, the same format
previously verified on the user's Kraken v0.5 recording. If checksum mismatch
occurs, investigate numeric representation rather than assuming data loss.
"""
import argparse
import csv
from decimal import Decimal, InvalidOperation
import gzip
from datetime import datetime
import json
from pathlib import Path
import zlib

PRICE_PLACES=1
QUANTITY_PLACES=8


def normalized(v, digits):
    return format(v, f'.{digits}f').replace('.', '').lstrip('0') or '0'


def crc32_book(bids, asks):
    ask_prices=sorted(asks)[:10]
    bid_prices=sorted(bids, reverse=True)[:10]
    joined=''.join(normalized(p, PRICE_PLACES) + normalized(asks[p], QUANTITY_PLACES) for p in ask_prices)
    joined+=''.join(normalized(p, PRICE_PLACES) + normalized(bids[p], QUANTITY_PLACES) for p in bid_prices)
    return zlib.crc32(joined.encode('ascii')) & 0xffffffff


def apply_changes(book, changes):
    for x in changes:
        price=x['price']; qty=x['qty']
        if qty<0: raise ValueError('Negative quantity')
        if qty==0: book.pop(price,None)
        else: book[price]=qty


def keep_depth(book, reverse, depth):
    for p in sorted(book, reverse=reverse)[depth:]:
        del book[p]


def validate(path, entry, depth, max_updates):
    counts={'meta':0,'subscription_ack':0,'snapshot':0,'update':0,'capture_complete':0}
    bids={};asks={};prior_recv=None;first_recv=None;last_recv=None
    first_exchange=None;last_exchange=None
    result={'segment':entry['index'],'state':entry['state'],'file':path.name,
            'exists':path.is_file(),'status':'PASS_SAMPLE' if max_updates is not None else 'PASS_FULL',
            'updates_checked':0,'expected_updates':entry['updates'],'crc_errors':0,'crossed_books':0,
            'first_receive_utc':'','last_receive_utc':'','first_exchange_time':'','last_exchange_time':'',
            'receive_timestamp_regressions':0,'largest_backstep_ms':0.0,
            'first_regression_line':'','first_regression_previous':'','first_regression_current':'',
            'error':''}
    if not path.exists():
        result.update(status='MISSING',error='Source file not found')
        return result
    try:
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            for line_num,line in enumerate(stream,1):
                row=json.loads(line,parse_float=Decimal)
                kind=row.get('record_type')
                if kind not in counts: raise ValueError(f'line {line_num}: unexpected record type {kind!r}')
                counts[kind]+=1
                if kind=='meta':
                    meta=row.get('payload',{})
                    if meta.get('symbol')!='BTC/USD' or meta.get('depth')!=depth:
                        raise ValueError(f'line {line_num}: unexpected metadata')
                    continue
                if kind=='subscription_ack':
                    if row.get('payload',{}).get('success') is not True:
                        raise ValueError(f'line {line_num}: unsuccessful subscription')
                    continue
                if kind=='capture_complete':
                    if entry['state']!='complete':
                        raise ValueError(f'line {line_num}: unexpected complete marker in partial segment')
                    marker=row.get('payload',{})
                    if marker.get('updates')!=counts['update'] or marker.get('snapshots')!=counts['snapshot']:
                        raise ValueError(f'line {line_num}: capture_complete totals mismatch')
                    continue
                # Every segment begins with its own independent initial snapshot.
                if counts['meta']!=1 or counts['subscription_ack']!=1:
                    raise ValueError(f'line {line_num}: book event before meta and subscription acknowledgement')
                message=row['payload']
                if message.get('channel')!='book' or message.get('type')!=kind or len(message.get('data',[]))!=1:
                    raise ValueError(f'line {line_num}: bad book envelope')
                data=message['data'][0]
                if data.get('symbol')!='BTC/USD':
                    raise ValueError(f'line {line_num}: wrong market symbol')
                if kind=='snapshot':
                    if counts['snapshot']!=1 or counts['update']:
                        raise ValueError(f'line {line_num}: unexpected second snapshot')
                    bids={x['price']:x['qty'] for x in data['bids'] if x['qty']>0}
                    asks={x['price']:x['qty'] for x in data['asks'] if x['qty']>0}
                else:
                    if counts['snapshot']!=1:
                        raise ValueError(f'line {line_num}: update before initial snapshot')
                    apply_changes(bids,data.get('bids',[]))
                    apply_changes(asks,data.get('asks',[]))
                keep_depth(bids,True,depth)
                keep_depth(asks,False,depth)
                if not bids or not asks:
                    raise ValueError(f'line {line_num}: empty book side')
                if max(bids)>=min(asks):
                    result['crossed_books']+=1
                    raise ValueError(f'line {line_num}: locked or crossed book')
                exchange_crc=data.get('checksum')
                local_crc=crc32_book(bids,asks)
                if local_crc!=exchange_crc:
                    result['crc_errors']+=1
                    raise ValueError(f'line {line_num}: exchange CRC={exchange_crc}, local CRC={local_crc}; check float normalization')
                ts=row.get('received_utc','')
                if not isinstance(ts,str) or not ts:
                    raise ValueError(f'line {line_num}: missing/invalid received_utc')
                # Local wall-clock timestamps may step backwards (clock sync, etc.).
                # That is worth reporting, but is NOT itself a book CRC mismatch.
                # Preserve original message order for the book reconstruction.
                if prior_recv is not None and ts < prior_recv:
                    result['receive_timestamp_regressions'] += 1
                    if not result['first_regression_line']:
                        result['first_regression_line']=line_num
                        result['first_regression_previous']=prior_recv
                        result['first_regression_current']=ts
                    try:
                        dt1=datetime.fromisoformat(prior_recv.replace('Z','+00:00'))
                        dt2=datetime.fromisoformat(ts.replace('Z','+00:00'))
                        backstep_ms=max(0.0,(dt1-dt2).total_seconds()*1000)
                        result['largest_backstep_ms']=max(result['largest_backstep_ms'],round(backstep_ms,3))
                    except (ValueError,TypeError):
                        pass
                prior_recv=ts
                if first_recv is None:
                    first_recv=ts
                    first_exchange=data.get('timestamp','')
                last_recv=ts
                last_exchange=data.get('timestamp','')
                if kind=='update':
                    result['updates_checked']+=1
                    if max_updates is not None and result['updates_checked']>=max_updates:
                        break
        if counts['snapshot']!=1 or counts['meta']!=1 or counts['subscription_ack']!=1:
            raise ValueError(f'book framing incomplete: {counts}')
        if result['updates_checked']<1:
            raise ValueError('No book updates were checksum validated')
        if max_updates is None:
            if counts['update']!=entry['updates']:
                raise ValueError(f"update count mismatch: observed {counts['update']}, expected {entry['updates']}")
            if counts['capture_complete']!=(1 if entry['state']=='complete' else 0):
                raise ValueError('incorrect number of capture_complete markers')
        result['first_receive_utc']=first_recv or ''
        result['last_receive_utc']=last_recv or ''
        result['first_exchange_time']=first_exchange or ''
        result['last_exchange_time']=last_exchange or ''
        if result['receive_timestamp_regressions']:
            result['status']='PASS_TS_WARNING'
    except Exception as exc:
        result['status']='FAIL'
        result['error']=f'{type(exc).__name__}: {exc}'[:360]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--out',type=Path,default=Path('kraken_l2_checksum_audit.csv'))
    parser.add_argument('--sample-updates',type=int,default=1000)
    parser.add_argument('--full',action='store_true',help='Validate every book message and verify entire segment counts')
    parser.add_argument('--segment',type=int,default=None,help='Only check this segment number (e.g. 5)')
    args=parser.parse_args()
    if args.sample_updates<1:parser.error('--sample-updates must be >=1')
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    folder=args.manifest.parent
    max_updates=None if args.full else args.sample_updates
    print(f"MODE: {'FULL all-update audit' if args.full else f'SAMPLE first {max_updates:,} updates per segment'}")
    rows=[]
    segments=[e for e in manifest['segments'] if args.segment is None or e['index']==args.segment]
    if not segments: parser.error('requested segment not found in manifest')
    for e in segments:
        path=folder/e['file'] if e['state']=='complete' else folder/(e['file'][:-len('.jsonl.gz')]+'.recovered.jsonl.gz')
        r=validate(path,e,manifest['depth'],max_updates)
        rows.append(r)
        summary=f"{r['segment']:02d} {r['state']:<8} {r['status']:<12} checked={r['updates_checked']:,}"
        extra=f" timestamp_regressions={r['receive_timestamp_regressions']} largest_backstep_ms={r['largest_backstep_ms']}" if r['receive_timestamp_regressions'] else ''
        print(summary+extra+(f" ERROR: {r['error']}" if r['error'] else ''),flush=True)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('w',newline='',encoding='utf-8') as stream:
        w=csv.DictWriter(stream,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)
    print(f"SUMMARY: passed_or_time_warned={sum(r['status'].startswith('PASS') for r in rows)}/{len(rows)}; "
          f"updates_checked={sum(r['updates_checked'] for r in rows):,}; "
          f"failures={sum(r['status']!='PASS_SAMPLE' and r['status']!='PASS_FULL' for r in rows)}")
    print(f"TIMESTAMP_WARNINGS: {sum(r['receive_timestamp_regressions'] for r in rows):,} backwards receive-time jumps")
    for r in rows:
        if r['receive_timestamp_regressions']:
            print(f"  segment {r['segment']:02}: first at JSONL line {r['first_regression_line']}: {r['first_regression_previous']} -> {r['first_regression_current']}")
    print(f'CSV report: {args.out.resolve()}')
    if not args.full:
        print('Sample checks do NOT prove full-session integrity. Run with --full after samples pass.')
    raise SystemExit(0 if all(r['status'].startswith('PASS') for r in rows) else 1)

if __name__=='__main__':
    main()
