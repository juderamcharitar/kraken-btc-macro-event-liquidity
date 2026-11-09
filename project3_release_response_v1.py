#!/usr/bin/env python3
"""Project 3: checksum-audited Kraken BTC/USD L2 macro-release response.

Reads ONE complete depth-100 Kraken WebSocket v2 segment and its PASS_FULL
checksum audit. Never modifies source recordings or manifests. Reconstructs
order-book snapshots/updates in original file order, then samples the LAST
observed book within each UTC receipt-time second. Missing seconds are missing;
no interpolation or book state is carried across independent segments.

Outputs: observed_seconds.csv, window_summary.csv, endpoint_returns.csv,
         event_report.json. Everything is DESCRIPTIVE, not a causal estimate,
         trade backtest, verified event-time reaction or alpha claim.

Python 3.10+, standard library only. Verified input prerequisite:
  validate_kraken_l2_checksums_v2.py --segment N --full --out AUDIT.csv
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import statistics

BPS = 10000.0
WINDOWS = [
    ("pre_10_to_1min", -600, -61),
    ("pre_last_60s", -60, -1),
    ("release_0_to_5s", 0, 5),
    ("post_6_to_30s", 6, 30),
    ("post_31_to_60s", 31, 60),
    ("post_61_to_300s", 61, 300),
    ("post_301_to_900s", 301, 900),
]
HORIZONS = (0, 1, 2, 5, 10, 30, 60, 120, 300, 600, 900)


def utc_epoch(s: str) -> float:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Timezone required: {s!r}")
    return dt.astimezone(timezone.utc).timestamp()


def utc_iso(t: int | float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def validate_audit(audit: Path, segment: int, expected: int) -> dict:
    with audit.open(newline="", encoding="utf-8-sig") as f:
        records = list(csv.DictReader(f))
    matched = [r for r in records if int(r["segment"]) == segment]
    if len(matched) != 1:
        raise ValueError(f"Expected exactly one audit row for segment {segment}")
    r = matched[0]
    if (r.get("status") != "PASS_FULL" or
            int(r.get("updates_checked", "-1")) != expected or
            int(r.get("expected_updates", "-1")) != expected or
            int(r.get("crc_errors", "-1")) != 0 or
            int(r.get("crossed_books", "-1")) != 0 or
            int(r.get("receive_timestamp_regressions", "-1")) != 0):
        raise ValueError(f"Audit did not establish complete clean validation: {r}")
    return r


def apply(side: dict[float, float], changes: list[dict]) -> None:
    for x in changes:
        price, qty = float(x["price"]), float(x["qty"])
        if not math.isfinite(price) or not math.isfinite(qty) or price <= 0 or qty < 0:
            raise ValueError("Invalid book price or quantity")
        if qty == 0:
            side.pop(price, None)
        else:
            side[price] = qty


def keep_depth(side: dict, reverse: bool, depth: int) -> None:
    if len(side) > depth:
        for price in sorted(side, reverse=reverse)[depth:]:
            del side[price]


def features(book_bid: dict, book_ask: dict, t: int, count: int, last_recv: str,
             segment: int, event_epoch: int) -> dict:
    bp = sorted(book_bid, reverse=True)
    ap = sorted(book_ask)
    if not bp or not ap or bp[0] >= ap[0]:
        raise ValueError(f"Empty or crossed book at {utc_iso(t)}")
    best_bid, best_ask = bp[0], ap[0]
    mid = (best_bid + best_ask) / 2.0
    b1, a1 = book_bid[best_bid], book_ask[best_ask]
    b10 = sum(book_bid[p] for p in bp[:10])
    a10 = sum(book_ask[p] for p in ap[:10])
    return {
        "second_utc": utc_iso(t), "event_offset_s": t-event_epoch,
        "segment": segment, "update_messages": count,
        "last_receive_utc": last_recv,
        "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
        "spread_usd": best_ask-best_bid,
        "spread_bps": (best_ask-best_bid)/mid*BPS,
        "bid1_btc": b1, "ask1_btc": a1,
        "bid10_btc": b10, "ask10_btc": a10,
        "total10_btc": b10+a10,
        "imbalance10": (b10-a10)/(b10+a10) if b10+a10 else None,
        "microprice_minus_mid_bps": ((best_ask*b1+best_bid*a1)/(b1+a1)-mid)/mid*BPS
        if b1+a1 else None,
    }


def replay(manifest: Path, segment: int, event_epoch: int) -> tuple[dict, dict]:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    if m.get("symbol") != "BTC/USD" or m.get("depth") != 100:
        raise ValueError("Requires Kraken BTC/USD, depth 100")
    matching = [x for x in m["segments"] if x["index"] == segment]
    if len(matching) != 1 or matching[0]["state"] != "complete":
        raise ValueError("Requested segment must exist and be complete")
    entry = matching[0]
    source = manifest.parent / entry["file"]
    if not source.is_file():
        raise FileNotFoundError(source)

    bids, asks = {}, {}
    cnt_meta = cnt_ack = cnt_snapshot = cnt_finish = updates = 0
    rows = {}
    sec = last_receive = None
    sec_updates = 0
    prev_recv = None
    last_before = first_after = None
    near_event_updates = 0
    seen_at_before = seen_at_after = False
    first_recorded = last_recorded = None

    def flush() -> None:
        if sec is not None and event_epoch-600 <= sec <= event_epoch+900:
            rows[sec] = features(bids, asks, sec, sec_updates, last_receive, segment, event_epoch)

    with gzip.open(source, "rt", encoding="utf-8") as inp:
        for line_num, line in enumerate(inp, 1):
            x = json.loads(line)
            kind = x.get("record_type")
            if kind == "meta":
                cnt_meta += 1
                if cnt_meta != 1 or x.get("payload", {}).get("symbol") != "BTC/USD":
                    raise ValueError(f"Bad metadata at line {line_num}")
                continue
            if kind == "subscription_ack":
                cnt_ack += 1
                if cnt_ack != 1 or x.get("payload", {}).get("success") is not True:
                    raise ValueError(f"Bad ACK at line {line_num}")
                continue
            if kind == "capture_complete":
                cnt_finish += 1
                if x.get("payload", {}).get("updates") != updates:
                    raise ValueError(f"Bad capture_complete at line {line_num}")
                continue
            if kind not in ("snapshot", "update"):
                raise ValueError(f"Unexpected record type {kind!r}")
            if cnt_meta != 1 or cnt_ack != 1:
                raise ValueError("Book event before metadata and ACK")
            recv = x.get("received_utc")
            if not isinstance(recv, str):
                raise ValueError(f"Bad received_utc at line {line_num}")
            t = utc_epoch(recv)
            if prev_recv is not None and t < prev_recv:
                raise ValueError(f"Backward receive timestamp at line {line_num}; stop research")
            prev_recv = t
            if first_recorded is None:
                first_recorded = recv
            last_recorded = recv
            second = int(math.floor(t))

            # IMPORTANT: flush previous second before applying the next update.
            if sec is not None and second != sec:
                flush()
                sec_updates = 0
            sec = second
            last_receive = recv

            msg = x["payload"]
            if msg.get("channel") != "book" or msg.get("type") != kind or len(msg.get("data", [])) != 1:
                raise ValueError(f"Invalid Kraken book envelope at line {line_num}")
            data = msg["data"][0]
            if data.get("symbol") != "BTC/USD":
                raise ValueError("Wrong symbol")
            if kind == "snapshot":
                cnt_snapshot += 1
                if cnt_snapshot != 1 or updates:
                    raise ValueError("Unexpected snapshot")
                bids = {float(p["price"]): float(p["qty"]) for p in data["bids"] if float(p["qty"]) > 0}
                asks = {float(p["price"]): float(p["qty"]) for p in data["asks"] if float(p["qty"]) > 0}
            else:
                if cnt_snapshot != 1:
                    raise ValueError("Update before snapshot")
                apply(bids, data.get("bids", []))
                apply(asks, data.get("asks", []))
                updates += 1
                sec_updates += 1
                if event_epoch-60 <= t <= event_epoch+60:
                    near_event_updates += 1
            keep_depth(bids, True, 100)
            keep_depth(asks, False, 100)
            if not bids or not asks or max(bids) >= min(asks):
                raise ValueError(f"Crossed or empty book at line {line_num}")
            if kind == "update":
                if t < event_epoch:
                    last_before = recv
                    seen_at_before = True
                elif not seen_at_after:
                    first_after = recv
                    seen_at_after = True
    flush()
    if cnt_meta != 1 or cnt_ack != 1 or cnt_snapshot != 1 or cnt_finish != 1:
        raise ValueError("Missing/duplicate meta, ACK, snapshot or capture_complete")
    if updates != entry["updates"]:
        raise ValueError(f"Updates {updates} != manifest expected {entry['updates']}")
    if not rows:
        raise ValueError("No observed book seconds in the event window")
    metadata = {"source_file": str(source), "segment": segment, "updates_replayed": updates,
                "snapshot_count": cnt_snapshot, "first_receive_utc": first_recorded,
                "last_receive_utc": last_recorded,
                "updates_within_exact_60s_each_side": near_event_updates,
                "last_update_before_event_utc": last_before,
                "first_update_after_event_utc": first_after,
                "release_update_gap_ms": round((utc_epoch(first_after)-utc_epoch(last_before))*1000, 3)
                if last_before and first_after else None}
    return rows, metadata


def avg(xs):
    values = [x for x in xs if x is not None and math.isfinite(x)]
    return statistics.fmean(values) if values else None


def window_stats(rows: dict, event_epoch: int, label: str, low: int, high: int) -> dict:
    present = [rows.get(event_epoch+k) for k in range(low, high+1)]
    valid = [r for r in present if r is not None]
    returns = []
    for k in range(low, high+1):
        current, prior = rows.get(event_epoch+k), rows.get(event_epoch+k-1)
        if current is not None and prior is not None:
            returns.append(BPS*math.log(current["mid"]/prior["mid"]))
    spread = [r["spread_bps"] for r in valid]
    return {"window": label, "start_offset_s": low, "end_offset_s": high,
            "expected_seconds": high-low+1, "observed_seconds": len(valid),
            "coverage_pct": round(100*len(valid)/(high-low+1), 3),
            "updates_in_observed_seconds": sum(r["update_messages"] for r in valid),
            "mean_spread_bps": avg(spread), "max_spread_bps": max(spread) if spread else None,
            "mean_bid10_btc": avg(r["bid10_btc"] for r in valid),
            "mean_ask10_btc": avg(r["ask10_btc"] for r in valid),
            "mean_total10_btc": avg(r["total10_btc"] for r in valid),
            "mean_imbalance10": avg(r["imbalance10"] for r in valid),
            "mean_abs_1s_return_bps": avg(abs(x) for x in returns),
            "rms_1s_return_bps": math.sqrt(avg(x*x for x in returns)) if returns else None,
            "valid_adjacent_1s_returns": len(returns)}


def endpoint_stats(rows: dict, event_epoch: int, k: int) -> dict:
    # t-1 is last received quote within the preceding second, NOT a pre-release
    # exchange-time synchronized quote. t+k is last observed quote in that second.
    before = rows.get(event_epoch-1)
    after = rows.get(event_epoch+k)
    path = [event_epoch+j for j in range(0, k+1)]
    have = sum(t in rows for t in path)
    result = {"horizon_s": k, "pre_second_observed": before is not None,
              "endpoint_second_observed": after is not None,
              "intermediate_seconds_observed": have,
              "intermediate_seconds_expected": k+1,
              "intermediate_coverage_pct": round(100*have/(k+1), 3),
              "mid_before": before["mid"] if before else None,
              "mid_after": after["mid"] if after else None,
              "mid_return_bps": None, "status": "missing_endpoint"}
    if before and after:
        if k <= 60 and have != k+1:
            result["status"] = "missing_intermediate_second_short_horizon"
        else:
            result["mid_return_bps"] = BPS*math.log(after["mid"]/before["mid"])
            result["status"] = ("observed_full_path" if have == k+1 else
                                "observed_endpoints_incomplete_long_path")
    return result


def save_csv(path: Path, items: list[dict]) -> None:
    if not items:
        raise ValueError("Cannot save empty CSV")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(items[0]))
        writer.writeheader()
        writer.writerows(items)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--audit", required=True, type=Path,
                   help="CSV emitted by a PASS_FULL check for the same segment")
    p.add_argument("--segment", required=True, type=int)
    p.add_argument("--event-utc", required=True,
                   help="ISO8601 UTC release time, e.g. 2026-11-05T13:30:00Z")
    p.add_argument("--label", required=True)
    p.add_argument("--outdir", required=True, type=Path)
    args = p.parse_args()
    event_time = utc_epoch(args.event_utc)
    if not event_time.is_integer():
        p.error("Event time must be on an exact UTC second")
    event_epoch = int(event_time)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = [e for e in manifest["segments"] if e["index"] == args.segment]
    if len(entries) != 1 or entries[0]["state"] != "complete":
        p.error("Segment must be complete and appear exactly once in the manifest")
    audit_row = validate_audit(args.audit, args.segment, entries[0]["updates"])
    rows, replay_result = replay(args.manifest, args.segment, event_epoch)
    ordered = [rows[t] for t in sorted(rows)]
    wins = [window_stats(rows, event_epoch, *w) for w in WINDOWS]
    ends = [endpoint_stats(rows, event_epoch, k) for k in HORIZONS]
    baseline = wins[1]
    for w in wins:
        w["spread_ratio_to_pre60"] = w["mean_spread_bps"]/baseline["mean_spread_bps"] if (
            w["mean_spread_bps"] is not None and baseline["mean_spread_bps"] and baseline["coverage_pct"] >= 90) else None
        w["depth10_ratio_to_pre60"] = w["mean_total10_btc"]/baseline["mean_total10_btc"] if (
            w["mean_total10_btc"] is not None and baseline["mean_total10_btc"] and baseline["coverage_pct"] >= 90) else None
    output = {"research_question": "BTC/USD displayed liquidity and midpoint behavior around scheduled U.S. releases",
              "classification": "descriptive event study, no surprise attribution or causal inference",
              "event_label": args.label, "event_utc": utc_iso(event_epoch),
              "input_manifest": str(args.manifest), "input_audit": str(args.audit),
              "audit_status": audit_row["status"], "audit_updates_checked": int(audit_row["updates_checked"]),
              "replay": replay_result, "windows": wins, "endpoints": ends,
              "definitions": {
                  "sampling": "Last reconstructed L2 book message received in each UTC local receipt second, not a quote at exact second boundary",
                  "spread_bps": "(best ask minus best bid)/midpoint * 10000",
                  "top10_depth_btc": "Sum of displayed BTC quantities at the best 10 price levels on both sides",
                  "imbalance10": "(bid10 minus ask10)/(bid10 plus ask10)",
                  "mid_return_bps": "10000*log(midpoint at end of t+k receipt second / midpoint at end of t-1 receipt second)",
                  "short_endpoint_eligibility": "Both endpoint seconds and every t+0 through t+k second observed for k <= 60",
                  "long_endpoint_eligibility": "Endpoint-available with explicit path coverage; not a complete path if observed seconds are missing",
                  "volatility_proxy": "RMS of exact adjacent observed one-second midpoint log returns, bps",
                  "baseline_ratios": "Only given when >=90% of pre-60-second window has book observations"},
              "limitations": [
                  "Kraken WS local receipt timestamp is not synchronized exchange-time release latency",
                  "A receipt-second last quote can include post-release price discovery within the same second",
                  "Checksum PASS_FULL confirms recorded reconstruction consistency, not absolute absence of lost exchange events",
                  "Segment boundaries have separate snapshots and are never bridged",
                  "Only a single realized event for each category; differences are not causal event effects",
                  "No contemporaneous consensus-vs-actual surprises, matched control windows or confounder adjustment",
                  "Displayed depth is not realized fill liquidity; no executions, commissions, queue, slippage or trade profitability"
              ]}
    args.outdir.mkdir(parents=True, exist_ok=True)
    save_csv(args.outdir/"observed_seconds.csv", ordered)
    save_csv(args.outdir/"window_summary.csv", wins)
    save_csv(args.outdir/"endpoint_returns.csv", ends)
    (args.outdir/"event_report.json").write_text(json.dumps(output, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(f"EVENT: {args.label} at {utc_iso(event_epoch)}")
    print(f"AUDIT: {audit_row['status']} {int(audit_row['updates_checked']):,} updates; REPLAY: {replay_result['updates_replayed']:,} updates")
    print(f"RELEASE: last before {replay_result['last_update_before_event_utc']}; first after {replay_result['first_update_after_event_utc']}; gap {replay_result['release_update_gap_ms']} ms")
    print(f"SECONDS: observed {len(rows):,} / 1,501 in [-600,+900] event-time window")
    for w in wins:
        fmt = lambda v: f"{v:.5f}" if isinstance(v,(float,int)) else "NA"
        print(f"WINDOW {w['window']:<21} coverage={w['coverage_pct']:>6.2f}% spread_bps={fmt(w['mean_spread_bps'])} depth10_btc={fmt(w['mean_total10_btc'])} imbalance10={fmt(w['mean_imbalance10'])} RMS_return_bps={fmt(w['rms_1s_return_bps'])}")
    for e in ends:
        print(f"RETURN t+{e['horizon_s']:<4} {e['status']:<45} bps={e['mid_return_bps']}")
    print("OUTPUT:", args.outdir.resolve())
    print("NOTE: receipt-second descriptive response, not event-isolated impact or executable returns.")

if __name__ == "__main__":
    main()
