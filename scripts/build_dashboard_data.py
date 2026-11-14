"""Build the weekly measles time series behind the dashboard.

    uv run python scripts/build_dashboard_data.py            # 2022 to this year
    uv run python scripts/build_dashboard_data.py --from 2023

Writes data/dashboard/measles_weekly.csv: one row per reporting area per MMWR week, for the
nation (U.S. Residents), the 50 states, DC, New York City, and the territories. Values are as
CDC published them that week, so they include the reporting lag a reader saw at the time.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

from measles_sitrep.nndss import NATIONAL, area_kind, fetch_snapshot, mmwr_week_ending

OUT = Path(__file__).resolve().parent.parent / "data" / "dashboard" / "measles_weekly.csv"
COLUMNS = [
    "area", "area_type", "year", "week", "week_ending",
    "indigenous", "imported", "indigenous_ytd", "imported_ytd",
    "indigenous_ytd_prev", "imported_ytd_prev", "indigenous_added", "imported_added",
]


def added(snap, area: str, week: int, label: str):
    """Rise in the YTD count since the week before: this week's reports plus late reports
    for earlier weeks. Unlike CDC's current-week column, these add up to the YTD total."""
    cur = snap.get(area, week, label)
    if cur is None or cur.ytd is None:
        return ""
    if week == 1:
        return cur.ytd
    prev = snap.get(area, week - 1, label)
    return "" if prev is None or prev.ytd is None else cur.ytd - prev.ytd


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", type=int, default=2022)
    p.add_argument("--to", dest="end", type=int, default=dt.date.today().year)
    args = p.parse_args()

    rows = []
    for year in range(args.start, args.end + 1):
        snap = fetch_snapshot(year)
        print(f"{year}: {len(snap.rows)} rows through week {snap.week}")
        for area in snap.areas:
            kind = "national" if area == NATIONAL else area_kind(area)
            if kind not in ("national", "jurisdiction", "territory"):
                continue
            for week in range(1, snap.week + 1):
                ind, imp = snap.get(area, week, "indigenous"), snap.get(area, week, "imported")
                if ind is None and imp is None:
                    continue
                rows.append({
                    "area": area,
                    "area_type": {"jurisdiction": "state"}.get(kind, kind),
                    "year": year,
                    "week": week,
                    "week_ending": mmwr_week_ending(year, week).isoformat(),
                    "indigenous": ind.current if ind else "",
                    "imported": imp.current if imp else "",
                    "indigenous_ytd": ind.ytd if ind else "",
                    "imported_ytd": imp.ytd if imp else "",
                    "indigenous_ytd_prev": ind.ytd_prev if ind else "",
                    "imported_ytd_prev": imp.ytd_prev if imp else "",
                    "indigenous_added": added(snap, area, week, "indigenous"),
                    "imported_added": added(snap, area, week, "imported"),
                })
    rows.sort(key=lambda r: (r["area"] != NATIONAL, r["area"], r["year"], r["week"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows):,} rows to {OUT}")


if __name__ == "__main__":
    main()
