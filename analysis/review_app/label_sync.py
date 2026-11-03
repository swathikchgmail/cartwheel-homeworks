"""Write accepted binary judgments to Langfuse scores and the local label log.

Langfuse is the canonical store; ``analysis/state/labels/`` is the committed
mirror. The sink is injected so tests and offline runs never touch the
network. A stable ``score_id`` per (trace, mode) makes a relabel overwrite
the earlier score instead of adding a second one.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

from analysis.review_app.store import ReviewStore


class LabelSink(Protocol):
    def write(self, trace_id: str, mode: str, label: int, comment: str | None) -> None: ...


def score_id(trace_id: str, mode: str) -> str:
    """Deterministic score id, so one (trace, mode) pair has one score."""
    return hashlib.sha256(f"hw4:{mode}:{trace_id}".encode()).hexdigest()[:32]


class LangfuseLabelSink:
    """Writes a 0/1 NUMERIC score named after the mode (1 = failure present)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def write(self, trace_id: str, mode: str, label: int, comment: str | None) -> None:
        # create_score and flush queue silently when the server is down, so
        # check it is reachable first; auth_check raises on a refused connection.
        if not self._client.auth_check():
            raise RuntimeError("Langfuse auth check failed")
        self._client.create_score(
            name=mode,
            value=int(label),
            trace_id=trace_id,
            score_id=score_id(trace_id, mode),
            data_type="NUMERIC",
            comment=comment or None,
        )
        self._client.flush()


def save_label(
    store: ReviewStore,
    sink: LabelSink | None,
    mode: str,
    trace_id: str,
    label: int,
    evidence: str,
) -> dict[str, Any]:
    """Try Langfuse first, then always record the label locally."""
    synced, error = False, None
    if sink is not None:
        try:
            sink.write(trace_id, mode, label, evidence)
            synced = True
        except Exception as exc:  # network or API failure; keep the local copy
            error = f"Langfuse score write failed: {exc}"
    row = store.set_label(mode, trace_id, label, evidence=evidence, langfuse_synced=synced)
    return {"label": row, "synced": synced, "error": error}
