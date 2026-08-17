"""
Aggregates scraped tee-sheet data (data/raw/teesheet.ndjson) into per-member
booking-concentration stats.

Two views, because the club's actual tee-time grid shifts slightly day to
day (7-10 minute intervals that aren't perfectly consistent):

  1. "bucket" view: slot times rounded to the nearest 15 minutes, so
     "7:30 AM" and "7:38 AM" on different days land in the same bucket.
  2. "ordinal" view: slots ranked by order within the day (1st tee time,
     2nd tee time, ...), which is robust to interval drift entirely and
     directly answers "who always gets the earliest slot."

A day only counts toward a bucket/ordinal-slot's denominator if that slot
existed that day AND wasn't blocked (closed, event, etc.) — so closures
don't get misread as "nobody wanted it."

Output: report.csv (bucket view) and report_ordinal.csv (ordinal view),
plus report.json with both plus supporting detail for the write-up.

Usage:
    python aggregate.py [--min-days 5] [--top-n 15]
"""
import argparse
import csv
import datetime
import json
import os
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
IN_FILE = os.path.join(DATA_DIR, "teesheet.ndjson")
OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "report")


def round_to_bucket(time_str, bucket_minutes=15):
    """'7:38 AM' -> '7:30 AM' style bucket, rounded down to bucket_minutes."""
    t = datetime.datetime.strptime(time_str, "%I:%M %p")
    minute = (t.minute // bucket_minutes) * bucket_minutes
    t = t.replace(minute=minute)
    return t.strftime("%I:%M %p").lstrip("0")


def load_days():
    days = []
    with open(IN_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            days.append(json.loads(line))
    days.sort(key=lambda d: d["date"])
    return days


def member_names_for_slot(slot):
    """Every member who appears anywhere in the slot that day (raw presence).

    This double-counts: when one member reserves all 4 spots and later fills
    TBDs with different friends, each friend shows up here as if they'd
    independently booked the slot, diluting the actual booker's numbers.
    """
    names = set()
    for party in slot["parties"]:
        for player in party:
            if player["type"] == "member":
                names.add(player["name"])
    return names


def bookers_for_slot(slot):
    """The member(s) who actually reserved each party in this slot.

    The booking member is listed first in the DOM for their party (they
    reserve up to 4 spots at once and invite others into the remaining TBDs
    later); guests/TBDs are already stripped out during scraping, so
    party[0] is the first *member* the reservation was made under. A slot
    can hold more than one independent party (e.g. two unrelated twosomes),
    so this yields one name per party, not one per slot.
    """
    names = []
    for party in slot["parties"]:
        if party and party[0]["type"] == "member":
            names.append(party[0]["name"])
    return names


def build_bucket_view(days, bucket_minutes=15):
    # bucket -> {"days_open": int, "member_counts": {...}, "booker_counts": {...}}
    stats = defaultdict(lambda: {
        "days_open": 0,
        "member_counts": defaultdict(int),
        "booker_counts": defaultdict(int),
    })
    for day in days:
        seen_buckets_today = set()
        for slot in day["slots"]:
            try:
                bucket = round_to_bucket(slot["time"], bucket_minutes)
            except ValueError:
                continue
            if slot["blocked_reason"]:
                continue
            if bucket not in seen_buckets_today:
                stats[bucket]["days_open"] += 1
                seen_buckets_today.add(bucket)
            for name in member_names_for_slot(slot):
                stats[bucket]["member_counts"][name] += 1
            for name in bookers_for_slot(slot):
                stats[bucket]["booker_counts"][name] += 1
    return stats


def build_ordinal_view(days):
    # ordinal (1-based position among non-blocked slots that day) -> stats
    stats = defaultdict(lambda: {
        "days_open": 0,
        "member_counts": defaultdict(int),
        "booker_counts": defaultdict(int),
    })
    for day in days:
        open_slots = [s for s in day["slots"] if not s["blocked_reason"]]
        for i, slot in enumerate(open_slots, start=1):
            stats[i]["days_open"] += 1
            for name in member_names_for_slot(slot):
                stats[i]["member_counts"][name] += 1
            for name in bookers_for_slot(slot):
                stats[i]["booker_counts"][name] += 1
    return stats


def rows_from_stats(stats, min_days, top_n, label_key):
    rows = []
    for key, data in stats.items():
        days_open = data["days_open"]
        if days_open < min_days:
            continue
        # Rank by booker_counts (who actually reserved the slot), not raw
        # presence — that's the number that reflects monopolization.
        ranked = sorted(data["booker_counts"].items(), key=lambda kv: -kv[1])[:top_n]
        for name, booker_count in ranked:
            present_count = data["member_counts"].get(name, 0)
            rows.append({
                label_key: key,
                "days_open": days_open,
                "member": name,
                "times_booked": present_count,
                "pct_of_days": round(100 * present_count / days_open, 1),
                "times_booker": booker_count,
                "pct_of_days_as_booker": round(100 * booker_count / days_open, 1),
            })
    return rows


def write_csv(rows, path, label_key):
    if not rows:
        return
    fieldnames = [label_key, "days_open", "member", "times_booked", "pct_of_days",
                  "times_booker", "pct_of_days_as_booker"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket-minutes", type=int, default=15)
    ap.add_argument("--min-days", type=int, default=5,
                     help="ignore slots/ordinals open on fewer than this many days")
    ap.add_argument("--top-n", type=int, default=15,
                     help="keep top N members per slot/ordinal")
    args = ap.parse_args()

    if not os.path.exists(IN_FILE):
        raise SystemExit(f"No data found at {IN_FILE}. Run scraper.py first.")

    days = load_days()
    if not days:
        raise SystemExit("No days in data file.")

    os.makedirs(OUT_DIR, exist_ok=True)

    bucket_stats = build_bucket_view(days, args.bucket_minutes)
    ordinal_stats = build_ordinal_view(days)

    bucket_rows = sorted(
        rows_from_stats(bucket_stats, args.min_days, args.top_n, "time_bucket"),
        key=lambda r: (r["time_bucket"], -r["pct_of_days_as_booker"]),
    )
    ordinal_rows = sorted(
        rows_from_stats(ordinal_stats, args.min_days, args.top_n, "ordinal_position"),
        key=lambda r: (r["ordinal_position"], -r["pct_of_days_as_booker"]),
    )

    write_csv(bucket_rows, os.path.join(OUT_DIR, "report_by_time.csv"), "time_bucket")
    write_csv(ordinal_rows, os.path.join(OUT_DIR, "report_by_ordinal.csv"), "ordinal_position")

    with open(os.path.join(OUT_DIR, "report.json"), "w") as f:
        json.dump({
            "date_range": {"from": days[0]["date"], "to": days[-1]["date"]},
            "total_days": len(days),
            "by_time_bucket": bucket_rows,
            "by_ordinal_position": ordinal_rows,
        }, f, indent=2)

    print(f"Scraped days: {len(days)} ({days[0]['date']} .. {days[-1]['date']})")
    print(f"Wrote {len(bucket_rows)} time-bucket rows -> data/report/report_by_time.csv")
    print(f"Wrote {len(ordinal_rows)} ordinal-position rows -> data/report/report_by_ordinal.csv")
    print("Also wrote data/report/report.json")


if __name__ == "__main__":
    main()
