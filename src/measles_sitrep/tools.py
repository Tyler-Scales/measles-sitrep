"""Tools the sitrep agent calls. Each one wraps an analysis function over a fixed snapshot.

Tools return JSON strings. Errors (an unknown area, a week not yet published) come back as
{"error": ...} so the model can explain the gap in the report instead of guessing.
"""

from __future__ import annotations

import json
from typing import Callable

from anthropic import beta_tool

from . import analysis
from .nndss import Snapshot


def _call(log: list[dict], name: str, fn: Callable[[], dict], args: dict) -> str:
    try:
        out = fn()
    except analysis.DataError as e:
        out = {"error": str(e)}
    log.append({"tool": name, "input": args, "output": out})
    return json.dumps(out, indent=1)


def make_tools(snap: Snapshot, log: list[dict]) -> list:
    """Build the agent's tools around `snap`. Each call is appended to `log` (used by evals)."""

    @beta_tool
    def get_reporting_period() -> str:
        """Return the MMWR year and latest published week in the data, the week-ending date,
        and source details. Call this first, so the report states the right period."""
        return _call(log, "get_reporting_period", lambda: analysis.reporting_period(snap), {})

    @beta_tool
    def get_national_summary(week: int | None = None) -> str:
        """National (U.S. residents) measles figures for one MMWR week: weekly cases,
        year-to-date (YTD) total, YTD at the same point last year with % change, the largest
        weekly count in the prior 52 weeks, and a 4-week trend. Indigenous (U.S.-acquired)
        and imported cases are reported separately.

        Args:
            week: MMWR week number. Omit for the latest published week.
        """
        return _call(log, "get_national_summary",
                     lambda: analysis.national_summary(snap, week), {"week": week})

    @beta_tool
    def get_jurisdiction_rankings(
        week: int | None = None,
        label: str = "indigenous",
        sort_by: str = "cases_this_week",
        top_n: int = 10,
    ) -> str:
        """Rank states, DC, NYC, and territories by measles cases. Includes how many
        jurisdictions reported cases this week and year to date, and each one's share of
        the national YTD total.

        Args:
            week: MMWR week number. Omit for the latest published week.
            label: "indigenous" (acquired in the U.S.) or "imported" (acquired abroad).
            sort_by: "cases_this_week", "ytd", or "ytd_added_since_last_week".
            top_n: How many jurisdictions to return (1-60).
        """
        args = {"week": week, "label": label, "sort_by": sort_by, "top_n": top_n}
        return _call(log, "get_jurisdiction_rankings",
                     lambda: analysis.jurisdiction_rankings(snap, week, label, sort_by, top_n), args)

    @beta_tool
    def get_area_summary(area: str, week: int | None = None) -> str:
        """Measles figures for one reporting area (a state, "New York City", "District of
        Columbia", a territory, or a census division such as "Mountain"). Same fields as the
        national summary. Use this for any jurisdiction you discuss in detail.

        Args:
            area: Reporting area name, e.g. "Texas" or "New York City".
            week: MMWR week number. Omit for the latest published week.
        """
        return _call(log, "get_area_summary",
                     lambda: analysis.area_summary(snap, area, week), {"area": area, "week": week})

    @beta_tool
    def get_weekly_series(area: str, weeks: int = 8) -> str:
        """Week-by-week counts of indigenous and imported cases for one area (use "U.S.
        Residents" for the nation), ending at the latest published week.

        Args:
            area: Reporting area name.
            weeks: Number of weeks to return (1-52).
        """
        return _call(log, "get_weekly_series",
                     lambda: analysis.weekly_series(snap, area, weeks), {"area": area, "weeks": weeks})

    @beta_tool
    def get_regional_breakdown(week: int | None = None) -> str:
        """Indigenous measles cases by the 9 U.S. census divisions, with the trend in each.

        Args:
            week: MMWR week number. Omit for the latest published week.
        """
        return _call(log, "get_regional_breakdown",
                     lambda: analysis.regional_breakdown(snap, week), {"week": week})

    @beta_tool
    def get_newly_affected_jurisdictions(week: int | None = None) -> str:
        """Jurisdictions whose first measles case of the year was reported in the last 4 weeks.

        Args:
            week: MMWR week number. Omit for the latest published week.
        """
        return _call(log, "get_newly_affected_jurisdictions",
                     lambda: analysis.newly_affected(snap, week), {"week": week})

    return [
        get_reporting_period, get_national_summary, get_jurisdiction_rankings, get_area_summary,
        get_weekly_series, get_regional_breakdown, get_newly_affected_jurisdictions,
    ]
