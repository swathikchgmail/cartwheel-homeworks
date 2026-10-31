"""Repository for the HW4 review state under ``analysis/state/``.

One owner per file: annotations, suggestions, patterns, the sample manifest,
and the per-mode label logs. Every write validates first, so a bad request
never reaches disk. Label files stay append-only: a relabel marks the prior
row ``superseded_by`` and appends the new row, the convention the existing
``analysis.helpers.tools._load_labels`` reads.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from analysis.helpers import _state

ANNOTATION_KINDS = ("open_code", "no_failure")
NO_FAILURE_NOTE = "no failure observed"
_STEP = re.compile(r"^(user|reply|tool:\d+)$")
_SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _anchor(trace_id: str, session_id: str, scenario_id: str, turn: int, step: str) -> dict:
    if not _STEP.match(step or ""):
        raise ValueError(f"step must be user, reply, or tool:<n>, got {step!r}")
    if not isinstance(turn, int) or turn < 1:
        raise ValueError("turn must be a positive integer")
    return {"trace_id": trace_id, "session_id": session_id, "scenario_id": scenario_id, "turn": turn, "step": step}


class ReviewStore:
    """Validated reads and writes of the review state files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # -- generic -------------------------------------------------------------

    def read(self, name: str, default: Any = None) -> Any:
        return _state.read_json(self.root / name, default=default)

    def _write(self, name: str, payload: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _state.write_json(self.root / name, payload)

    # -- annotations ---------------------------------------------------------

    def annotations(self) -> list[dict[str, Any]]:
        return self.read("annotations.json", {"annotations": []})["annotations"]

    def _save_annotations(self, rows: list[dict[str, Any]]) -> None:
        self._write("annotations.json", {"annotations": rows})

    def add_annotation(
        self, *, trace_id: str, session_id: str, scenario_id: str, turn: int,
        step: str, note: str, kind: str = "open_code", quote: str | None = None,
        batch: str | None = None, accepted_from: str | None = None,
    ) -> dict[str, Any]:
        if kind not in ANNOTATION_KINDS:
            raise ValueError(f"kind must be one of {ANNOTATION_KINDS}")
        note = (note or "").strip() or (NO_FAILURE_NOTE if kind == "no_failure" else "")
        if not note:
            raise ValueError("an open code needs a note")
        row = {
            "id": _new_id("ann"), **_anchor(trace_id, session_id, scenario_id, turn, step),
            "kind": kind, "note": note, "quote": quote or None, "batch": batch,
            "author": "human", "accepted_from": accepted_from, "ts": _now(), "history": [],
        }
        rows = self.annotations()
        if kind == "open_code":
            _retire_no_failure(rows, row)
        self._save_annotations([*rows, row])
        return row

    def update_annotation(self, annotation_id: str, note: str) -> dict[str, Any]:
        note = (note or "").strip()
        if not note:
            raise ValueError("an edited note cannot be empty")
        rows = self.annotations()
        row = _find(rows, annotation_id)
        row["history"].append({"note": row["note"], "ts": row["ts"]})
        row.update(note=note, ts=_now())
        self._save_annotations(rows)
        return row

    # -- suggestions ---------------------------------------------------------

    def suggestions(self) -> list[dict[str, Any]]:
        return self.read("suggestions.json", [])

    def add_suggestion(
        self, *, trace_id: str, session_id: str, scenario_id: str, turn: int,
        step: str, note: str, source: str, mode: str | None = None,
    ) -> dict[str, Any]:
        """Agent-side write: a hypothesis awaiting a human decision."""
        row = {
            "id": _new_id("sug"), **_anchor(trace_id, session_id, scenario_id, turn, step),
            "note": note, "source": source, "mode": mode, "author": "agent",
            "status": "pending", "decision_reason": None, "decided_ts": None, "ts": _now(),
        }
        self._write("suggestions.json", [*self.suggestions(), row])
        return row

    def accept_suggestion(self, suggestion_id: str, batch: str | None = None) -> dict[str, Any]:
        rows = self.suggestions()
        sug = _pending(rows, suggestion_id)
        anchor = {k: sug[k] for k in ("trace_id", "session_id", "scenario_id", "turn", "step")}
        ann = self.add_annotation(**anchor, note=sug["note"], batch=batch, accepted_from=sug["id"])
        sug.update(status="accepted", decided_ts=_now())
        self._write("suggestions.json", rows)
        return ann

    def reject_suggestion(self, suggestion_id: str, reason: str) -> dict[str, Any]:
        if not (reason or "").strip():
            raise ValueError("a rejection needs a reason")
        rows = self.suggestions()
        sug = _pending(rows, suggestion_id)
        sug.update(status="rejected", decision_reason=reason.strip(), decided_ts=_now())
        self._write("suggestions.json", rows)
        return sug

    # -- patterns and manifest -----------------------------------------------

    def patterns(self) -> dict[str, Any]:
        return self.read("patterns.json", {"modes": []})

    def save_patterns(self, modes: list[dict[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for mode in modes:
            name = str(mode.get("name") or "")
            if not _SNAKE.match(name):
                raise ValueError(f"mode name must be snake_case: {name!r}")
            if name in seen:
                raise ValueError(f"duplicate mode name: {name}")
            seen.add(name)
        payload = {"modes": modes}
        self._write("patterns.json", payload)
        return payload

    def manifest(self) -> dict[str, Any]:
        return self.read("sample_manifest.json", {"batches": []})

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        owner: dict[str, str] = {}
        for batch in manifest.get("batches", []):
            for item in batch.get("items", []):
                sid = item["session_id"]
                if sid in owner:
                    raise ValueError(f"session {sid} is in batches {owner[sid]} and {batch['id']}")
                owner[sid] = batch["id"]
        self._write("sample_manifest.json", manifest)

    # -- labels --------------------------------------------------------------

    def _label_path(self, mode: str) -> Path:
        if not _SNAKE.match(mode or ""):
            raise ValueError(f"mode name must be snake_case: {mode!r}")
        return self.root / "labels" / f"{mode}.jsonl"

    def label_rows(self, mode: str) -> list[dict[str, Any]]:
        return _state.read_jsonl(self._label_path(mode))

    def live_labels(self, mode: str) -> dict[str, dict[str, Any]]:
        return {r["trace_id"]: r for r in self.label_rows(mode) if not r.get("superseded_by")}

    def set_label(
        self, mode: str, trace_id: str, label: int, *, evidence: str, langfuse_synced: bool
    ) -> dict[str, Any]:
        if label not in (0, 1) or isinstance(label, bool):
            raise ValueError("label must be 0 or 1 (1 = failure present)")
        rows = self.label_rows(mode)
        row = {
            "trace_id": trace_id, "mode": mode, "label": label, "evidence": evidence or "",
            "source": "human", "ts": _now(), "langfuse_synced": langfuse_synced,
            "label_id": f"{trace_id}#{sum(r['trace_id'] == trace_id for r in rows)}",
        }
        for prior in rows:
            if prior["trace_id"] == trace_id and not prior.get("superseded_by"):
                prior["superseded_by"] = row["label_id"]
        _state.write_jsonl(self._label_path(mode), [*rows, row])
        return row


def _find(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    for row in rows:
        if row["id"] == row_id:
            return row
    raise KeyError(row_id)


def _retire_no_failure(rows: list[dict[str, Any]], open_code: dict[str, Any]) -> None:
    """An open code contradicts the conversation's "no failure" note: mark it
    retired (kept in the file) rather than deleting it."""
    for prior in rows:
        if prior["session_id"] == open_code["session_id"] and prior["kind"] == "no_failure" and not prior.get("retired_by"):
            prior.update(retired_by=open_code["id"], retired_ts=open_code["ts"])


def _pending(rows: list[dict[str, Any]], suggestion_id: str) -> dict[str, Any]:
    sug = _find(rows, suggestion_id)
    if sug["status"] != "pending":
        raise ValueError(f"suggestion {suggestion_id} is already {sug['status']}")
    return sug
