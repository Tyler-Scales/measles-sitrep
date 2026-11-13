"""Graders for measles sitrep drafts.

The deterministic checks (always run, free) cover facts: numbers, jurisdictions, trend,
caveats, and invented figures. An optional LLM judge scores what regexes can't: faithfulness
to the tool outputs, clarity for the audience, and how actionable the recommendations are.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from measles_sitrep.nndss import REGIONS, Snapshot, area_kind

REQUIRED_SECTIONS = [
    "Summary", "Key figures", "Geographic distribution", "Trend",
    "Data notes and limitations", "Recommended public health actions",
]
TREND_WORDS = {
    "increasing": r"increas|rising|rise|accelerat|upward|growing|grew",
    "decreasing": r"decreas|declin|falling|fell|downward|lower",
    "stable": r"stable|steady|flat|plateau|level|little change|roughly unchanged",
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


# ---- helpers ------------------------------------------------------------------------------------
def _num_pattern(n: int | float) -> str:
    if isinstance(n, float) and not n.is_integer():
        return re.escape(str(n))
    n = int(n)
    plain, comma = str(abs(n)), f"{abs(n):,}"
    alts = {re.escape(plain), re.escape(comma)}
    return r"(?<![\d.,])(?:" + "|".join(sorted(alts)) + r")(?![\d]|,\d)"


def has_number(text: str, n: int | float) -> bool:
    return re.search(_num_pattern(n), text) is not None


def has_pct(text: str, pct: float) -> bool:
    mag = abs(pct)
    candidates = {f"{mag:.1f}", f"{round(mag):d}"}
    for c in candidates:
        if re.search(r"(?<![\d.])" + re.escape(c) + r"\s*(%|percent)", text, re.I):
            return True
    ratio = 1 + pct / 100
    if ratio > 1.5:  # "3.2 times", "3.2-fold", "more than triple" is not checked
        for c in {f"{ratio:.1f}", f"{ratio:.0f}"}:
            if re.search(r"(?<![\d.])" + re.escape(c) + r"[\s-]*(times|fold|x\b)", text, re.I):
                return True
    return False


def section(text: str, name: str) -> str | None:
    m = re.search(rf"^#{{1,3}}\s*{re.escape(name)}\b.*$", text, re.I | re.M)
    if not m:
        return None
    nxt = re.search(r"^#{1,3}\s", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


def mentioned_jurisdictions(text: str, snap: Snapshot) -> set[str]:
    """Jurisdiction names in the text. Longer names are matched first, so "West Virginia"
    doesn't count as "Virginia" and "New York City" doesn't count as "New York"."""
    names = [a for a in snap.areas if area_kind(a) in ("jurisdiction", "territory")]
    names += ["NYC", "Washington, D.C.", "Washington DC", "D.C."]
    found, scrub = set(), text
    for name in sorted(names, key=len, reverse=True):
        pat = re.compile(r"\b" + re.escape(name) + r"(?![A-Za-z])")
        if pat.search(scrub):
            canon = {"NYC": "New York City", "Washington, D.C.": "District of Columbia",
                     "Washington DC": "District of Columbia", "D.C.": "District of Columbia"}.get(name, name)
            found.add(canon)
            scrub = pat.sub(" ", scrub)
    return found


def allowed_jurisdictions(snap: Snapshot) -> set[str]:
    """Jurisdictions with any measles this year or by this point last year, in either label."""
    ok = set()
    for r in snap.rows:
        if r.week == snap.week and area_kind(r.area) in ("jurisdiction", "territory"):
            if (r.ytd or 0) > 0 or (r.ytd_prev or 0) > 0:
                ok.add(r.area)
    return ok


def valid_numbers(snap: Snapshot, area: str) -> set[int]:
    """Every count a draft could truthfully attach to `area`: weekly, YTD, prior-year YTD,
    52-week max, YTD added, recent weekly counts, and 4-week totals."""
    vals: set[int] = set()
    for label in ("indigenous", "imported"):
        for w in range(max(1, snap.week - 11), snap.week + 1):
            r = snap.get(area, w, label)
            if r:
                vals |= {v for v in (r.current, r.ytd, r.ytd_prev, r.max52) if v is not None}
        cur, prev = snap.get(area, snap.week, label), snap.get(area, snap.week - 1, label)
        if cur and prev and cur.ytd is not None and prev.ytd is not None:
            vals.add(cur.ytd - prev.ytd)
        for end in (snap.week, snap.week - 4):
            window = [snap.get(area, w, label) for w in range(end - 3, end + 1)]
            if all(x and x.current is not None for x in window):
                vals.add(sum(x.current for x in window))
        if cur and snap.get(area, snap.week, "imported") and snap.get(area, snap.week, "indigenous"):
            a, b = snap.get(area, snap.week, "indigenous"), snap.get(area, snap.week, "imported")
            vals |= {(a.ytd or 0) + (b.ytd or 0), (a.current or 0) + (b.current or 0)}
    return vals


def misattributed_numbers(text: str, snap: Snapshot) -> list[str]:
    """Find "<Jurisdiction> (N)" and "<Jurisdiction> reported N cases" claims whose N isn't one of
    that jurisdiction's real figures."""
    bad = []
    names = [a for a in snap.areas if area_kind(a) in ("jurisdiction", "territory", "region")]
    for name in sorted(names, key=len, reverse=True):
        pats = [
            rf"\b{re.escape(name)}(?: State)?(?: \(excl\.? NYC\))?\s*\((\d[\d,]*)\)",
            rf"\b{re.escape(name)}\b(?! City)[^.\n|(]{{0,40}}?\breported\s+(\d[\d,]*)\b",
        ]
        valid = valid_numbers(snap, name)
        for pat in pats:
            for m in re.finditer(pat, text):
                n = int(m.group(1).replace(",", ""))
                if n not in valid:
                    bad.append(m.group(0))
        text = re.sub(rf"\b{re.escape(name)}\b", " ", text)  # so "New York" won't rematch "New York City"
    return bad


OUTCOME_FABRICATION = re.compile(
    r"\b\d[\d,.]*\s*%?\s*(?:\w+\s){0,3}?(deaths?|died|hospitali[sz]ations?|hospitali[sz]ed|"
    r"unvaccinated|vaccinated|fatalit)",
    re.I,
)


# ---- the grader ---------------------------------------------------------------------------------
def grade(case: dict, markdown: str, snap: Snapshot, tool_calls: list[dict] | None = None) -> list[Check]:
    exp = case.get("expect", {})
    text = markdown
    checks: list[Check] = []

    if exp.get("sections", True):
        missing = [s for s in REQUIRED_SECTIONS if section(text, s) is None]
        checks.append(Check("sections", not missing, f"missing: {missing}" if missing else ""))
        checks.append(Check(
            "provisional_caveat",
            re.search(r"provisional|subject to (change|revision)", text, re.I) is not None,
        ))

    for n in exp.get("numbers", []):
        checks.append(Check(f"number:{n}", has_number(text, n)))
    for p in exp.get("pct", []):
        checks.append(Check(f"pct:{p}", has_pct(text, p)))
    for a in exp.get("areas", []):
        checks.append(Check(f"area:{a}", re.search(r"\b" + re.escape(a) + r"\b", text) is not None))

    if "trend" in exp:
        body = section(text, "Trend") or ""
        ok = re.search(TREND_WORDS[exp["trend"]], body, re.I) is not None
        checks.append(Check(f"trend:{exp['trend']}", ok, "" if ok else "direction word not in ## Trend"))

    if exp.get("revision_note"):
        ok = re.search(r"late[- ]report|delayed|revis|backfill|reported late|earlier weeks", text, re.I)
        checks.append(Check("revision_note", ok is not None))

    for pat in exp.get("must_contain", []):
        checks.append(Check(f"contains:/{pat}/", re.search(pat, text, re.I | re.M) is not None))
    for pat in exp.get("must_not_contain", []):
        m = re.search(pat, text, re.I | re.M)
        checks.append(Check(f"not_contains:/{pat}/", m is None, f"found: {m.group(0)!r}" if m else ""))

    # --- always-on safety checks ---
    scrubbed = re.sub(r"New York City", "", text)
    if re.search(r"\bNew York\b", scrubbed):
        ok = re.search(r"excl|excluding|outside (of )?(New York City|NYC)|not including|upstate|separate", text, re.I)
        checks.append(Check("ny_nyc_disambiguation", ok is not None))

    extra = mentioned_jurisdictions(text, snap) - allowed_jurisdictions(snap) - set(REGIONS)
    if case.get("focus"):
        extra -= {case["focus"]}
    checks.append(Check("no_unsupported_jurisdictions", not extra, f"named without data: {sorted(extra)}" if extra else ""))

    wrong = misattributed_numbers(text, snap)
    checks.append(Check("jurisdiction_numbers_match_data", not wrong, f"found: {wrong}" if wrong else ""))

    fab = [m.group(0) for m in OUTCOME_FABRICATION.finditer(text)]
    checks.append(Check("no_invented_outcomes", not fab, f"found: {fab}" if fab else ""))

    if tool_calls is not None:
        called = {c["tool"] for c in tool_calls}
        for t in exp.get("tools", []):
            checks.append(Check(f"tool:{t}", t in called))
        if case.get("focus") and "get_area_summary" in exp.get("tools", []):
            hit = any(c["tool"] == "get_area_summary" and
                      case["focus"].lower() in str(c["input"].get("area", "")).lower() for c in tool_calls)
            checks.append(Check("tool:focus_area_looked_up", hit))

    return checks


# ---- optional LLM judge -------------------------------------------------------------------------
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "integer", "description": "1-5: every claim is supported by the tool outputs"},
        "audience_fit": {"type": "integer", "description": "1-5: clarity and tone for the stated audience"},
        "actionability": {"type": "integer", "description": "1-5: recommendations follow from the data"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["faithfulness", "audience_fit", "actionability", "unsupported_claims", "rationale"],
    "additionalProperties": False,
}

JUDGE_PROMPT = """\
You are reviewing a draft measles situation report written by an AI agent from CDC NNDSS data.
Below are the exact tool outputs the agent received, then the request, then the draft.

Score the draft from 1 to 5 on each dimension:
- faithfulness: every number and factual claim is supported by the tool outputs. Any invented
  figure, misread number, or claim about data the tools don't provide caps this at 2.
- audience_fit: clear, well organized, and right for this audience: {audience}
- actionability: recommendations are reasonable, standard measles-response actions that follow
  from the data, without invented specifics.
{focus_line}
List each unsupported claim word for word in unsupported_claims (an empty list if none).

<tool_outputs>
{tool_outputs}
</tool_outputs>

<request>
{request}
</request>

<draft>
{draft}
</draft>
"""


def judge(case: dict, request: str, markdown: str, tool_calls: list[dict], client, model: str) -> dict:
    focus_line = f"Also consider: {case['expect']['judge_focus']}" if case.get("expect", {}).get("judge_focus") else ""
    prompt = JUDGE_PROMPT.format(
        audience=case.get("audience", ""), focus_line=focus_line,
        tool_outputs=json.dumps(tool_calls, indent=1), request=request, draft=markdown,
    )
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        return {"error": "judge declined"}
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)
