"""Command line: `sitrep fetch | facts | draft`."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import analysis
from .nndss import Snapshot, fetch_snapshot

SNAPSHOT_DIR = Path("data/snapshots")


def _load_or_fetch(args) -> Snapshot:
    if args.snapshot:
        return Snapshot.load(args.snapshot)
    year = args.year or dt.date.today().year
    print(f"Fetching NNDSS measles rows for {year} from data.cdc.gov ...", file=sys.stderr)
    snap = fetch_snapshot(year, args.week)
    path = snap.save(SNAPSHOT_DIR / f"{snap.year}-w{snap.week:02d}.json")
    print(f"Saved {len(snap.rows)} rows (through week {snap.week}) to {path}", file=sys.stderr)
    return snap


def cmd_fetch(args) -> None:
    _load_or_fetch(args)


def cmd_facts(args) -> None:
    """Print the figures the agent would see. Needs no API key."""
    snap = _load_or_fetch(args)
    facts = {
        "reporting_period": analysis.reporting_period(snap),
        "national": analysis.national_summary(snap, args.week),
        "top_jurisdictions_this_week": analysis.jurisdiction_rankings(snap, args.week, top_n=5)["top"],
        "newly_affected": analysis.newly_affected(snap, args.week)["newly_affected"],
    }
    print(json.dumps(facts, indent=2))


def cmd_draft(args) -> None:
    from .agent import draft_sitrep

    from .tools import summarize_call

    snap = _load_or_fetch(args)
    trace = (lambda c: print(f"  -> {summarize_call(c)}", file=sys.stderr, flush=True)) if args.verbose else None
    try:
        res = draft_sitrep(snap, week=args.week, audience=args.audience, focus=args.focus,
                           model=args.model, effort=args.effort, on_tool_call=trace)
    except TypeError as e:
        if "authentication" not in str(e):
            raise
        sys.exit("No Claude credentials found. Set ANTHROPIC_API_KEY (or run `ant auth login`) and retry.")
    out = Path(args.out or f"reports/sitrep-{snap.year}-w{(args.week or snap.week):02d}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(res.markdown + "\n")
    print(res.markdown)
    print(
        f"\n---\n{len(res.tool_calls)} tool calls · {res.input_tokens:,} input tokens "
        f"({res.cache_read_tokens:,} from cache) · {res.output_tokens:,} output tokens · "
        f"model {res.model} · saved to {out}",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sitrep", description="Measles situation reports from CDC NNDSS data")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--snapshot", help="Use a saved snapshot JSON instead of fetching")
        sp.add_argument("--year", type=int, help="MMWR year to fetch (default: this year)")
        sp.add_argument("--week", type=int, help="MMWR week (default: latest published)")

    common(sub.add_parser("fetch", help="Download and save a snapshot"))
    common(sub.add_parser("facts", help="Print key figures (no API key needed)"))
    d = sub.add_parser("draft", help="Draft a sitrep with Claude")
    common(d)
    d.add_argument("--audience", default="state and local public health officials")
    d.add_argument("--focus", help='e.g. "Pennsylvania" or "imported cases"')
    d.add_argument("--model", default=None)
    d.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    d.add_argument("--out", help="Where to save the Markdown")
    d.add_argument("-v", "--verbose", action="store_true", help="Print each tool call as it happens")

    args = p.parse_args(argv)
    if args.cmd == "draft":
        from .agent import DEFAULT_EFFORT, DEFAULT_MODEL
        args.model = args.model or DEFAULT_MODEL
        args.effort = args.effort or DEFAULT_EFFORT
    {"fetch": cmd_fetch, "facts": cmd_facts, "draft": cmd_draft}[args.cmd](args)


if __name__ == "__main__":
    main()
