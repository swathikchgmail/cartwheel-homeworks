"""Unit tests for the HW5 input preparation in analysis/run_judges.py."""

from analysis import run_judges as rj


def _turn(tid, ts, user, reply, tools=(), session="s1"):
    return {
        "id": tid, "timestamp": ts,
        "meta": {"session_id": session, "scenario_id": "support-9999", "role": "shopper"},
        "input": [{"role": "user", "parts": [{"type": "text", "content": user}]}],
        "output": [{"role": "assistant", "parts": [{"type": "text", "content": reply}]}],
        "observations": [
            {"type": "TOOL", "name": name, "input": args, "output": out, "start_time": start}
            for name, args, out, start in tools
        ],
    }


def _label(tid, label):
    return {tid: {"trace_id": tid, "label": label, "ts": "2026-11-06T00:00:00+00:00", "evidence": "e"}}


T1 = _turn("a", "2026-01-01T00:00:01", "refund please", "Done, refund issued.",
           tools=[("issue_refund", {"id": 1}, {"note": "5 to 10 business days"}, "2026-01-01T00:00:00.2"),
                  ("find_order", {"q": "x"}, {"ok": True}, "2026-01-01T00:00:00.1")])
T2 = _turn("b", "2026-01-01T00:00:02", "how long?", "Returns are allowed for 30 days (cw-returns).")
T3 = _turn("c", "2026-01-01T00:00:03", "thanks", "You're welcome.")


def test_live_labels_drops_superseded_rows():
    rows = [{"trace_id": "a", "label": 1, "superseded_by": "a#1"}, {"trace_id": "a", "label": 0}]
    assert rj.live_labels(rows)["a"]["label"] == 0


def test_group_turns_orders_turns_by_timestamp():
    groups = rj.group_turns([T3, T1, T2])
    assert [t["id"] for t in groups["s1"]] == ["a", "b", "c"]


def test_difficulty_scores_citation_and_number():
    assert rj.difficulty("30 days (cw-returns)") == 3


def test_difficulty_is_zero_without_policy_signal():
    assert rj.difficulty("You're welcome.") == 0


def test_choose_turn_picks_first_fail_turn():
    labels = {**_label("a", 0), **_label("b", 1), **_label("c", 1)}
    assert rj.choose_turn([T1, T2, T3], labels) == 1


def test_choose_turn_picks_hardest_pass_turn():
    labels = {**_label("a", 0), **_label("b", 0), **_label("c", 0)}
    assert rj.choose_turn([T1, T2, T3], labels) == 1


def test_choose_turn_breaks_ties_with_last_labeled_turn():
    labels = {**_label("a", 0), **_label("c", 0)}
    assert rj.choose_turn([T1, T2, T3], labels) == 2


def test_choose_turn_returns_none_for_unlabeled_conversation():
    assert rj.choose_turn([T1, T2], {}) is None


def test_turn_messages_orders_tools_by_start_time():
    names = [m["name"] for m in rj.turn_messages(T1) if m["role"] == "tool"]
    assert names == ["find_order", "issue_refund"]


def test_tool_line_shows_name_arguments_and_result():
    tool = [m for m in rj.turn_messages(T1) if m.get("name") == "issue_refund"][0]
    assert tool["content"] == 'issue_refund {"id": 1} -> {"note": "5 to 10 business days"}'


def test_judge_text_includes_tool_results():
    from analysis.helpers.normalization import normalize_trace
    text = normalize_trace(rj.build_record([T1, T2], 1))["text"]
    assert 'tool: issue_refund {"id": 1} -> {"note": "5 to 10 business days"}' in text


def test_build_record_ends_with_evaluated_reply():
    record = rj.build_record([T1, T2, T3], 1)
    assert record["trace"][-1] == {"role": "assistant", "content": "Returns are allowed for 30 days (cw-returns)."}


def test_build_record_includes_earlier_turns():
    record = rj.build_record([T1, T2, T3], 1)
    assert record["trace"][0] == {"role": "user", "content": "refund please"}


def test_build_record_uses_evaluated_turn_trace_id():
    assert rj.build_record([T1, T2, T3], 1)["trace_id"] == "b"


def test_build_record_leaks_no_metadata_or_labels():
    text = str(rj.build_record([T1, T2], 1))
    assert not any(leak in text for leak in ("support-9999", "'s1'", "shopper", "evidence", "label"))


def test_hw5_label_flips_fail_to_zero():
    assert rj.hw5_label(_label("a", 1)["a"])["label"] == 0


def test_hw5_label_flips_pass_to_one():
    assert rj.hw5_label(_label("a", 0)["a"])["label"] == 1
