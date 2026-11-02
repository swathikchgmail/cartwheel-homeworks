"""Part E draft labels: human priors first, model drafts with a stubbed classifier."""

from __future__ import annotations

import json

import pytest

from analysis.review_app.draft_labels import (
    build_messages,
    cost_usd,
    draft_pairs,
    human_priors,
    parse_reply,
    reference_facts,
)

MODES = [
    {"name": "mode_a", "definition": "Fail if A.", "boundary": "Not B.", "created_from": ["ann-1"]},
    {"name": "mode_b", "definition": "Fail if B.", "boundary": "Not A.", "created_from": []},
]


def _conv(sid: str, turns: int) -> dict:
    return {
        "session_id": sid, "scenario_id": f"support-{sid}",
        "turns": [
            {"index": i, "trace_id": f"{sid}-t{i}", "user_text": f"q{i}", "reply_text": f"r{i}",
             "steps": [{"name": "get_order", "input": {"id": 1}, "output": {"ok": True}}]}
            for i in range(1, turns + 1)
        ],
    }


def _note(nid: str, sid: str, turn: int, kind: str = "open_code", **extra) -> dict:
    return {"id": nid, "session_id": sid, "trace_id": f"{sid}-t{turn}", "turn": turn, "kind": kind, **extra}


def _reply(a: bool, b: bool) -> str:
    return json.dumps({"mode_a": {"present": a, "reason": "ra"}, "mode_b": {"present": b, "reason": "rb"}})


# -- human priors -------------------------------------------------------------


def test_no_failure_note_marks_every_mode_absent_on_every_turn():
    priors = human_priors([_note("ann-9", "s", 1, kind="no_failure")], MODES, {"s": _conv("s", 2)})
    assert {k: v["label"] for k, v in priors.items()} == {
        ("s-t1", "mode_a"): 0, ("s-t1", "mode_b"): 0, ("s-t2", "mode_a"): 0, ("s-t2", "mode_b"): 0,
    }


def test_linked_open_code_marks_its_mode_present_on_its_trace():
    priors = human_priors([_note("ann-1", "s", 2)], MODES, {"s": _conv("s", 2)})
    assert priors[("s-t2", "mode_a")]["label"] == 1


def test_linked_open_code_leaves_other_modes_on_its_trace_open():
    priors = human_priors([_note("ann-1", "s", 2)], MODES, {"s": _conv("s", 2)})
    assert ("s-t2", "mode_b") not in priors


def test_turns_before_the_first_failure_are_absent_for_every_mode():
    priors = human_priors([_note("ann-1", "s", 2)], MODES, {"s": _conv("s", 3)})
    assert [priors[("s-t1", n)]["label"] for n in ("mode_a", "mode_b")] == [0, 0]


def test_turns_after_the_first_failure_are_left_open():
    priors = human_priors([_note("ann-1", "s", 2)], MODES, {"s": _conv("s", 3)})
    assert not any(k[0] == "s-t3" for k in priors)


def test_retired_notes_give_no_prior():
    priors = human_priors([_note("ann-1", "s", 1, retired_by="ann-2")], MODES, {"s": _conv("s", 1)})
    assert priors == {}


def test_unlinked_open_code_gives_no_prior():
    priors = human_priors([_note("ann-7", "s", 1)], MODES, {"s": _conv("s", 1)})
    assert priors == {}


# -- prompt ---------------------------------------------------------------------


def test_build_messages_includes_only_turns_up_to_the_judged_one():
    user = build_messages(_conv("s", 3), 2, MODES)[1]["content"]
    assert ("r2" in user, "r3" in user) == (True, False)


def test_build_messages_lists_every_mode_with_its_boundary():
    system = build_messages(_conv("s", 1), 1, MODES)[0]["content"]
    assert "mode_b: Fail if B.\n  Boundary: Not A." in system


def test_build_messages_puts_the_reference_facts_in_the_system_prompt():
    system = build_messages(_conv("s", 1), 1, MODES, reference="return_window_days: 30")[0]["content"]
    assert "return_window_days: 30" in system


def test_reference_facts_lists_each_store_window():
    text = reference_facts("return_window_days: 30", {"Northwind Books": 45})
    assert "Northwind Books: 45-day return window" in text


def test_build_messages_wraps_the_conversation_as_data():
    user = build_messages(_conv("s", 1), 1, MODES)[1]["content"]
    assert user.startswith("<conversation>") and "</conversation>" in user


# -- parsing -------------------------------------------------------------------


def test_parse_reply_reads_a_label_and_reason_per_mode():
    assert parse_reply(_reply(True, False), ["mode_a", "mode_b"]) == {
        "mode_a": {"label": 1, "reason": "ra"}, "mode_b": {"label": 0, "reason": "rb"},
    }


def test_parse_reply_tolerates_text_around_the_json():
    assert parse_reply("Here:\n" + _reply(False, False) + "\nDone", ["mode_a", "mode_b"])["mode_a"]["label"] == 0


def test_parse_reply_rejects_a_missing_mode():
    with pytest.raises(ValueError, match="mode_b"):
        parse_reply(json.dumps({"mode_a": {"present": True}}), ["mode_a", "mode_b"])


def test_parse_reply_rejects_a_non_boolean_label():
    with pytest.raises(ValueError, match="mode_a"):
        parse_reply(json.dumps({"mode_a": {"present": "yes"}, "mode_b": {"present": False}}), ["mode_a", "mode_b"])


def test_parse_reply_rejects_text_without_json():
    with pytest.raises(ValueError, match="no JSON"):
        parse_reply("I cannot decide", ["mode_a"])


# -- drafting -------------------------------------------------------------------


def _stub(reply: str):
    return lambda messages: (reply, {"input": 100, "output": 10})


def test_draft_pairs_prefers_the_human_prior_over_the_model():
    priors = {("s-t1", "mode_a"): {"label": 1, "why": "open code ann-1"}}
    rows, _ = draft_pairs(_conv("s", 1), 1, MODES, priors, _stub(_reply(False, False)))
    assert (rows[0]["proposed"], rows[0]["source"]) == (1, "human_prior")


def test_draft_pairs_flags_a_model_disagreement_with_a_prior():
    priors = {("s-t1", "mode_a"): {"label": 1, "why": "open code ann-1"}}
    rows, _ = draft_pairs(_conv("s", 1), 1, MODES, priors, _stub(_reply(False, False)))
    assert rows[0]["disagrees"] is True


def test_draft_pairs_uses_the_model_where_no_prior_exists():
    rows, _ = draft_pairs(_conv("s", 1), 1, MODES, {}, _stub(_reply(False, True)))
    assert [(r["mode"], r["proposed"], r["source"]) for r in rows] == [("mode_a", 0, "model"), ("mode_b", 1, "model")]


def test_draft_pairs_returns_the_call_usage():
    _, usage = draft_pairs(_conv("s", 1), 1, MODES, {}, _stub(_reply(False, False)))
    assert usage == {"input": 100, "output": 10}


def _sequence(*replies: str):
    queue = list(replies)
    return lambda messages: (queue.pop(0), {"input": 100, "output": 10})


def test_draft_pairs_asks_again_after_a_broken_reply():
    rows, _ = draft_pairs(_conv("s", 1), 1, MODES, {}, _sequence('{"mode_a" {', _reply(True, False)))
    assert rows[0]["model_label"] == 1


def test_draft_pairs_counts_usage_for_every_attempt():
    _, usage = draft_pairs(_conv("s", 1), 1, MODES, {}, _sequence('{"mode_a" {', _reply(True, False)))
    assert usage == {"input": 200, "output": 20}


def test_draft_pairs_gives_up_after_three_broken_replies():
    with pytest.raises(ValueError):
        draft_pairs(_conv("s", 1), 1, MODES, {}, _sequence("{bad}", "{bad}", "{bad}"))


def test_cost_usd_uses_the_model_price():
    assert cost_usd("claude-haiku-4-5", {"input": 1_000_000, "output": 200_000}) == pytest.approx(2.0)
