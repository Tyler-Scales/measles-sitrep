"""Run the sitrep eval set.

    uv run python evals/run_evals.py                       # run every case with Claude
    uv run python evals/run_evals.py --cases national-latest focus-new-york
    uv run python evals/run_evals.py --judge               # also score with an LLM judge
    uv run python evals/run_evals.py --regrade runs/<dir>  # re-grade saved drafts, no API calls

Each run saves its drafts, tool logs, and a results.json under runs/<timestamp>/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evals"))

from graders import grade, judge  # noqa: E402
from measles_sitrep.nndss import Snapshot  # noqa: E402

SNAPSHOTS = ROOT / "data" / "snapshots"


def load_cases(path: Path = ROOT / "evals" / "cases.yaml") -> list[dict]:
    spec = yaml.safe_load(path.read_text())
    return [spec.get("defaults", {}) | c for c in spec["cases"]]


def run_case(case: dict, out_dir: Path, args) -> dict:
    snap = Snapshot.load(SNAPSHOTS / case["snapshot"])
    saved = out_dir / f"{case['id']}.json"
    if args.regrade:
        rec = json.loads(saved.read_text())
    else:
        from measles_sitrep.agent import draft_sitrep

        try:
            res = draft_sitrep(snap, week=case.get("week"), audience=case["audience"],
                               focus=case.get("focus"), extra=case.get("extra"),
                               model=args.model, effort=args.effort)
            rec = {"request": res.request, "markdown": res.markdown, "tool_calls": res.tool_calls,
                   "model": res.model, "usage": {"input": res.input_tokens, "output": res.output_tokens,
                                                 "cache_read": res.cache_read_tokens}}
        except Exception as e:  # record the failure and keep going
            rec = {"request": "", "markdown": "", "tool_calls": [], "error": f"{type(e).__name__}: {e}"}
        (out_dir / f"{case['id']}.md").write_text(rec["markdown"] + "\n")

    checks = grade(case, rec["markdown"], snap, rec["tool_calls"]) if rec["markdown"] else []
    rec["checks"] = [c.__dict__ for c in checks]
    rec["passed"] = bool(checks) and all(c.passed for c in checks)
    if args.judge and rec["markdown"]:
        import anthropic

        rec["judge"] = judge(case, rec["request"], rec["markdown"], rec["tool_calls"],
                             anthropic.Anthropic(), args.judge_model)
    saved.write_text(json.dumps(rec, indent=1))
    return {"id": case["id"], **rec}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", nargs="*", help="Only run these case ids")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="high")
    p.add_argument("--judge", action="store_true", help="Also score each draft with an LLM judge")
    p.add_argument("--judge-model", default="claude-opus-5-5")
    p.add_argument("--regrade", metavar="RUN_DIR", help="Re-grade drafts saved in RUN_DIR (no API calls)")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    cases = load_cases()
    if args.cases:
        cases = [c for c in cases if c["id"] in set(args.cases)]
    out_dir = Path(args.regrade) if args.regrade else ROOT / "runs" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: run_case(c, out_dir, args), cases))

    print(f"\n{'case':<28} {'result':<7} {'checks':>7}  failures")
    print("-" * 90)
    for r in results:
        n_ok = sum(c["passed"] for c in r["checks"])
        fails = r.get("error") or ", ".join(
            c["name"] + (f" ({c['detail']})" if c["detail"] else "") for c in r["checks"] if not c["passed"])
        j = r.get("judge")
        jtxt = f"  judge F{j['faithfulness']}/A{j['audience_fit']}/R{j['actionability']}" if j and "error" not in j else ""
        print(f"{r['id']:<28} {'PASS' if r['passed'] else 'FAIL':<7} {n_ok:>3}/{len(r['checks']):<3}  {fails}{jtxt}")
    n_pass = sum(r["passed"] for r in results)
    total_checks = sum(len(r["checks"]) for r in results)
    ok_checks = sum(sum(c["passed"] for c in r["checks"]) for r in results)
    print("-" * 90)
    print(f"{n_pass}/{len(results)} cases passed · {ok_checks}/{total_checks} checks passed · saved to {out_dir}")
    (out_dir / "results.json").write_text(json.dumps(
        {"model": args.model, "effort": args.effort, "cases_passed": n_pass, "cases": len(results),
         "checks_passed": ok_checks, "checks": total_checks,
         "results": [{"id": r["id"], "passed": r["passed"], "checks": r["checks"], "judge": r.get("judge"),
                      "error": r.get("error")} for r in results]}, indent=1))


if __name__ == "__main__":
    main()
