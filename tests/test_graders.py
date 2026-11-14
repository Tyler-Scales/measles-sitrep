"""The graders must pass a correct draft and catch each kind of error."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

from graders import grade, has_number, has_pct, mentioned_jurisdictions  # noqa: E402
from run_evals import load_cases  # noqa: E402

from measles_sitrep.nndss import Snapshot  # noqa: E402

GOOD = (ROOT / "tests" / "fixtures" / "handwritten_sitrep_2026w44.md").read_text()


@pytest.fixture(scope="module")
def snap():
    return Snapshot.load(ROOT / "data" / "snapshots" / "2026-w44.json")


@pytest.fixture(scope="module")
def case():
    return next(c for c in load_cases() if c["id"] == "national-latest")


def failed(checks):
    return {c.name for c in checks if not c.passed}


def test_good_draft_passes(case, snap):
    assert failed(grade(case, GOOD, snap)) == set()


def test_wrong_number(case, snap):
    assert "number:4991" in failed(grade(case, GOOD.replace("4,991", "4,919"), snap))


def test_invented_state(case, snap):
    # Delaware has had no measles this year or last, so naming it at all is unsupported.
    bad = GOOD.replace("Minnesota (20) led", "Minnesota (20) and Delaware (4) led")
    assert "no_unsupported_jurisdictions" in failed(grade(case, bad, snap))


def test_misattributed_number(case, snap):
    # Iowa had cases last year (so it may be named) but none this week.
    bad = GOOD.replace("Minnesota (20) led", "Minnesota (20) and Iowa (4) led")
    assert "jurisdiction_numbers_match_data" in failed(grade(case, bad, snap))
    swapped = GOOD.replace("Wisconsin (58)", "Wisconsin (85)")
    assert "jurisdiction_numbers_match_data" in failed(grade(case, swapped, snap))


def test_invented_outcomes(case, snap):
    bad = GOOD.replace("## Trend", "There were 12 hospitalizations and 1 death.\n\n## Trend")
    assert "no_invented_outcomes" in failed(grade(case, bad, snap))
    advice = GOOD.replace("- Promote MMR", "1. **Get vaccinated.** Promote MMR")
    assert "no_invented_outcomes" not in failed(grade(case, advice, snap))


def test_ny_without_disambiguation(case, snap):
    bad = GOOD.replace("New York State (excl. NYC)", "New York")
    assert "ny_nyc_disambiguation" in failed(grade(case, bad, snap))


def test_wrong_trend_and_missing_section(case, snap):
    bad = GOOD.replace("Stable: 614", "Rising: 614").replace("## Data notes and limitations", "## Notes")
    f = failed(grade(case, bad, snap))
    assert {"trend:stable", "sections"} <= f


def test_tool_check(case, snap):
    f = failed(grade(case, GOOD, snap, tool_calls=[{"tool": "get_reporting_period", "input": {}}]))
    assert {"tool:get_national_summary", "tool:get_jurisdiction_rankings"} <= f


def test_summary_sentence_count(case, snap):
    from graders import count_sentences, section
    assert count_sentences(section(GOOD, "Summary")) == 4
    assert count_sentences("U.S. cases rose 219.7% vs. 2025. New York State (excl. NYC) led.") == 2
    long = GOOD.replace("reported the most cases this week.", "reported the most cases this week. One. Two. Three.", 1)
    assert "summary_3_to_5_sentences" in failed(grade(case, long, snap))


def test_number_and_pct_matching():
    assert has_number("total of 4,991 cases", 4991) and has_number("4991 cases", 4991)
    assert not has_number("14,991 cases", 4991) and not has_number("4,9910", 4991)
    assert has_pct("up 220% from", 219.7) and has_pct("219.7 percent", 219.7)
    assert has_pct("3.2 times last year", 219.7)
    assert has_pct("down 35%", -35.4)


def test_jurisdiction_matching_prefers_longest(snap):
    found = mentioned_jurisdictions("West Virginia and New York City, not Virginia's", snap)
    assert found == {"West Virginia", "New York City", "Virginia"}
