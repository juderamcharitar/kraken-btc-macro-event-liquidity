"""Kraken Spot WS v2 BTC/USD L2 depth recorder with hourly rotation and reconnect.

Requires: pip install 'websockets>=13'
Does not require credentials or place orders.
Every segment starts with a fresh snapshot. Raw messages ONLY; NOT checksum-verified.
Interrupted segments retain a *.partial file, never accepted as complete.
"""
import argparse
import asyncio
import gzip
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

URL = 'wss://ws.kraken.com/v2'


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def line(record_type, payload):
    return json.dumps({'received_utc': utc_iso(), 'record_type': record_type,
                       'source': 'kraken_spot_ws_v2_book', 'payload': payload},
                      separators=(',', ':'), ensure_ascii=False) + '\n'


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def next_boundary(start_epoch, rotation_s):
    """Next global UTC rotation boundary (epoch-seconds multiples)."""
    return (int(start_epoch // rotation_s) + 1) * rotation_s


def filename(stamp, index, compressed):
    dt = datetime.fromtimestamp(stamp, tz=timezone.utc)
    suffix = '.jsonl.gz' if compressed else '.jsonl'
    return f'kraken_BTCUSD_{dt:%Y%m%dT%H%M%SZ}_s{index:04d}{suffix}'


def record_message(out, kind, msg):
    out.write(line(kind, msg))


async def capture_segment(outdir, index, symbol, depth, stop_monotonic, rotation_s, compress,
                          connect_timeout=20, idle_timeout=35, ws_connect=None):
    """A fresh connection + snapshot per segment. Returns manifest record.

    Rotation uses wall UTC boundaries, while total capture duration uses monotonic time.
    Always stops at the earlier of the two deadlines; any socket failure leaves .partial.
    """
    now = time.time()
    time_left = max(0., stop_monotonic - time.monotonic())
    remaining_to_boundary = max(0., next_boundary(now, rotation_s) - now)
    segment_s = min(time_left, remaining_to_boundary)
    dest = outdir / filename(now, index, compress)
    partial = dest.with_name(dest.name + '.partial')
    if dest.exists() or partial.exists():
        raise FileExistsError(f'Existing segment path: {dest}')
    entry = {'index': index, 'file': dest.name, 'started_utc': utc_iso(),
             'state': 'started', 'snapshots': 0, 'updates': 0,
             'checksum_verified': False, 'bytes': None, 'sha256': None,
             'error': None}
    if segment_s <= 0:
        entry['state'] = 'skipped'; return entry
    connector = ws_connect or websockets.connect
    until = time.monotonic() + segment_s
    snapped = False
    acked = False
    try:
        with partial.open('xb') as raw:
            stream = gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=3, mtime=0) if compress else raw
            try:
                # Write UTF-8, but retain raw Kraken-decoded JSON numbers as in original recorder.
                def write(kind, payload):
                    stream.write(line(kind, payload).encode('utf-8'))
                write('meta', {'symbol':symbol, 'depth':depth, 'endpoint':URL,
                               'segment_s':round(segment_s,3), 'integrity':'RAW_UNVERIFIED_CHECKSUM',
                               'rotation_s':rotation_s})
                async with connector(URL, open_timeout=connect_timeout, ping_interval=20,
                                     ping_timeout=20, max_size=32 * 1024 * 1024) as ws:
                    await ws.send(json.dumps({'method':'subscribe','params':{
                        'channel':'book','symbol':[symbol],'depth':depth,'snapshot':True},'req_id':23004}))
                    while True:
                        remaining = until - time.monotonic()
                        if remaining <= 0:
                            break
                        try:
                            raw_msg = await asyncio.wait_for(ws.recv(), timeout=min(idle_timeout, remaining))
                        except asyncio.TimeoutError:
                            if time.monotonic() >= until:
                                break
                            raise TimeoutError(f'No feed messages for {idle_timeout}s')
                        msg = json.loads(raw_msg)
                        if msg.get('method') == 'subscribe':
                            if msg.get('success') is False:
                                raise RuntimeError(f'Subscription rejected: {msg.get("error", msg)}')
                            res = msg.get('result') or {}
                            if res.get('channel') == 'book' and res.get('symbol') == symbol:
                                acked = True
                                write('subscription_ack', msg)
                            continue
                        if msg.get('channel') != 'book' or msg.get('type') not in ('snapshot','update'):
                            continue
                        data = msg.get('data')
                        if not isinstance(data, list) or len(data) != 1 or data[0].get('symbol') != symbol:
                            continue
                        kind = msg['type']
                        if kind == 'snapshot':
                            entry['snapshots'] += 1
                            snapped = True
                        else:
                            if not snapped:
                                continue
                            entry['updates'] += 1
                        write(kind, msg)
                        if entry['updates'] and entry['updates'] % 5000 == 0:
                            stream.flush()
                            raw.flush()
                            print(f'  Segment {index}: {entry["updates"]:,} updates', flush=True)
                    if not acked or not snapped or entry['updates'] == 0:
                        raise RuntimeError('Segment lacks ACK, snapshot, or updates')
                    write('capture_complete', {'snapshots':entry['snapshots'], 'updates':entry['updates'],
                                               'checksum_validated':False,
                                               'note':'Raw capture ended at planned boundary; downstream checksums required'})
                    stream.flush()
            finally:
                if compress:
                    stream.close()  # finalize gzip trailer even on exception
                raw.flush()
                os.fsync(raw.fileno())
        os.replace(partial, dest)
        entry.update(state='complete', bytes=dest.stat().st_size, sha256=sha256(dest))
        print(f'  SAVED {dest.name} | {entry["updates"]:,} updates | {entry["bytes"]:,} bytes',flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        entry.update(state='partial', error=f'{type(exc).__name__}: {str(exc)[:220]}')
        print(f'  INCOMPLETE {partial.name}: {entry["error"]}', flush=True)
        if isinstance(exc, KeyboardInterrupt):
            raise
    finally:
        entry['ended_utc'] = utc_iso()
    return entry


async def run(args, capture_fn=capture_segment):
    session_stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outdir = args.outdir / f'kraken_BTCUSD_{session_stamp}'
    outdir.mkdir(parents=True, exist_ok=False)  # never overwrite old sessions
    manifest_path = outdir / 'manifest.json'
    started = time.monotonic()
    deadline = started + args.hours * 3600
    manifest = {'schema':1, 'session_start_utc':utc_iso(), 'symbol':args.symbol,
                'depth':args.depth,'requested_hours':args.hours,
                'rotation_seconds':args.rotate_minutes*60, 'compressed':not args.plain,
                'feed':URL, 'segment_checksums':'NOT_VERIFIED_DURING_RECORDING',
                'status':'running', 'segments':[]}
    atomic_json(manifest_path, manifest)
    i = 0; consecutive_failures = 0
    try:
        while time.monotonic() < deadline:
            i += 1
            segment = await capture_fn(outdir, i, args.symbol,args.depth,deadline,
                                       args.rotate_minutes*60,not args.plain)
            manifest['segments'].append(segment)
            if segment['state'] == 'complete':
                consecutive_failures = 0
            elif segment['state'] == 'skipped':
                await asyncio.sleep(0.1)
            else:
                consecutive_failures += 1
                if consecutive_failures >= args.max_failures:
                    manifest['status'] = 'stopped_after_repeated_failures'
                    break
                delay=min(60, 2 ** min(consecutive_failures,5)) + random.uniform(0,.5)
                print(f'  Reconnecting with fresh snapshot after {delay:.1f}s...',flush=True)
                await asyncio.sleep(min(delay,max(0.,deadline-time.monotonic())))
            atomic_json(manifest_path,manifest)
        if manifest['status']=='running':
            manifest['status']='ended_at_duration'
    except (KeyboardInterrupt, asyncio.CancelledError):
        manifest['status']='interrupted'
        raise
    finally:
        manifest['session_end_utc']=utc_iso()
        manifest['complete_segments']=sum(x['state']=='complete' for x in manifest['segments'])
        manifest['incomplete_segments']=sum(x['state']=='partial' for x in manifest['segments'])
        manifest['total_recorded_updates']=sum(x['updates'] for x in manifest['segments'] if x['state']=='complete')
        atomic_json(manifest_path,manifest)
        print(f'MANIFEST {manifest_path}; status={manifest["status"]}; '
              f'complete={manifest["complete_segments"]}; partial={manifest["incomplete_segments"]}',flush=True)
    return manifest_path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hours',type=float,default=24)
    p.add_argument('--rotate-minutes',type=int,default=60)
    p.add_argument('--symbol',default='BTC/USD')
    p.add_argument('--depth',type=int,choices=[10,25,100,500,1000],default=100)
    p.add_argument('--outdir',type=Path,default=Path('data/l2_overnight'))
    p.add_argument('--plain',action='store_true',help='Save larger uncompressed .jsonl files')
    p.add_argument('--max-failures',type=int,default=12)
    a=p.parse_args()
    if not (0 < a.hours <= 72):p.error('hours must be in (0, 72]')
    if not (1 <= a.rotate_minutes <= 60):p.error('rotate-minutes must be 1..60')
    if a.max_failures < 1:p.error('max-failures must be >=1')
    asyncio.run(run(a))

if __name__=='__main__':
    main()
