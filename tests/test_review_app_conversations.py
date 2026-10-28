"""The review app groups per-turn Langfuse traces into conversations.

Cartwheel writes one trace per user turn. A reviewer needs every turn of a
session in time order, with each tool call placed between the user message
and the reply, and none of the empty wrapper spans.
"""

from __future__ import annotations

from typing import Any

from analysis.review_app.conversations import build_conversations, tool_summary


def _msg(role: str, text: str) -> list[dict[str, Any]]:
    return [{"role": role, "parts": [{"type": "text", "content": text}]}]


def _obs(kind: str, name: str, start: str, inp: Any = None, out: Any = None) -> dict:
    return {"type": kind, "name": name, "start_time": start, "input": inp, "output": out}


def _trace(trace_id: str, session: str, scenario: str, ts: str, **kw: Any) -> dict:
    return {
        "trace_id": trace_id,
        "timestamp": ts,
        "meta": {"scenario_id": scenario, "session_id": session, "role": "shopper"},
        "metadata": {"cartwheel.user_id": "197"},
        "input": _msg("user", kw.get("user", "hi")),
        "output": _msg("assistant", kw.get("reply", "hello")),
        "observations": kw.get("observations", []),
    }


SCENARIOS = {
    "support-0082": {
        "tuple": {"intent": "return_eligibility", "order_id": 1649},
        "expected": {"outcome": "not_eligible_cite_cw-returns", "reason": "45 days"},
    }
}


def test_turns_of_one_session_form_one_conversation_in_time_order() -> None:
    traces = [
        _trace("t2", "s1", "support-0082", "2026-10-25T10:00:05Z", user="second"),
        _trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z", user="first"),
    ]
    [conv] = build_conversations(traces, SCENARIOS)
    assert [t["user_text"] for t in conv["turns"]] == ["first", "second"]


def test_turn_records_its_trace_id_and_index() -> None:
    traces = [_trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z")]
    [conv] = build_conversations(traces, SCENARIOS)
    assert (conv["turns"][0]["trace_id"], conv["turns"][0]["index"]) == ("t1", 1)


def test_traces_outside_the_prefix_are_dropped() -> None:
    traces = [
        _trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z"),
        _trace("p1", "s9", "pilot-001", "2026-10-25T09:00:00Z"),
    ]
    assert [c["scenario_id"] for c in build_conversations(traces, SCENARIOS)] == [
        "support-0082"
    ]


def test_only_tool_observations_become_steps_in_start_order() -> None:
    observations = [
        _obs("AGENT", "cartwheel-support.agent", "2026-10-25T10:00:00Z"),
        _obs("TOOL", "search_help_center", "2026-10-25T10:00:03Z", {"query": "x"}, {"ok": True, "results": []}),
        _obs("GENERATION", "openai.response", "2026-10-25T10:00:01Z"),
        _obs("TOOL", "find_order", "2026-10-25T10:00:02Z", {"query": "y"}, {"ok": True, "orders": []}),
    ]
    traces = [_trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z", observations=observations)]
    [conv] = build_conversations(traces, SCENARIOS)
    assert [s["name"] for s in conv["turns"][0]["steps"]] == ["find_order", "search_help_center"]


def test_model_calls_are_counted_but_not_shown_as_steps() -> None:
    observations = [_obs("GENERATION", "openai.response", "2026-10-25T10:00:01Z")] * 3
    traces = [_trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z", observations=observations)]
    [conv] = build_conversations(traces, SCENARIOS)
    assert conv["turns"][0]["model_calls"] == 3


def test_failed_tool_step_is_marked_not_ok() -> None:
    out = {"ok": False, "error": "permission_denied", "reason": "may not view order #483"}
    observations = [_obs("TOOL", "get_order", "2026-10-25T10:00:02Z", {"order_id": 483}, out)]
    traces = [_trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z", observations=observations)]
    [conv] = build_conversations(traces, SCENARIOS)
    assert conv["turns"][0]["steps"][0]["ok"] is False


def test_reference_comes_from_the_matching_scenario() -> None:
    traces = [_trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z")]
    [conv] = build_conversations(traces, SCENARIOS)
    assert conv["reference"]["expected"]["reason"] == "45 days"


def test_missing_scenario_gives_no_reference() -> None:
    traces = [_trace("t1", "s1", "support-0999", "2026-10-25T10:00:00Z")]
    [conv] = build_conversations(traces, SCENARIOS)
    assert conv["reference"] is None


def test_conversation_carries_role_and_user_id() -> None:
    traces = [_trace("t1", "s1", "support-0082", "2026-10-25T10:00:00Z")]
    [conv] = build_conversations(traces, SCENARIOS)
    assert (conv["role"], conv["user_id"]) == ("shopper", "197")


def test_tool_summary_lists_key_order_fields() -> None:
    out = {"ok": True, "orders": [{"order_id": 1649, "delivered_at": "2026-05-17", "refund_eligible": False, "product_id": 647}]}
    assert tool_summary(out) == "order 1649 · delivered_at 2026-05-17 · refund_eligible false"


def test_tool_summary_shows_error_and_reason() -> None:
    out = {"ok": False, "error": "permission_denied", "reason": "may not view order #483"}
    assert tool_summary(out) == "permission_denied: may not view order #483"


def test_tool_summary_shows_write_status() -> None:
    out = {"ok": True, "status": "queued_for_approval", "refund_id": 592, "amount_usd": 298.75}
    assert tool_summary(out) == "status queued_for_approval · refund_id 592 · amount_usd 298.75"


def test_tool_summary_passes_unparsed_text_through() -> None:
    assert tool_summary("not json") == "not json"
