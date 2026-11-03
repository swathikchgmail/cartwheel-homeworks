"""Request validation and operations behind the review app's HTTP routes.

The HTTP layer only parses JSON and maps exceptions to status codes:
``ValueError`` -> 400, ``KeyError`` -> 404. Every body is checked against an
allowlist of fields, and every anchor must match a loaded trace, so a stale
or hand-edited request cannot attach a note or label to the wrong turn.
"""

from __future__ import annotations

from typing import Any

from analysis.review_app.label_sync import LabelSink, save_label
from analysis.review_app.store import ReviewStore

_ANNOTATION_FIELDS = {"trace_id", "session_id", "scenario_id", "turn", "step", "note", "kind", "quote", "batch"}
_MODE_FIELDS = {
    "name", "definition", "boundary", "nearest_mode", "requirement_source",
    "evaluator_type", "created_from", "example_trace_ids",
    "close_negative_trace_ids", "status", "history", "notes",
}
_MODE_STATUSES = (None, "candidate", "final", "rejected")
_EVALUATOR_TYPES = (None, "code", "judge")


def _fields(body: Any, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    extra = set(body) - allowed
    if extra:
        raise ValueError(f"unexpected fields: {sorted(extra)}")
    missing = required - set(body)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    return body


class ReviewApp:
    """The loaded conversations plus the store and label sink they write to."""

    def __init__(self, conversations: list[dict[str, Any]], store: ReviewStore, sink: LabelSink | None) -> None:
        self.conversations = conversations
        self.store = store
        self.sink = sink
        self._turns = {
            turn["trace_id"]: (conv, turn) for conv in conversations for turn in conv["turns"]
        }

    # -- reads ---------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        patterns = self.store.patterns()
        modes = [m["name"] for m in patterns.get("modes", [])]
        return {
            "annotations": self.store.annotations(),
            "suggestions": self.store.suggestions(),
            "patterns": patterns,
            "manifest": self.store.manifest(),
            "labels": {m: list(self.store.live_labels(m).values()) for m in modes},
        }

    # -- writes --------------------------------------------------------------

    def create_annotation(self, body: Any) -> dict[str, Any]:
        body = _fields(body, _ANNOTATION_FIELDS, {"trace_id", "session_id", "scenario_id", "turn", "step"})
        self._check_anchor(body)
        return self.store.add_annotation(**{"note": "", **body})

    def update_annotation(self, annotation_id: str, body: Any) -> dict[str, Any]:
        body = _fields(body, {"note"}, {"note"})
        return self.store.update_annotation(annotation_id, body["note"])

    def accept_suggestion(self, suggestion_id: str, body: Any) -> dict[str, Any]:
        body = _fields(body or {}, {"batch"}, set())
        return self.store.accept_suggestion(suggestion_id, batch=body.get("batch"))

    def reject_suggestion(self, suggestion_id: str, body: Any) -> dict[str, Any]:
        body = _fields(body, {"reason"}, {"reason"})
        return self.store.reject_suggestion(suggestion_id, body["reason"])

    def save_patterns(self, body: Any) -> dict[str, Any]:
        body = _fields(body, {"modes"}, {"modes"})
        if not isinstance(body["modes"], list):
            raise ValueError("modes must be a list")
        known = {a["id"] for a in self.store.annotations()}
        for mode in body["modes"]:
            self._check_mode(_fields(mode, _MODE_FIELDS, {"name", "definition"}), known)
        return self.store.save_patterns(body["modes"])

    def save_label(self, body: Any) -> dict[str, Any]:
        body = _fields(body, {"mode", "trace_id", "label", "evidence"}, {"mode", "trace_id", "label"})
        if body["trace_id"] not in self._turns:
            raise ValueError(f"unknown trace_id {body['trace_id']}")
        if not isinstance(body["label"], int) or isinstance(body["label"], bool):
            raise ValueError("label must be 0 or 1 (1 = failure present)")
        return save_label(self.store, self.sink, body["mode"], body["trace_id"], body["label"], body.get("evidence") or "")

    # -- checks --------------------------------------------------------------

    def _check_anchor(self, body: dict[str, Any]) -> None:
        if body["trace_id"] not in self._turns:
            raise ValueError(f"unknown trace_id {body['trace_id']}")
        conv, turn = self._turns[body["trace_id"]]
        expected = (conv["session_id"], conv["scenario_id"], turn["index"])
        if (body["session_id"], body["scenario_id"], body["turn"]) != expected:
            raise ValueError("session_id, scenario_id, and turn do not match the trace")

    def _check_mode(self, mode: dict[str, Any], known_annotations: set[str]) -> None:
        if mode.get("status") not in _MODE_STATUSES:
            raise ValueError(f"status must be one of {_MODE_STATUSES[1:]}")
        if mode.get("evaluator_type") not in _EVALUATOR_TYPES:
            raise ValueError("evaluator_type must be code or judge")
        unknown = set(mode.get("created_from") or []) - known_annotations
        if unknown:
            raise ValueError(f"created_from names unknown annotations: {sorted(unknown)}")
        for key in ("example_trace_ids", "close_negative_trace_ids"):
            missing = set(mode.get(key) or []) - set(self._turns)
            if missing:
                raise ValueError(f"{key} names unknown traces: {sorted(missing)}")
