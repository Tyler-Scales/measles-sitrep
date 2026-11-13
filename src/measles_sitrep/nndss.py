"""Load weekly measles rows from CDC's NNDSS Weekly Data table (data.cdc.gov, dataset x9gk-5huc).

The table holds one row per (reporting area, MMWR year, MMWR week, disease label), as published
that week. Measles comes in two labels: "Measles, Indigenous" (acquired in the U.S.) and
"Measles, Imported" (acquired abroad).

Value columns:
  m1  current week          m2  max of the previous 52 weeks
  m3  year-to-date (YTD)    m4  YTD for the same point in the previous year
Each has a *_flag column; "-" means no cases were reported (we store it as 0). Other flags
(e.g. "U" unavailable, "N" not reportable) mean the number is missing, and we store None.

A snapshot is every measles row for one MMWR year up to and including one week. Because the
rows are stored as published, a snapshot shows what was known that week, so tests and evals
can be repeated exactly.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

DATASET_ID = "x9gk-5huc"
API_URL = f"https://data.cdc.gov/resource/{DATASET_ID}.json"
SOURCE_PAGE = f"https://data.cdc.gov/d/{DATASET_ID}"
LABELS = {"Measles, Indigenous": "indigenous", "Measles, Imported": "imported"}

# NNDSS reporting areas that are aggregates rather than single jurisdictions.
NATIONAL = "U.S. Residents"
AGGREGATES = {"U.S. Residents", "U.S. Territories", "Non-U.S. Residents", "Total"}
REGIONS = {
    "New England", "Middle Atlantic", "East North Central", "West North Central",
    "South Atlantic", "East South Central", "West South Central", "Mountain", "Pacific",
}
TERRITORIES = {
    "American Samoa", "Commonwealth of Northern Mariana Islands", "Guam", "Puerto Rico",
    "U.S. Virgin Islands",
}


def area_kind(area: str) -> str:
    if area in AGGREGATES:
        return "aggregate"
    if area in REGIONS:
        return "region"
    if area in TERRITORIES:
        return "territory"
    return "jurisdiction"  # 50 states, DC, and NYC (NNDSS reports NYC apart from New York)


@dataclass(frozen=True)
class Row:
    area: str
    year: int
    week: int
    label: str  # "indigenous" | "imported"
    current: int | None
    current_flag: str | None
    max52: int | None
    ytd: int | None
    ytd_prev: int | None


def _num(raw: dict, col: str) -> int | None:
    if col in raw and raw[col] not in ("", None):
        return int(float(raw[col]))
    return 0 if raw.get(f"{col}_flag") == "-" else None


def parse_row(raw: dict) -> Row | None:
    label = LABELS.get(raw.get("label", ""))
    if label is None:
        return None
    return Row(
        area=raw["states"],
        year=int(raw["year"]),
        week=int(raw["week"]),
        label=label,
        current=_num(raw, "m1"),
        current_flag=raw.get("m1_flag"),
        max52=_num(raw, "m2"),
        ytd=_num(raw, "m3"),
        ytd_prev=_num(raw, "m4"),
    )


@dataclass
class Snapshot:
    year: int
    week: int
    fetched_at: str
    rows: list[Row]
    source: str = SOURCE_PAGE

    # ---- persistence -------------------------------------------------------------------------
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": self.source,
            "dataset": DATASET_ID,
            "year": self.year,
            "week": self.week,
            "fetched_at": self.fetched_at,
            "rows": [asdict(r) for r in self.rows],
        }
        path.write_text(json.dumps(payload, separators=(",", ":")))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "Snapshot":
        d = json.loads(Path(path).read_text())
        return cls(
            year=d["year"], week=d["week"], fetched_at=d["fetched_at"],
            rows=[Row(**r) for r in d["rows"]], source=d.get("source", SOURCE_PAGE),
        )

    # ---- lookups ------------------------------------------------------------------------------
    def get(self, area: str, week: int, label: str) -> Row | None:
        if not hasattr(self, "_index"):
            self._index = {(r.area, r.week, r.label): r for r in self.rows}
        return self._index.get((area, week, label))

    @property
    def areas(self) -> list[str]:
        return sorted({r.area for r in self.rows})


def fetch_snapshot(year: int, week: int | None = None, timeout: float = 60) -> Snapshot:
    """Download every measles row for `year`, up to `week` (default: latest published week)."""
    where = f"year='{year}' AND label in ('Measles, Indigenous','Measles, Imported')"
    rows: list[Row] = []
    offset, page = 0, 5000
    while True:
        resp = requests.get(
            API_URL,
            params={"$where": where, "$limit": page, "$offset": offset, "$order": ":id"},
            timeout=timeout,
        )
        resp.raise_for_status()
        batch = resp.json()
        rows.extend(r for r in (parse_row(b) for b in batch) if r is not None)
        if len(batch) < page:
            break
        offset += page
    if not rows:
        raise ValueError(f"NNDSS returned no measles rows for {year}")
    latest = max(r.week for r in rows)
    week = latest if week is None else week
    if week > latest:
        raise ValueError(f"NNDSS has published {year} only through week {latest}, not week {week}")
    rows = sorted((r for r in rows if r.week <= week), key=lambda r: (r.week, r.label, r.area))
    return Snapshot(
        year=year, week=week, rows=rows,
        fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    )


def mmwr_week_ending(year: int, week: int) -> dt.date:
    """Saturday that ends MMWR week `week` of `year`. Week 1 is the first week with ≥4 days in January."""
    # MMWR weeks run Sunday to Saturday. Week 1 holds January 4, so it starts on the
    # Sunday on or before that date. (Python's weekday(): Monday=0 ... Sunday=6.)
    jan4 = dt.date(year, 1, 4)
    week1_start = jan4 - dt.timedelta(days=(jan4.weekday() + 1) % 7)
    return week1_start + dt.timedelta(days=7 * (week - 1) + 6)
