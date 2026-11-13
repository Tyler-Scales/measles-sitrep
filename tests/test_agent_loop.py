"""Run the agent loop against a mock Messages API, with no network or API key needed.

The mock serves two scripted turns: Claude calls two tools, then returns text. The test
checks the request settings we send and that real NNDSS numbers reach the model in tool
results.
"""

import json
from pathlib import Path

import anthropic
import httpx2

from measles_sitrep.agent import draft_sitrep
from measles_sitrep.nndss import Snapshot

SNAP = Snapshot.load(Path(__file__).resolve().parent.parent / "data" / "snapshots" / "2026-w44.json")


def _msg(content, stop_reason):
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
    }


def test_tool_loop_end_to_end():
    requests = []
    turns = [
        _msg([
            {"type": "tool_use", "id": "tu_1", "name": "get_reporting_period", "input": {}},
            {"type": "tool_use", "id": "tu_2", "name": "get_national_summary", "input": {}},
        ], "tool_use"),
        _msg([{"type": "text", "text": "SCRIPTED TEST DRAFT"}], "end_turn"),
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=turns[len(requests) - 1])

    client = anthropic.Anthropic(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    res = draft_sitrep(SNAP, client=client)

    assert res.markdown == "SCRIPTED TEST DRAFT"
    assert [c["tool"] for c in res.tool_calls] == ["get_reporting_period", "get_national_summary"]
    assert res.input_tokens == 200 and res.cache_read_tokens == 100

    first = requests[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"]["effort"] == "high"
    assert first["fallbacks"] == "default"
    assert {t["name"] for t in first["tools"]} >= {"get_national_summary", "get_area_summary"}
    assert "latest published week" in first["messages"][0]["content"]

    # Second request carries the tool results, built from the real snapshot.
    results = [b for b in requests[1]["messages"][-1]["content"] if b["type"] == "tool_result"]
    assert len(results) == 2
    payload = json.dumps(results)
    assert "4991" in payload and "2026-11-07" in payload
