import datetime as dt
from pathlib import Path

import pytest

from measles_sitrep import analysis as a
from measles_sitrep.nndss import NATIONAL, Snapshot, area_kind, mmwr_week_ending, parse_row

SNAPS = Path(__file__).resolve().parent.parent / "data" / "snapshots"


@pytest.fixture(scope="module")
def w44():
    return Snapshot.load(SNAPS / "2026-w44.json")


def test_old_upper_case_area_names():
    from measles_sitrep.nndss import canonical_area
    assert canonical_area("US RESIDENTS") == NATIONAL
    assert canonical_area("NEW YORK CITY") == "New York City"
    assert canonical_area("NORTHERN MARIANA ISLANDS") == "Commonwealth of Northern Mariana Islands"
    assert canonical_area("Texas") == "Texas"
    r = parse_row({"states": "WEST VIRGINIA", "year": "2023", "week": "5", "label": "Measles, Imported", "m1": "1"})
    assert r.area == "West Virginia" and area_kind(r.area) == "jurisdiction"


def test_parse_row_flags():
    r = parse_row({"states": "Iowa", "year": "2026", "week": "44", "label": "Measles, Indigenous",
                   "m1_flag": "-", "m2": "1.0", "m3_flag": "-", "m4": "7.0"})
    assert (r.current, r.max52, r.ytd, r.ytd_prev, r.label) == (0, 1, 0, 7, "indigenous")
    assert parse_row({"states": "Iowa", "year": "2026", "week": "1", "label": "Mumps"}) is None
    unavailable = parse_row({"states": "X", "year": "2026", "week": "1", "label": "Measles, Imported",
                             "m1_flag": "U"})
    assert unavailable.current is None


@pytest.mark.parametrize("year,week,ending", [
    (2026, 44, dt.date(2026, 11, 7)), (2025, 10, dt.date(2025, 3, 8)),
    (2025, 1, dt.date(2025, 1, 4)), (2026, 1, dt.date(2026, 1, 10)), (2021, 1, dt.date(2021, 1, 9)),
])
def test_mmwr_week_ending(year, week, ending):
    assert mmwr_week_ending(year, week) == ending


@pytest.mark.parametrize("snap_file", sorted(p.name for p in SNAPS.glob("*.json")))
@pytest.mark.parametrize("label", ["indigenous", "imported"])
def test_jurisdictions_sum_to_national(snap_file, label):
    s = Snapshot.load(SNAPS / snap_file)
    juris = [s.get(x, s.week, label) for x in s.areas if area_kind(x) == "jurisdiction"]
    nat = s.get(NATIONAL, s.week, label)
    assert sum(r.current or 0 for r in juris if r) == nat.current
    assert sum(r.ytd or 0 for r in juris if r) == nat.ytd


def test_national_summary(w44):
    n = a.national_summary(w44)
    assert n["week_ending"] == "2026-11-07"
    assert n["indigenous"]["cases_this_week"] == 196
    assert n["indigenous"]["ytd"] == 4991
    assert n["indigenous"]["ytd_pct_change_vs_last_year"] == 219.7
    assert n["indigenous"]["ytd_added_since_last_week"] == 363
    assert n["trend_indigenous"]["direction"] == "stable"


def test_small_prior_year_suppresses_pct(w44):
    pa = a.area_summary(w44, "Pennsylvania")["indigenous"]
    assert pa["ytd_same_week_last_year"] == 12
    assert pa["ytd_pct_change_vs_last_year"] is None
    assert "both counts" in pa["ytd_comparison_note"]


def test_unpublished_week_and_unknown_area(w44):
    with pytest.raises(a.DataError, match="through week 44"):
        a.national_summary(w44, 50)
    with pytest.raises(a.DataError, match="not an NNDSS reporting area"):
        a.area_summary(w44, "Atlantis")


def test_aliases(w44):
    assert a.resolve_area(w44, "nyc") == "New York City"
    assert a.resolve_area(w44, "texas") == "Texas"
    assert a.resolve_area(w44, "United States") == NATIONAL


def test_rankings(w44):
    r = a.jurisdiction_rankings(w44, top_n=3)
    assert [x["area"] for x in r["top"]] == ["Wisconsin", "Pennsylvania", "New York"]
    assert r["jurisdictions_with_cases_this_week"] == 12
    assert r["top"][1]["share_of_national_ytd_pct"] == 29.5
