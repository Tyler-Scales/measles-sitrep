"""Build the README screenshots from committed outputs of a live run.

    uv run python docs/screenshots/make_screenshots.py

Inputs (all committed):
  docs/examples/sitrep-2026-w44.tools.json   tool calls from the live run
  docs/examples/sitrep-2026-w44.md           the draft Claude wrote
  evals/results/*.json                       the latest eval scorecard

Renders each as HTML and captures it with headless Google Chrome.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "screenshots"
sys.path.insert(0, str(ROOT / "src"))
from measles_sitrep.tools import summarize_call  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTH = 1280

TERMINAL_CSS = """
body { margin: 0; background: #0b0f17; }
.win { margin: 28px; background: #0d1117; border: 1px solid #30363d; border-radius: 12px;
       box-shadow: 0 12px 40px rgba(0,0,0,.45); overflow: hidden; }
.bar { height: 38px; background: #161b22; display: flex; align-items: center; padding: 0 14px;
       gap: 8px; border-bottom: 1px solid #30363d; }
.dot { width: 12px; height: 12px; border-radius: 50%; }
.title { color: #8b949e; font: 13px -apple-system, Helvetica, sans-serif; margin-left: 12px; }
pre { margin: 0; padding: 18px 22px 22px; color: #e6edf3; font: 15px/1.55 Menlo, monospace;
      white-space: pre-wrap; word-break: break-word; }
.cmd { color: #7ee787; font-weight: bold; } .muted { color: #8b949e; } .tool { color: #79c0ff; }
.pass { color: #3fb950; font-weight: bold; } .warn { color: #d29922; } .num { color: #f0f6fc; }
"""

DOC_CSS = """
body { margin: 0; background: #eef0f3; }
.page { margin: 28px; background: #fff; border: 1px solid #d0d7de; border-radius: 10px;
        padding: 36px 48px; box-shadow: 0 8px 30px rgba(31,35,40,.12);
        font: 16px/1.6 -apple-system, "Helvetica Neue", Helvetica, sans-serif; color: #1f2328; }
h1 { font-size: 26px; margin: 0 0 18px; padding-bottom: 10px; border-bottom: 1px solid #d8dee4; }
h2 { font-size: 20px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #eaeef2; }
table { border-collapse: collapse; margin: 10px 0 14px; font-size: 15px; }
th, td { border: 1px solid #d0d7de; padding: 6px 12px; text-align: left; }
th { background: #f6f8fa; } tr:nth-child(even) td { background: #fafbfc; }
p, li { margin: 6px 0; }
"""


def terminal_page(title: str, body_html: str) -> str:
    dots = "".join(f'<span class="dot" style="background:{c}"></span>' for c in ("#ff5f56", "#ffbd2e", "#27c93f"))
    return (f"<!doctype html><meta charset=utf-8><style>{TERMINAL_CSS}</style>"
            f'<div class="win"><div class="bar">{dots}<span class="title">{html.escape(title)}</span></div>'
            f"<pre>{body_html}</pre></div>")


def trace_html() -> str:
    rec = json.loads((ROOT / "docs/examples/sitrep-2026-w44.tools.json").read_text())
    lines = ['<span class="cmd">$ uv run sitrep draft --verbose --snapshot data/snapshots/2026-w44.json</span>', ""]
    for call in rec["tool_calls"]:
        head, _, res = summarize_call(call).partition("  ->  ")
        lines.append(f'  <span class="muted">-&gt;</span> <span class="tool">{html.escape(head)}</span>')
        lines.append(f'       <span class="muted">{html.escape(res)}</span>')
    lines += ["", f'<span class="muted">{len(rec["tool_calls"])} tool calls, then Claude writes the report '
                  f'({html.escape(rec["model"])})</span>']
    return terminal_page("sitrep draft --verbose", "\n".join(lines))


def scorecard_html() -> str:
    path = sorted((ROOT / "evals" / "results").glob("*.json"))[-1]
    res = json.loads(path.read_text())
    lines = ['<span class="cmd">$ uv run python evals/run_evals.py --judge</span>', "",
             f'<span class="muted">{"case":<28} {"result":<7} {"checks":>7}   judge (faithfulness/audience/actionability)</span>',
             '<span class="muted">' + "-" * 92 + "</span>"]
    for r in res["results"]:
        ok = sum(c["passed"] for c in r["checks"])
        j = r.get("judge") or {}
        judge = (f'{j["faithfulness"]} / {j["audience_fit"]} / {j["actionability"]}'
                 if "faithfulness" in j else "not judged")
        cls = "warn" if ("faithfulness" in j and j["faithfulness"] < 4) or "faithfulness" not in j else "num"
        verdict = '<span class="pass">PASS</span>   ' if r["passed"] else '<span class="warn">FAIL</span>   '
        lines.append(f'{html.escape(r["id"]):<28} {verdict}{ok:>3}/{len(r["checks"]):<3}    '
                     f'<span class="{cls}">{judge}</span>')
    lines += ['<span class="muted">' + "-" * 92 + "</span>",
              f'<span class="pass">{res["cases_passed"]}/{res["cases"]} cases passed</span> · '
              f'{res["checks_passed"]}/{res["checks"]} checks passed · '
              f'<span class="muted">{html.escape(res["model"])}, effort {html.escape(res["effort"])}</span>']
    return terminal_page("evals/run_evals.py", "\n".join(lines))


def sitrep_html() -> str:
    md = (ROOT / "docs/examples/sitrep-2026-w44.md").read_text()
    body = markdown.markdown(md, extensions=["tables"])
    return f'<!doctype html><meta charset=utf-8><style>{DOC_CSS}</style><div class="page">{body}</div>'


def shoot(page: str, out: Path, height: int) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(page)
    subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
        f"--window-size={WIDTH},{height}", f"--screenshot={out}", f"file://{f.name}",
    ], check=True, capture_output=True)
    Path(f.name).unlink()
    print(f"Wrote {out.relative_to(ROOT)}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    n_calls = len(json.loads((ROOT / "docs/examples/sitrep-2026-w44.tools.json").read_text())["tool_calls"])
    shoot(trace_html(), OUT / "agent-trace.png", 190 + 47 * n_calls)
    shoot(sitrep_html(), OUT / "sitrep.png", 1180)
    shoot(scorecard_html(), OUT / "eval-scorecard.png", 470)


if __name__ == "__main__":
    main()
