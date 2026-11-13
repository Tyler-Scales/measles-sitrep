"""Check the hard-coded numbers in evals/cases.yaml against the raw snapshot rows."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

from run_evals import load_cases  # noqa: E402

from measles_sitrep.nndss import NATIONAL, Snapshot  # noqa: E402

CASES = load_cases()


def raw_values(snap: Snapshot, area: str) -> set[int]:
    vals = set()
    for label in ("indigenous", "imported"):
        r = snap.get(area, snap.week, label)
        if r:
            vals |= {v for v in (r.current, r.ytd, r.ytd_prev) if v is not None}
    return vals


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_expected_numbers_are_in_the_data(case):
    snap = Snapshot.load(ROOT / "data" / "snapshots" / case["snapshot"])
    area = case.get("focus") if case.get("focus") in snap.areas else NATIONAL
    have = raw_values(snap, area) | raw_values(snap, NATIONAL)
    for n in case.get("expect", {}).get("numbers", []):
        assert n in have, f"{case['id']}: {n} not found for {area}"


def test_ids_unique_and_snapshots_exist():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) == 10
    for c in CASES:
        assert (ROOT / "data" / "snapshots" / c["snapshot"]).exists()
