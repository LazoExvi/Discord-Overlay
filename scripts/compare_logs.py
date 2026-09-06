"""Compare two exported combat-log CSVs from the same recording.

Usage:  python scripts/compare_logs.py run1-log.csv run2-log.csv [--gap 8]

Reports how much of the fight each log covers, any silences longer than the
fight timeout (which reset the on-screen totals unless running totals are on),
and the per-actor damage difference between the runs.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DAMAGE_KINDS = {"damage_out", "damage_in", "damage_other"}


def load(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "Time" not in rows[0]:
        raise SystemExit(f"{path} is not a log export (use Export current data > log).")
    return rows


def summarize(name: str, rows: list[dict[str, str]], gap: float) -> dict[str, int]:
    times = [datetime.fromisoformat(r["Time"]) for r in rows]
    span = (times[-1] - times[0]).total_seconds() if times else 0.0
    print(f"\n== {name}: {len(rows)} lines over {span:.0f}s "
          f"({times[0].strftime('%H:%M:%S') if times else '-'} to {times[-1].strftime('%H:%M:%S') if times else '-'})")
    gaps = [(times[i - 1], (times[i] - times[i - 1]).total_seconds())
            for i in range(1, len(times)) if (times[i] - times[i - 1]).total_seconds() >= gap]
    if gaps:
        print(f"   {len(gaps)} silence(s) of {gap:g}s or more (each one ended the fight on screen):")
        for at, seconds in gaps:
            print(f"     {at.strftime('%H:%M:%S')}  {seconds:.0f}s quiet")
    else:
        print(f"   no silences of {gap:g}s or more")
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        if row["Type"] in DAMAGE_KINDS:
            totals[row["Actor"]] += int(row["Amount"] or 0)
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--gap", type=float, default=8.0, help="fight timeout in seconds (default 8)")
    args = parser.parse_args()

    first = summarize(args.first.name, load(args.first), args.gap)
    second = summarize(args.second.name, load(args.second), args.gap)

    print(f"\n{'Actor':<28}{'Run 1':>12}{'Run 2':>12}{'Diff':>10}")
    for actor in sorted(set(first) | set(second), key=lambda a: -max(first.get(a, 0), second.get(a, 0))):
        a, b = first.get(actor, 0), second.get(actor, 0)
        diff = f"{100.0 * (b - a) / a:+.1f}%" if a else "new"
        print(f"{actor:<28}{a:>12,}{b:>12,}{diff:>10}")


if __name__ == "__main__":
    main()
