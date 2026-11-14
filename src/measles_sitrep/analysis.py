"""Deterministic measles metrics computed from an NNDSS snapshot.

The agent reads every number in a sitrep from these functions (through the tools in
tools.py). The model does no arithmetic of its own, and the evals check the draft against
the same figures.
"""

from __future__ import annotations

from .nndss import NATIONAL, REGIONS, Snapshot, area_kind, mmwr_week_ending

TREND_WINDOW = 4  # weeks
TREND_THRESHOLD = 0.20  # ±20% between consecutive 4-week windows counts as a change
MIN_BASE_FOR_PCT = 20  # below this, a % change misleads (12 -> 1,474 would read "+12,183%")

ALIASES = {
    "nyc": "New York City", "new york city": "New York City",
    "dc": "District of Columbia", "washington dc": "District of Columbia",
    "washington, dc": "District of Columbia", "washington d.c.": "District of Columbia",
    "us": NATIONAL, "u.s.": NATIONAL, "usa": NATIONAL, "united states": NATIONAL,
    "national": NATIONAL, "nation": NATIONAL,
    "upstate new york": "New York", "new york state": "New York",
}


class DataError(ValueError):
    """Request can't be answered from the snapshot (unknown area, week not published...)."""


def pct_change(new: int | None, old: int | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round(100.0 * (new - old) / old, 1)


def check_week(snap: Snapshot, week: int | None) -> int:
    week = snap.week if week is None else int(week)
    if week < 1 or week > snap.week:
        raise DataError(
            f"MMWR week {week} of {snap.year} is not in this data. NNDSS has published "
            f"{snap.year} through week {snap.week} (ending {mmwr_week_ending(snap.year, snap.week)})."
        )
    return week


def resolve_area(snap: Snapshot, name: str) -> str:
    key = name.strip().lower()
    if key in ALIASES:
        return ALIASES[key]
    for area in snap.areas:
        if area.lower() == key:
            return area
    raise DataError(f"'{name}' is not an NNDSS reporting area. Known areas: {', '.join(snap.areas)}")


def _ytd_added(snap: Snapshot, area: str, week: int, label: str) -> int | None:
    """Rise in the YTD count since the week before. It counts this week's cases plus late
    reports and revisions for earlier weeks, so it can differ from the weekly count."""
    cur = snap.get(area, week, label)
    if week == 1:
        return cur.ytd if cur else None
    prev = snap.get(area, week - 1, label)
    if not cur or not prev or cur.ytd is None or prev.ytd is None:
        return None
    return cur.ytd - prev.ytd


def trend(snap: Snapshot, area: str, week: int, label: str = "indigenous") -> dict:
    """Compare weekly reported cases in the latest 4 weeks with the 4 weeks before."""
    def window(end: int) -> int | None:
        vals = [snap.get(area, w, label) for w in range(end - TREND_WINDOW + 1, end + 1)]
        if any(v is None or v.current is None for v in vals) or end - TREND_WINDOW + 1 < 1:
            return None
        return sum(v.current for v in vals)

    recent, prior = window(week), window(week - TREND_WINDOW)
    if recent is None or prior is None:
        direction = "insufficient data"
    elif prior == 0:
        direction = "increasing" if recent > 0 else "no recent cases"
    else:
        change = (recent - prior) / prior
        direction = (
            "increasing" if change > TREND_THRESHOLD
            else "decreasing" if change < -TREND_THRESHOLD
            else "stable"
        )
    return {
        "label": label,
        "weeks_compared": (
            f"weeks {week - TREND_WINDOW + 1}-{week} vs weeks {week - 2 * TREND_WINDOW + 1}-{week - TREND_WINDOW}"
        ),
        "recent_4wk_cases": recent,
        "prior_4wk_cases": prior,
        "pct_change": pct_change(recent, prior),
        "direction": direction,
        "rule": "increasing/decreasing if the 4-week total changed by more than 20%, otherwise stable",
    }


def _label_block(snap: Snapshot, area: str, week: int, label: str) -> dict:
    r = snap.get(area, week, label)
    if r is None:
        return {"available": False}
    return {
        "cases_this_week": r.current,
        "cases_this_week_flag": r.current_flag,
        "ytd": r.ytd,
        "ytd_same_week_last_year": r.ytd_prev,
        "ytd_pct_change_vs_last_year": (
            pct_change(r.ytd, r.ytd_prev) if (r.ytd_prev or 0) >= MIN_BASE_FOR_PCT else None
        ),
        "ytd_comparison_note": (
            None if (r.ytd_prev or 0) >= MIN_BASE_FOR_PCT
            else f"Last year's YTD was under {MIN_BASE_FOR_PCT}, so give both counts instead of a % change."
        ),
        "max_weekly_cases_prior_52_weeks": r.max52,
        "ytd_added_since_last_week": _ytd_added(snap, area, week, label),
    }


def area_summary(snap: Snapshot, area: str, week: int | None = None) -> dict:
    week = check_week(snap, week)
    area = resolve_area(snap, area)
    ind = _label_block(snap, area, week, "indigenous")
    imp = _label_block(snap, area, week, "imported")
    total_ytd = None
    if ind.get("ytd") is not None and imp.get("ytd") is not None:
        total_ytd = ind["ytd"] + imp["ytd"]
    return {
        "area": area,
        "area_type": area_kind(area),
        "mmwr_year": snap.year,
        "mmwr_week": week,
        "week_ending": mmwr_week_ending(snap.year, week).isoformat(),
        "indigenous": ind,
        "imported": imp,
        "total_ytd_all_measles": total_ytd,
        "trend_indigenous": trend(snap, area, week, "indigenous"),
    }


def national_summary(snap: Snapshot, week: int | None = None) -> dict:
    return area_summary(snap, NATIONAL, week)


def jurisdiction_rankings(
    snap: Snapshot, week: int | None = None, label: str = "indigenous",
    sort_by: str = "cases_this_week", top_n: int = 10,
) -> dict:
    week = check_week(snap, week)
    if label not in ("indigenous", "imported"):
        raise DataError("label must be 'indigenous' or 'imported'")
    keys = {"cases_this_week": "current", "ytd": "ytd", "ytd_added_since_last_week": "added"}
    if sort_by not in keys:
        raise DataError(f"sort_by must be one of {sorted(keys)}")
    rows = []
    for area in snap.areas:
        if area_kind(area) not in ("jurisdiction", "territory"):
            continue
        r = snap.get(area, week, label)
        if r is None:
            continue
        rows.append({
            "area": area,
            "current": r.current,
            "ytd": r.ytd,
            "ytd_prev": r.ytd_prev,
            "added": _ytd_added(snap, area, week, label),
        })
    k = keys[sort_by]
    nat = snap.get(NATIONAL, week, label)
    nat_ytd = nat.ytd if nat else None
    rows.sort(key=lambda x: (-(x[k] or 0), -(x["ytd"] or 0), x["area"]))
    with_cases_ytd = [x for x in rows if (x["ytd"] or 0) > 0]
    with_cases_week = [x for x in rows if (x["current"] or 0) > 0]
    return {
        "mmwr_year": snap.year,
        "mmwr_week": week,
        "label": label,
        "sorted_by": sort_by,
        "jurisdictions_with_cases_this_week": len(with_cases_week),
        "jurisdictions_with_cases_ytd": len(with_cases_ytd),
        "top": [
            {
                "area": x["area"],
                "cases_this_week": x["current"],
                "ytd": x["ytd"],
                "ytd_same_week_last_year": x["ytd_prev"],
                "ytd_added_since_last_week": x["added"],
                "share_of_national_ytd_pct": (
                    round(100 * x["ytd"] / nat_ytd, 1) if nat_ytd and x["ytd"] is not None else None
                ),
            }
            for x in rows[: max(1, min(int(top_n), 60))]
            if (x[k] or 0) > 0 or sort_by != "cases_this_week"
        ],
        "national_ytd": nat_ytd,
        "note": "New York means New York State excluding New York City; NNDSS reports NYC separately.",
    }


def regional_breakdown(snap: Snapshot, week: int | None = None) -> dict:
    week = check_week(snap, week)
    out = []
    for region in sorted(REGIONS):
        r = snap.get(region, week, "indigenous")
        if r is None:
            continue
        out.append({
            "region": region,
            "cases_this_week": r.current,
            "ytd": r.ytd,
            "ytd_same_week_last_year": r.ytd_prev,
            "trend": trend(snap, region, week)["direction"],
        })
    out.sort(key=lambda x: -(x["ytd"] or 0))
    return {"mmwr_year": snap.year, "mmwr_week": week, "label": "indigenous",
            "census_divisions": out}


def newly_affected(snap: Snapshot, week: int | None = None, lookback: int = 4) -> dict:
    """Jurisdictions whose first measles case of the year (either label) arrived in the last
    `lookback` weeks."""
    week = check_week(snap, week)
    found = []
    for area in snap.areas:
        if area_kind(area) not in ("jurisdiction", "territory"):
            continue
        def total_ytd(w: int) -> int:
            return sum((snap.get(area, w, lb).ytd or 0) for lb in ("indigenous", "imported")
                       if snap.get(area, w, lb))
        if total_ytd(week) == 0:
            continue
        first = next((w for w in range(1, week + 1) if total_ytd(w) > 0), None)
        if first is not None and first > week - lookback:
            found.append({"area": area, "first_reported_week": first, "ytd_now": total_ytd(week)})
    return {"mmwr_year": snap.year, "mmwr_week": week, "lookback_weeks": lookback,
            "definition": (f"Jurisdictions whose first measles case of {snap.year}, indigenous or "
                           f"imported, was reported in weeks {week - lookback + 1}-{week}."),
            "newly_affected": sorted(found, key=lambda x: x["first_reported_week"])}


def weekly_series(snap: Snapshot, area: str, weeks: int = 8, end_week: int | None = None) -> dict:
    end = check_week(snap, end_week)
    area = resolve_area(snap, area)
    start = max(1, end - int(weeks) + 1)
    series = []
    for w in range(start, end + 1):
        ind, imp = snap.get(area, w, "indigenous"), snap.get(area, w, "imported")
        series.append({
            "week": w,
            "week_ending": mmwr_week_ending(snap.year, w).isoformat(),
            "indigenous_cases": ind.current if ind else None,
            "imported_cases": imp.current if imp else None,
            "indigenous_ytd": ind.ytd if ind else None,
        })
    return {"area": area, "mmwr_year": snap.year, "series": series}


def reporting_period(snap: Snapshot) -> dict:
    return {
        "mmwr_year": snap.year,
        "latest_mmwr_week": snap.week,
        "week_ending": mmwr_week_ending(snap.year, snap.week).isoformat(),
        "weeks_available": f"1-{snap.week}",
        "data_fetched_at": snap.fetched_at,
        "source": snap.source,
        "dataset": "CDC NNDSS Weekly Data (provisional), labels 'Measles, Indigenous' and 'Measles, Imported'",
    }
