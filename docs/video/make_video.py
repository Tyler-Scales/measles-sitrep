"""Build docs/walkthrough.mp4: narrated slides, about 2 minutes long.

    uv run python docs/video/make_video.py

Needs macOS (`say` for the narration) and the dev dependencies (Pillow, imageio-ffmpeg).
Terminal slides show real output: the script runs the commands while it builds.
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "docs" / "video" / "build"
OUT = ROOT / "docs" / "walkthrough.mp4"
W, H = 1920, 1080
VOICE, RATE = "Samantha", 198

BG, PANEL, INK, MUTED = (14, 20, 34), (8, 11, 18), (236, 239, 244), (148, 160, 180)
ACCENT, GREEN, AMBER, BLUE = (230, 75, 75), (110, 200, 140), (240, 190, 90), (110, 160, 240)

SANS = "/System/Library/Fonts/HelveticaNeue.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"


def font(size, bold=False, mono=False):
    if mono:
        return ImageFont.truetype(MONO, size, index=1 if bold else 0)
    return ImageFont.truetype(SANS, size, index=1 if bold else 0)


def run(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True).stdout


# ---- drawing helpers -----------------------------------------------------------------------------
def canvas(title: str, step: int, total: int):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 8], fill=ACCENT)
    d.text((96, 64), title, font=font(60, bold=True), fill=INK)
    d.text((W - 96, 80), f"{step}/{total}", font=font(30), fill=MUTED, anchor="ra")
    d.text((96, H - 64), "measles-sitrep  ·  Claude + CDC NNDSS", font=font(26), fill=MUTED, anchor="ls")
    return img, d


def bullets(d, items, x, y, size=40, width=46, gap=22, color=INK):
    f = font(size)
    for item in items:
        lines = textwrap.wrap(item, width)
        d.ellipse([x, y + size * 0.35, x + 14, y + size * 0.35 + 14], fill=ACCENT)
        for i, line in enumerate(lines):
            d.text((x + 40, y), line, font=f, fill=color)
            y += int(size * 1.3)
        y += gap
    return y


def terminal(d, x, y, w, h, lines, size=26, title="zsh"):
    d.rounded_rectangle([x, y, x + w, y + h], radius=18, fill=PANEL, outline=(40, 48, 66), width=2)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([x + 24 + i * 30, y + 20, x + 40 + i * 30, y + 36], fill=c)
    d.text((x + w / 2, y + 18), title, font=font(22), fill=MUTED, anchor="ma")
    f, fb = font(size, mono=True), font(size, bold=True, mono=True)
    ty = y + 64
    max_chars = int((w - 56) / (size * 0.602))
    for line in lines:
        if ty > y + h - size - 16:
            break
        color, fnt = INK, f
        if line.startswith("$ "):
            color, fnt = GREEN, fb
        elif re.search(r"\bpassed\b|PASS", line):
            color = GREEN
        elif line.lstrip().startswith(("#", "//")):
            color = MUTED
        d.text((x + 28, ty), line[:max_chars], font=fnt, fill=color)
        ty += int(size * 1.42)


def box(d, xy, label, sub=None, color=BLUE):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, radius=16, fill=(24, 32, 52), outline=color, width=3)
    cy = (y0 + y1) / 2 - (18 if sub else 0)
    d.text(((x0 + x1) / 2, cy), label, font=font(34, bold=True), fill=INK, anchor="mm")
    if sub:
        d.text(((x0 + x1) / 2, cy + 44), sub, font=font(25), fill=MUTED, anchor="mm")


def arrow(d, a, b, color=MUTED):
    d.line([a, b], fill=color, width=5)
    (x0, y0), (x1, y1) = a, b
    if abs(x1 - x0) > abs(y1 - y0):
        s = 1 if x1 > x0 else -1
        d.polygon([(x1, y1), (x1 - 18 * s, y1 - 11), (x1 - 18 * s, y1 + 11)], fill=color)
    else:
        s = 1 if y1 > y0 else -1
        d.polygon([(x1, y1), (x1 - 11, y1 - 18 * s), (x1 + 11, y1 - 18 * s)], fill=color)


def table(d, x, y, rows, widths, size=30, row_h=74):
    f, fb = font(size), font(size, bold=True)
    for r, row in enumerate(rows):
        if r == 0:
            d.rectangle([x, y, x + sum(widths), y + row_h], fill=(30, 40, 64))
        elif r % 2 == 0:
            d.rectangle([x, y, x + sum(widths), y + row_h], fill=(20, 27, 44))
        cx = x
        for c, cell in enumerate(row):
            lines = textwrap.wrap(cell, int(widths[c] / (size * 0.5)))
            ly = y + row_h / 2 - (len(lines) - 1) * size * 0.62
            for line in lines:
                d.text((cx + 20, ly), line, font=fb if r == 0 else f,
                       fill=INK if r == 0 or c == 0 else MUTED, anchor="lm")
                ly += size * 1.24
            cx += widths[c]
        y += row_h


# ---- slides ---------------------------------------------------------------------------------------
def latest_run() -> dict | None:
    runs = sorted((ROOT / "evals" / "results").glob("*.json"))
    return json.loads(runs[-1].read_text()) if runs else None


def slides() -> list[tuple[Image.Image, str]]:
    total = 10
    out = []
    counter = iter(range(2, total + 1))
    step = lambda: next(counter)  # noqa: E731

    # 1. Title
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 24, H], fill=ACCENT)
    d.text((160, 330), "measles-sitrep", font=font(120, bold=True), fill=INK)
    d.text((164, 490), "A Claude agent that drafts weekly measles situation reports", font=font(46), fill=INK)
    d.text((164, 556), "from CDC NNDSS data, with an eval set to check them.", font=font(46), fill=INK)
    d.text((164, 690), "2-minute walkthrough", font=font(34), fill=ACCENT)
    out.append((img, "This is measles sitrep: a Claude agent that turns CDC's weekly measles data into a "
                     "draft public-health situation report, with an eval set to check it."))

    # 2. Architecture
    img, d = canvas("How it works", step(), total)
    box(d, (110, 260, 520, 420), "data.cdc.gov", "NNDSS weekly table")
    box(d, (640, 260, 1050, 420), "Snapshots", "frozen JSON per week")
    box(d, (1170, 260, 1810, 420), "analysis.py", "every number computed here", GREEN)
    box(d, (1170, 560, 1810, 720), "Claude Opus 5.5", "7 tools · tool runner", ACCENT)
    box(d, (640, 560, 1050, 720), "sitrep.md", "fixed 6-section report")
    box(d, (110, 560, 520, 720), "Evals", "graders + LLM judge", AMBER)
    arrow(d, (520, 340), (636, 340)); arrow(d, (1050, 340), (1166, 340))
    arrow(d, (1490, 420), (1490, 556)); arrow(d, (1170, 640), (1054, 640)); arrow(d, (640, 640), (524, 640))
    d.text((W / 2, 860), "Claude decides what to look up and how to explain it. Code does all the arithmetic.",
           font=font(36), fill=MUTED, anchor="mm")
    out.append((img, "Measles rows from data dot C D C dot gov are frozen as snapshots. Python computes every "
                     "figure. Claude Opus 5.5 looks them up through seven tools and writes the report. "
                     "Then the evals grade the draft."))

    # 3. Facts (real output)
    facts = json.loads(run("uv run sitrep facts --snapshot data/snapshots/2026-w44.json"))
    n = facts["national"]
    ind, imp, tr = n["indigenous"], n["imported"], n["trend_indigenous"]
    top = facts["top_jurisdictions_this_week"]
    lines = ["$ uv run sitrep facts --snapshot data/snapshots/2026-w44.json", "",
             f"  MMWR week {n['mmwr_week']}, {n['mmwr_year']}  (week ending {n['week_ending']})", "",
             f"  Indigenous cases this week   {ind['cases_this_week']:>6,}",
             f"  Indigenous YTD               {ind['ytd']:>6,}   (last year {ind['ytd_same_week_last_year']:,}, "
             f"{ind['ytd_pct_change_vs_last_year']:+.1f}%)",
             f"  YTD added since last week    {ind['ytd_added_since_last_week']:>6,}   <- includes late reports",
             f"  Imported this week / YTD     {imp['cases_this_week']:>6,} / {imp['ytd']}",
             f"  4-week trend                 {tr['direction']}  ({tr['recent_4wk_cases']} vs {tr['prior_4wk_cases']})", "",
             "  Top this week:  " + ", ".join(f"{t['area']} {t['cases_this_week']}" for t in top[:4])]
    img, d = canvas("What the agent sees", step(), total)
    terminal(d, 96, 190, W - 192, 640, lines, size=30)
    d.text((96, 900), "Summarized from the real JSON output. No API key needed for this step.", font=font(32), fill=MUTED)
    out.append((img, f"For week {n['mmwr_week']} of {n['mmwr_year']}, the agent sees "
                     f"{ind['cases_this_week']} locally acquired cases this week and {ind['ytd']:,} this year, "
                     f"up about {round(ind['ytd_pct_change_vs_last_year'])} percent, with a "
                     f"{tr['direction']} trend. {top[0]['area']} and {top[1]['area']} lead this week."))

    # 4. A real draft (committed example from a live run)
    md = (ROOT / "docs/examples/sitrep-2026-w44.md").read_text()
    summary = re.search(r"## Summary\s*\n(.*?)\n## ", md, re.S).group(1).strip().replace("**", "")
    kf = re.search(r"## Key figures\s*\n(.*?)\n\n", md, re.S).group(1).strip().splitlines()
    rows = [[c.strip().replace("**", "") for c in r.strip("|").split("|")] for r in kf if not set(r) <= set("|-: ")]
    img, d = canvas("A real draft from Claude", step(), total)
    d.rounded_rectangle([96, 170, W - 96, 920], radius=18, fill=(246, 244, 239))
    paper, ink2 = (246, 244, 239), (30, 34, 44)
    title = md.splitlines()[0].lstrip("# ").strip()
    d.text((140, 215), title, font=font(36, bold=True), fill=ink2)
    d.text((140, 285), "Summary", font=font(30, bold=True), fill=ACCENT)
    y = 330
    for line in textwrap.wrap(summary, 105):
        d.text((140, y), line, font=font(27), fill=ink2); y += 38
    y += 30
    d.text((140, y), "Key figures", font=font(30, bold=True), fill=ACCENT); y += 50
    widths = [620, 420, 420]
    for r, row in enumerate(rows[:6]):
        x = 140
        if r == 0:
            d.rectangle([130, y - 6, 130 + sum(widths), y + 40], fill=(226, 222, 212))
        for c, cell in enumerate(row[:3]):
            d.text((x, y), cell[:44], font=font(26, bold=(r == 0)), fill=ink2); x += widths[c]
        y += 48
    d.text((96, 945), "docs/examples/sitrep-2026-w44.md  ·  Claude Opus 5.5, live run", font=font(26), fill=MUTED)
    out.append((img, "Here's a real draft Claude wrote for that week. The summary is short, the key "
                     "figures match the data exactly, and the full report explains that late reports "
                     "pushed the year-to-date total up by more than this week's count."))

    # 5. Agent code
    src = (ROOT / "src/measles_sitrep/agent.py").read_text().splitlines()
    start = next(i for i, l in enumerate(src) if "tool_runner(" in l)
    end = next(i for i in range(start, len(src)) if src[i].strip() == ")")
    code = ["# src/measles_sitrep/agent.py"] + [
        l[4:].split("  #")[0].rstrip() for l in src[start: end + 1] if not l.strip().startswith("#")]
    img, d = canvas("The agent", step(), total)
    terminal(d, 96, 190, 1100, 720, code, size=25, title="agent.py")
    bullets(d, ["SDK tool runner runs the loop", "Adaptive thinking, effort high",
                "Prompt caching on the system prompt and tools", "Server-side refusal fallbacks",
                "Prompt fixes the 6 sections and the data rules"], 1250, 230, size=34, width=30)
    out.append((img, "The agent uses the S D K tool runner with adaptive thinking, high effort, prompt caching, "
                     "and refusal fallbacks. The prompt fixes the sections and data rules. Claude never does "
                     "arithmetic itself."))

    # 6. Traps
    img, d = canvas("NNDSS traps, each with a test", step(), total)
    table(d, 96, 200, [
        ["Trap", "Handling"],
        ["\"New York\" excludes New York City", "Prompt rule plus a check on every eval case"],
        ["YTD rises more than the weekly count", "Tool reports YTD added; draft must explain late reports"],
        ["12 to 1,474 shown as \"+12,183%\"", "No % change when last year's count is under 20"],
        ["No hospitalizations or deaths in the data", "Agent declines; grader flags invented figures"],
        ["Week not published yet", "Tool returns an error; agent writes a short note"],
    ], [760, 968], size=32, row_h=110)
    out.append((img, "The data has traps. New York excludes New York City. Year-to-date totals include late "
                     "reports. Tiny bases give absurd percent changes. And there's no hospitalization or death "
                     "data. Each trap has a rule and an eval case."))

    # 7. Eval cases (real ids from cases.yaml)
    import yaml
    cases = yaml.safe_load((ROOT / "evals/cases.yaml").read_text())["cases"]
    lines = ["# case id                    snapshot         focus", ""] + [
        f"  {c['id']:<28} {c['snapshot']:<16} {('focus: ' + c['focus']) if c.get('focus') else ''}"
        for c in cases]
    img, d = canvas(f"Eval set: {len(cases)} cases, 4 frozen snapshots", step(), total)
    terminal(d, 96, 190, W - 192, 740, lines, size=30, title="evals/cases.yaml")
    out.append((img, f"{len(cases)} eval cases span four snapshots, from the early 2025 Texas outbreak to this "
                     "month, including plain language, single states, an unpublished week, and missing data."))

    # 8. Graders
    img, d = canvas("Grading", step(), total)
    d.text((96, 200), "Deterministic checks (every case)", font=font(40, bold=True), fill=AMBER)
    bullets(d, ["Required sections and a provisional-data caveat",
                "Exact numbers and % changes, in any common format",
                "Trend word inside the Trend section",
                "Each state's numbers match its real data",
                "No invented hospitalization, death, or vaccine figures",
                "Expected tools were called"], 96, 280, size=34, width=48)
    d.text((1120, 200), "Optional LLM judge", font=font(40, bold=True), fill=AMBER)
    bullets(d, ["Sees the exact tool outputs", "Scores faithfulness, audience fit, and actionability",
                "Returns structured JSON"], 1120, 280, size=34, width=32)
    out.append((img, "Graders check the sections, exact numbers, and the trend. Each state's numbers must match "
                     "its real data, with no invented outcomes. An optional Claude judge scores faithfulness "
                     "against the tool outputs."))

    # 9. Live eval results
    res = latest_run()
    img, d = canvas("Live eval results", step(), total)
    rows = [["Case", "Result", "Checks", "Judge (F / A / R)"]]
    fs = []
    for r in res["results"]:
        ok = sum(c["passed"] for c in r["checks"])
        j = r.get("judge") or {}
        if "faithfulness" in j:
            fs.append(j["faithfulness"])
        rows.append([r["id"], "PASS" if r["passed"] else "FAIL", f"{ok}/{len(r['checks'])}",
                     f"{j['faithfulness']} / {j['audience_fit']} / {j['actionability']}" if "faithfulness" in j else "-"])
    table(d, 96, 170, rows, [760, 260, 260, 448], size=28, row_h=66)
    favg = sum(fs) / len(fs) if fs else 0
    d.text((96, 925), f"{res['cases_passed']}/{res['cases']} cases · {res['checks_passed']}/{res['checks']} checks · "
           f"judge: F faithfulness, A audience fit, R actionability (1-5)", font=font(28), fill=MUTED)
    out.append((img, f"On the live run, {res['cases_passed']} of {res['cases']} cases passed every check, "
                     f"{res['checks_passed']} of {res['checks']} checks in all. The judge scored {len(fs)} drafts, "
                     f"averaging {favg:.1f} out of 5 for faithfulness."))

    # 10. Run it
    img, d = canvas("Run it", step(), total)
    terminal(d, 96, 190, W - 192, 520, [
        "$ uv sync",
        "$ ant auth login                              # or export ANTHROPIC_API_KEY",
        "$ uv run sitrep draft                         # latest week from data.cdc.gov",
        "$ uv run sitrep draft --focus Pennsylvania --audience \"state epidemiologists\"",
        "$ uv run python evals/run_evals.py --judge    # scorecard",
    ], size=32)
    d.text((96, 790), "Drafts are for an epidemiologist to review before release.", font=font(38), fill=INK)
    d.text((96, 850), "Data: CDC NNDSS Weekly Data (data.cdc.gov/d/x9gk-5huc), provisional counts.",
           font=font(30), fill=MUTED)
    out.append((img, "To run it: u v sync, sign in with ant auth login, then run sitrep draft, or run evals for "
                     "the scorecard. Offline tests need no key. An epidemiologist should review every draft."))
    return out


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    segments = []
    for i, (img, narration) in enumerate(slides(), 1):
        png, aiff, seg = BUILD / f"s{i:02d}.png", BUILD / f"s{i:02d}.aiff", BUILD / f"s{i:02d}.mp4"
        img.save(png)
        subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), narration], check=True)
        secs = float(re.search(r"estimated duration: ([\d.]+)",
                               subprocess.run(["afinfo", str(aiff)], capture_output=True, text=True).stdout).group(1))
        # 0.5 s of silence before and 0.7 s after each line of narration.
        subprocess.run([
            ffmpeg, "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(png),
            "-i", str(aiff), "-filter_complex",
            "[1:a]adelay=500|500,apad=pad_dur=0.7,aresample=48000[a]",
            "-map", "0:v", "-map", "[a]", "-t", f"{secs + 1.2:.2f}", "-c:v", "libx264", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(seg),
        ], check=True)
        segments.append(seg)
    listfile = BUILD / "segments.txt"
    listfile.write_text("".join(f"file '{s}'\n" for s in segments))
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c", "copy", "-movflags", "+faststart", str(OUT)], check=True)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
