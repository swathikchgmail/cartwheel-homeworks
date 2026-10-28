"""The review store owns the HW4 state files under analysis/state/.

Annotations keep their edit history, AI suggestions stay separate until a
human accepts or rejects them, and label files stay append-only so the
existing analysis helpers read the same live label per trace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analysis.review_app.store import ReviewStore

ANCHOR = {"trace_id": "t1", "session_id": "s1", "scenario_id": "support-0082", "turn": 1}


@pytest.fixture
def store(tmp_path: Path) -> ReviewStore:
    return ReviewStore(tmp_path)


def test_added_open_code_is_saved_as_a_human_annotation(store: ReviewStore) -> None:
    store.add_annotation(**ANCHOR, step="reply", note="offers escalation past window")
    [saved] = ReviewStore(store.root).annotations()
    assert (saved["author"], saved["note"], saved["step"]) == ("human", "offers escalation past window", "reply")


def test_annotations_file_keeps_the_helper_shape(store: ReviewStore) -> None:
    store.add_annotation(**ANCHOR, step="user", note="x")
    assert list(store.read("annotations.json")) == ["annotations"]


def test_open_code_without_a_note_is_rejected(store: ReviewStore) -> None:
    with pytest.raises(ValueError, match="note"):
        store.add_annotation(**ANCHOR, step="reply", note="  ")


def test_no_failure_gets_the_standard_note(store: ReviewStore) -> None:
    saved = store.add_annotation(**ANCHOR, step="reply", note="", kind="no_failure")
    assert saved["note"] == "no failure observed"


def test_unknown_step_is_rejected(store: ReviewStore) -> None:
    with pytest.raises(ValueError, match="step"):
        store.add_annotation(**ANCHOR, step="span:3", note="x")


def test_tool_step_anchor_is_accepted(store: ReviewStore) -> None:
    saved = store.add_annotation(**ANCHOR, step="tool:2", note="wrong order looked up")
    assert saved["step"] == "tool:2"


def test_editing_a_note_keeps_the_original_in_history(store: ReviewStore) -> None:
    saved = store.add_annotation(**ANCHOR, step="reply", note="first wording")
    edited = store.update_annotation(saved["id"], "second wording")
    assert [h["note"] for h in edited["history"]] == ["first wording"]


def test_accepting_a_suggestion_creates_a_linked_human_annotation(store: ReviewStore) -> None:
    sug = store.add_suggestion(**ANCHOR, step="reply", note="hedges after refusal", source="search:x")
    ann = store.accept_suggestion(sug["id"])
    assert (ann["author"], ann["accepted_from"]) == ("human", sug["id"])


def test_accepted_suggestion_is_marked_accepted(store: ReviewStore) -> None:
    sug = store.add_suggestion(**ANCHOR, step="reply", note="n", source="search:x")
    store.accept_suggestion(sug["id"])
    assert store.suggestions()[0]["status"] == "accepted"


def test_rejecting_a_suggestion_requires_a_reason(store: ReviewStore) -> None:
    sug = store.add_suggestion(**ANCHOR, step="reply", note="n", source="search:x")
    with pytest.raises(ValueError, match="reason"):
        store.reject_suggestion(sug["id"], "")


def test_rejected_suggestion_keeps_its_reason(store: ReviewStore) -> None:
    sug = store.add_suggestion(**ANCHOR, step="reply", note="n", source="search:x")
    store.reject_suggestion(sug["id"], "tool confirmed success")
    assert store.suggestions()[0]["decision_reason"] == "tool confirmed success"


def test_a_decided_suggestion_cannot_be_decided_again(store: ReviewStore) -> None:
    sug = store.add_suggestion(**ANCHOR, step="reply", note="n", source="search:x")
    store.reject_suggestion(sug["id"], "no")
    with pytest.raises(ValueError, match="already"):
        store.accept_suggestion(sug["id"])


def test_mode_names_must_be_snake_case(store: ReviewStore) -> None:
    with pytest.raises(ValueError, match="snake_case"):
        store.save_patterns([{"name": "Unconfirmed Write", "definition": "d"}])


def test_duplicate_mode_names_are_rejected(store: ReviewStore) -> None:
    modes = [{"name": "a_mode", "definition": "d"}, {"name": "a_mode", "definition": "e"}]
    with pytest.raises(ValueError, match="duplicate"):
        store.save_patterns(modes)


def test_saved_patterns_round_trip(store: ReviewStore) -> None:
    store.save_patterns([{"name": "unconfirmed_write", "definition": "d"}])
    assert store.patterns()["modes"][0]["name"] == "unconfirmed_write"


def test_manifest_rejects_a_session_in_two_batches(store: ReviewStore) -> None:
    batches = [
        {"id": "b1", "items": [{"session_id": "s1", "trace_ids": ["t1"]}]},
        {"id": "b2", "items": [{"session_id": "s1", "trace_ids": ["t1"]}]},
    ]
    with pytest.raises(ValueError, match="s1"):
        store.save_manifest({"batches": batches})


def test_relabeling_supersedes_the_earlier_label(store: ReviewStore) -> None:
    store.set_label("unconfirmed_write", "t1", 1, evidence="queued", langfuse_synced=True)
    store.set_label("unconfirmed_write", "t1", 0, evidence="tool said refunded", langfuse_synced=True)
    assert store.live_labels("unconfirmed_write")["t1"]["label"] == 0


def test_label_file_keeps_the_superseded_row(store: ReviewStore) -> None:
    store.set_label("unconfirmed_write", "t1", 1, evidence="a", langfuse_synced=True)
    store.set_label("unconfirmed_write", "t1", 0, evidence="b", langfuse_synced=True)
    rows = store.label_rows("unconfirmed_write")
    assert rows[0]["superseded_by"] == rows[1]["label_id"]


def test_labels_are_readable_by_the_analysis_helpers(
    store: ReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analysis.helpers import tools

    monkeypatch.setenv("CARTWHEEL_ANALYSIS_STATE", str(store.root))
    store.set_label("unconfirmed_write", "t1", 1, evidence="a", langfuse_synced=True)
    store.set_label("unconfirmed_write", "t1", 0, evidence="b", langfuse_synced=True)
    assert [r["label"] for r in tools._load_labels("unconfirmed_write")] == [0]


def test_label_must_be_zero_or_one(store: ReviewStore) -> None:
    with pytest.raises(ValueError, match="0 or 1"):
        store.set_label("unconfirmed_write", "t1", 2, evidence="", langfuse_synced=True)
