"""The sitrep agent: Claude, NNDSS tools, and the SDK's tool runner."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import anthropic

from .nndss import Snapshot
from .prompts import SYSTEM_PROMPT, user_request
from .tools import make_tools

DEFAULT_MODEL = os.environ.get("SITREP_MODEL", "claude-opus-5-5")
DEFAULT_EFFORT = os.environ.get("SITREP_EFFORT", "high")
MAX_TOOL_ITERATIONS = 20


@dataclass
class SitrepResult:
    markdown: str
    model: str
    stop_reason: str | None
    tool_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    request: str = ""


class SitrepError(RuntimeError):
    pass


def draft_sitrep(
    snap: Snapshot,
    week: int | None = None,
    audience: str = "state and local public health officials",
    focus: str | None = None,
    extra: str | None = None,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    client: anthropic.Anthropic | None = None,
) -> SitrepResult:
    client = client or anthropic.Anthropic()
    log: list[dict] = []
    request = user_request(week, snap.year if week else None, audience, focus, extra)

    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=make_tools(snap, log),
        messages=[{"role": "user", "content": request}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        cache_control={"type": "ephemeral"},  # system prompt and tools repeat each turn
        max_iterations=MAX_TOOL_ITERATIONS,
        # If a safety classifier declines the request, the API retries it on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    result = SitrepResult(markdown="", model=model, stop_reason=None, request=request)
    last = None
    for message in runner:
        last = message
        u = message.usage
        result.input_tokens += u.input_tokens or 0
        result.output_tokens += u.output_tokens or 0
        result.cache_read_tokens += u.cache_read_input_tokens or 0

    if last is None:
        raise SitrepError("The model returned no messages")
    result.stop_reason = last.stop_reason
    result.model = last.model
    result.tool_calls = log
    if last.stop_reason == "refusal":
        raise SitrepError(f"Request declined: {getattr(last, 'stop_details', None)}")
    if last.stop_reason == "max_tokens":
        raise SitrepError("Draft was cut off at max_tokens")
    if last.stop_reason == "tool_use":
        raise SitrepError(f"Stopped after {MAX_TOOL_ITERATIONS} tool iterations without a draft")
    result.markdown = "\n".join(b.text for b in last.content if b.type == "text").strip()
    return result
