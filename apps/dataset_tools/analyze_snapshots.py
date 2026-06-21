#!/usr/bin/env python3
"""analyze_snapshots.py

For every snapshot in a given folder, finds all matching pipeline.log entries
and writes a detailed frame-by-frame report to a text file.

Usage
-----
  python apps/dataset_tools/analyze_snapshots.py
  python apps/dataset_tools/analyze_snapshots.py --snapshots snapshots/2026-06-10 --out report.txt
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ── Regex patterns ────────────────────────────────────────────────────────────

RE_LOG_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})")

RE_DIAG_FRAME = re.compile(
    r"\[DIAG\] cam=(\S+) track=(\d+) frame=(\d+)"
    r" face=(\d+)x(\d+) blur=([\d.]+) quality=([\d.]+) pose_w=([\d.]+)"
    r" \| (.+?) \| margin=([\d.]+) stab=(\S+)"
)
RE_DIAG_DECISION = re.compile(
    r"\[DIAG DECISION\] cam=(\S+) track=(\d+) frames=(\d+) elapsed=([\d.]+)s"
    r" \| consensus: (.+?) \| margin=([\d.]+)"
    r" \| best_frame=([\d.]+) avg_frame=([\d.]+) median_frame=([\d.]+)"
    r" \| id_switches=(\d+) reject_reason=(\S+)"
    r" → (\S+) \(threshold=([\d.]+)\)"
)
RE_DIAG_CLASS = re.compile(
    r"\[DIAG CLASS\] cam=(\S+) track=(\d+) state=(\S+)"
    r" best=([\d.]+) switches=(\d+) consensus=([\d.]+) candidate=(\S+)"
)
RE_SKIP_SMALL = re.compile(r"\[(\S+)\] track=(\d+) SKIP: face too small \((.+?)\)")
RE_SKIP_BLUR  = re.compile(r"\[(\S+)\] track=(\d+) SKIP: too blurry \((.+?)\)")
RE_SKIP_POSE  = re.compile(r"cam=(\S+) track=(\d+) SKIP: pose_w=([\d.]+)")
RE_TOP_ID     = re.compile(r"(\S+):([\d.]+)")


def parse_log_ts(line: str) -> Optional[datetime]:
    m = RE_LOG_TS.match(line)
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)}.{m.group(2)}", "%Y-%m-%d %H:%M:%S.%f")


def parse_snapshot_filename(name: str):
    """Return (dt, camera_id, identity) from filename stem, or None on failure."""
    stem = Path(name).stem
    parts = stem.split("_")
    if len(parts) < 5:
        return None
    try:
        dt = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S")
    except ValueError:
        return None
    camera_id = f"{parts[2]}_{parts[3]}"   # camera_01 / camera_02
    identity  = "_".join(parts[4:])         # unknown / b27_arif / ...
    return dt, camera_id, identity


def load_log(log_path: Path):
    """
    Parse the full pipeline.log in one pass.
    Returns:
      decisions : list of dicts (one per DIAG DECISION line)
      frames    : dict  (camera_id, track_id) → list of frame dicts
      classes   : dict  (camera_id, track_id, decision_ts_str) → class dict
      skips     : dict  (camera_id, track_id) → list of skip dicts
    """
    decisions = []
    frames    = defaultdict(list)
    classes   = {}
    skips     = defaultdict(list)

    print(f"Loading {log_path} ...", end=" ", flush=True)
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            ts = parse_log_ts(line)
            if ts is None:
                continue

            # DIAG DECISION
            m = RE_DIAG_DECISION.search(line)
            if m:
                decisions.append({
                    "ts": ts,
                    "camera": m.group(1),
                    "track":  int(m.group(2)),
                    "frames": int(m.group(3)),
                    "elapsed": float(m.group(4)),
                    "consensus_str": m.group(5),
                    "margin": float(m.group(6)),
                    "best_frame": float(m.group(7)),
                    "avg_frame":  float(m.group(8)),
                    "med_frame":  float(m.group(9)),
                    "id_switches": int(m.group(10)),
                    "reject_reason": m.group(11),
                    "event": m.group(12),
                    "threshold": float(m.group(13)),
                })
                continue

            # DIAG CLASS — append rather than overwrite so that a later pass
            # of the same track ID does not clobber an earlier one.
            m = RE_DIAG_CLASS.search(line)
            if m:
                key = (m.group(1), int(m.group(2)))
                classes.setdefault(key, []).append({
                    "ts": ts,
                    "state": m.group(3),
                    "best": float(m.group(4)),
                    "switches": int(m.group(5)),
                    "consensus": float(m.group(6)),
                    "candidate": m.group(7),
                })
                continue

            # DIAG frame
            m = RE_DIAG_FRAME.search(line)
            if m:
                top_ids = RE_TOP_ID.findall(m.group(9))
                frames[(m.group(1), int(m.group(2)))].append({
                    "ts": ts,
                    "frame":   int(m.group(3)),
                    "w":       int(m.group(4)),
                    "h":       int(m.group(5)),
                    "blur":    float(m.group(6)),
                    "quality": float(m.group(7)),
                    "pose_w":  float(m.group(8)),
                    "top_ids": top_ids,   # [(id, score), ...]
                    "margin":  float(m.group(10)),
                    "stab":    m.group(11),
                })
                continue

            # SKIP too small
            m = RE_SKIP_SMALL.search(line)
            if m:
                skips[(m.group(1), int(m.group(2)))].append(
                    {"ts": ts, "reason": f"too small ({m.group(3)})"}
                )
                continue

            # SKIP too blurry
            m = RE_SKIP_BLUR.search(line)
            if m:
                skips[(m.group(1), int(m.group(2)))].append(
                    {"ts": ts, "reason": f"too blurry ({m.group(3)})"}
                )
                continue

    print(f"done — {len(decisions)} decisions, {sum(len(v) for v in frames.values())} frames.")
    return decisions, frames, classes, skips


def find_decision(decisions, snap_dt: datetime, camera_id: str, window_sec: float = 4.0):
    """Find the DIAG DECISION entry closest to snap_dt for the given camera."""
    best = None
    best_delta = timedelta(seconds=window_sec)
    for d in decisions:
        if d["camera"] != camera_id:
            continue
        delta = abs(d["ts"] - snap_dt)
        if delta < best_delta:
            best_delta = delta
            best = d
    return best


def session_frames(all_frames, camera_id: str, track_id: int, decision_ts: datetime, window_sec: float = 10.0):
    """Return frames for this track that fall within [decision_ts - window_sec, decision_ts + 1s]."""
    lo = decision_ts - timedelta(seconds=window_sec)
    hi = decision_ts + timedelta(seconds=1.0)
    return [
        f for f in all_frames.get((camera_id, track_id), [])
        if lo <= f["ts"] <= hi
    ]


def session_skips(all_skips, camera_id: str, track_id: int, decision_ts: datetime, window_sec: float = 10.0):
    lo = decision_ts - timedelta(seconds=window_sec)
    hi = decision_ts + timedelta(seconds=1.0)
    return [
        s for s in all_skips.get((camera_id, track_id), [])
        if lo <= s["ts"] <= hi
    ]


def format_top1(top_ids):
    if not top_ids:
        return "—", "—"
    return top_ids[0][0], top_ids[0][1]


def write_report(snap_files, decisions, all_frames, classes, all_skips, out_path: Path):
    total = len(snap_files)
    matched = 0
    unmatched = []

    with open(out_path, "w", encoding="utf-8") as out:
        out.write("=" * 100 + "\n")
        out.write("SNAPSHOT ANALYSIS REPORT\n")
        out.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"Snapshots : {total}\n")
        out.write("=" * 100 + "\n\n")

        for i, snap in enumerate(sorted(snap_files), 1):
            parsed = parse_snapshot_filename(snap.name)
            if parsed is None:
                out.write(f"[{i}/{total}] SKIP (cannot parse filename): {snap.name}\n\n")
                continue

            snap_dt, camera_id, identity = parsed
            decision = find_decision(decisions, snap_dt, camera_id)

            out.write("─" * 100 + "\n")
            out.write(f"[{i}/{total}] {snap.name}\n")
            out.write(f"  Camera   : {camera_id}\n")
            out.write(f"  Snap time: {snap_dt.strftime('%H:%M:%S')}\n")
            out.write(f"  Identity : {identity}\n")

            if decision is None:
                out.write("  [NO MATCHING DECISION FOUND IN LOG — possibly outside log window]\n\n")
                unmatched.append(snap.name)
                continue

            matched += 1
            track_id = decision["track"]

            # Consensus top identity
            cons_ids = RE_TOP_ID.findall(decision["consensus_str"])
            cons_top = cons_ids[0] if cons_ids else ("?", "0")

            out.write(f"  Track ID : {track_id}\n")
            out.write(f"  Decision : {decision['event']}  score={float(cons_top[1]):.4f}  threshold={decision['threshold']}\n")
            out.write(f"  Consensus: {decision['consensus_str']}\n")
            out.write(f"  Stats    : frames={decision['frames']}  elapsed={decision['elapsed']:.2f}s"
                      f"  best={decision['best_frame']:.3f}  avg={decision['avg_frame']:.3f}"
                      f"  median={decision['med_frame']:.3f}  switches={decision['id_switches']}"
                      f"  margin={decision['margin']:.3f}\n")

            # DIAG CLASS — pick the entry closest in time to this decision
            cls_list = classes.get((camera_id, track_id), [])
            cls = min(cls_list, key=lambda c: abs(c["ts"] - decision["ts"])) if cls_list else None
            if cls:
                out.write(f"  DIAG CLASS: {cls['state']}  candidate={cls['candidate']}"
                          f"  best={cls['best']:.3f}  switches={cls['switches']}"
                          f"  consensus={cls['consensus']:.3f}\n")
            else:
                # Compute classification from decision signals (for older entries before feature was added)
                if decision["event"] == "AUTHORIZED":
                    cls_state = "AUTHORIZED"
                elif decision["id_switches"] <= 2 and decision["best_frame"] >= 0.40:
                    cls_state = "LOW_CONFIDENCE_MATCH"
                else:
                    cls_state = "NO_STABLE_MATCH"
                out.write(f"  DIAG CLASS: {cls_state}  [inferred — no DIAG CLASS line in log]\n")

            out.write("\n")

            # Skips before decision
            skips = session_skips(all_skips, camera_id, track_id, decision["ts"])
            if skips:
                out.write("  PRE-GATE SKIPS:\n")
                for s in skips:
                    out.write(f"    {s['ts'].strftime('%H:%M:%S.%f')[:-3]}  {s['reason']}\n")
                out.write("\n")

            # Frame table
            frames = session_frames(all_frames, camera_id, track_id, decision["ts"])
            if frames:
                hdr = f"  {'Frame':>5}  {'Time':>12}  {'Face':>9}  {'Blur':>6}  {'pose_w':>6}  {'Top-1 identity':<22}  {'Score':>6}  {'2nd':>6}  {'Stab':>6}"
                out.write(hdr + "\n")
                out.write("  " + "-" * (len(hdr) - 2) + "\n")
                for fr in frames:
                    top1_id, top1_sc = format_top1(fr["top_ids"])
                    top2_sc = fr["top_ids"][1][1] if len(fr["top_ids"]) >= 2 else "—"
                    out.write(
                        f"  {fr['frame']:>5}"
                        f"  {fr['ts'].strftime('%H:%M:%S.%f')[:-3]:>12}"
                        f"  {fr['w']:>4}x{fr['h']:<4}"
                        f"  {fr['blur']:>6.1f}"
                        f"  {fr['pose_w']:>6.2f}"
                        f"  {top1_id:<22}"
                        f"  {float(top1_sc):>6.3f}"
                        f"  {float(top2_sc) if top2_sc != '—' else 0.0:>6.3f}"
                        f"  {fr['stab']:>6}\n"
                    )
            else:
                out.write("  [NO FRAME DATA — DIAG logging may have been off at this time]\n")

            out.write("\n")

        # Summary
        out.write("=" * 100 + "\n")
        out.write("SUMMARY\n")
        out.write(f"  Total snapshots : {total}\n")
        out.write(f"  Matched to log  : {matched}\n")
        out.write(f"  Unmatched       : {len(unmatched)}\n")
        if unmatched:
            out.write("\n  Unmatched files:\n")
            for f in unmatched:
                out.write(f"    {f}\n")
        out.write("=" * 100 + "\n")

    print(f"\nReport written to: {out_path}")
    print(f"Matched {matched}/{total} snapshots.")
    if unmatched:
        print(f"Unmatched: {len(unmatched)} (no log entry within ±4s)")


def main():
    parser = argparse.ArgumentParser(description="Analyze snapshots against pipeline.log")
    parser.add_argument(
        "--snapshots",
        default=r"C:\Users\acer\Desktop\TDI\Ha-meem\FR\ha_meem_ai_surveillance\snapshots\2026-06-10",
        help="Folder containing snapshot JPEGs",
    )
    parser.add_argument(
        "--log",
        default=r"C:\Users\acer\Desktop\TDI\Ha-meem\FR\ha_meem_ai_surveillance\logs\pipeline.log",
        help="Path to pipeline.log",
    )
    parser.add_argument(
        "--out",
        default=r"C:\Users\acer\Desktop\TDI\Ha-meem\FR\ha_meem_ai_surveillance\snapshot_analysis.txt",
        help="Output text file",
    )
    args = parser.parse_args()

    snap_dir = Path(args.snapshots)
    log_path = Path(args.log)
    out_path = Path(args.out)

    if not snap_dir.exists():
        print(f"ERROR: snapshot folder not found: {snap_dir}")
        sys.exit(1)
    if not log_path.exists():
        print(f"ERROR: log file not found: {log_path}")
        sys.exit(1)

    snap_files = sorted(snap_dir.glob("*.jpg"))
    if not snap_files:
        print(f"No .jpg files found in {snap_dir}")
        sys.exit(1)

    print(f"Found {len(snap_files)} snapshots in {snap_dir}")

    decisions, all_frames, classes, all_skips = load_log(log_path)
    write_report(snap_files, decisions, all_frames, classes, all_skips, out_path)


if __name__ == "__main__":
    main()
