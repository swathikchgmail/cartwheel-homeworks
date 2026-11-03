"""HTTP routes of the review app: shapes, validation errors, and not-found.

The server runs on an ephemeral localhost port with a temporary state
directory and a fake label sink, so the tests make no network calls.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from analysis.review_app.server import ReviewApp, make_server
from analysis.review_app.store import ReviewStore

CONVERSATIONS = [
    {
        "session_id": "s1",
        "scenario_id": "support-0082",
        "role": "shopper",
        "turns": [{"index": 1, "trace_id": "t1", "steps": []}],
    }
]


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def write(self, trace_id: str, mode: str, label: int, comment: str | None) -> None:
        self.calls.append((trace_id, mode, label))


@pytest.fixture
def base_url(tmp_path: Path) -> Iterator[str]:
    app = ReviewApp(CONVERSATIONS, ReviewStore(tmp_path), RecordingSink())
    server = make_server(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _call(url: str, body: Any | None = None, raw: bytes | None = None) -> tuple[int, Any]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


ANNOTATION = {"trace_id": "t1", "session_id": "s1", "scenario_id": "support-0082", "turn": 1, "step": "reply", "note": "n"}


def test_conversations_route_returns_the_loaded_conversations(base_url: str) -> None:
    status, body = _call(f"{base_url}/api/conversations")
    assert (status, body[0]["scenario_id"]) == (200, "support-0082")


def test_state_route_returns_every_state_section(base_url: str) -> None:
    _, body = _call(f"{base_url}/api/state")
    assert set(body) == {"annotations", "suggestions", "patterns", "manifest", "labels"}


def test_creating_an_annotation_returns_201(base_url: str) -> None:
    status, body = _call(f"{base_url}/api/annotations", ANNOTATION)
    assert (status, body["author"]) == (201, "human")


def test_annotation_for_an_unknown_trace_returns_400(base_url: str) -> None:
    status, _ = _call(f"{base_url}/api/annotations", {**ANNOTATION, "trace_id": "nope"})
    assert status == 400


def test_invalid_json_returns_400(base_url: str) -> None:
    status, _ = _call(f"{base_url}/api/annotations", raw=b"{not json")
    assert status == 400


def test_unexpected_annotation_field_returns_400(base_url: str) -> None:
    status, _ = _call(f"{base_url}/api/annotations", {**ANNOTATION, "author": "agent"})
    assert status == 400


def test_label_route_writes_through_the_sink(base_url: str) -> None:
    status, body = _call(f"{base_url}/api/labels", {"mode": "unconfirmed_write", "trace_id": "t1", "label": 1, "evidence": "q"})
    assert (status, body["synced"]) == (200, True)


def test_label_with_bad_value_returns_400(base_url: str) -> None:
    status, _ = _call(f"{base_url}/api/labels", {"mode": "unconfirmed_write", "trace_id": "t1", "label": "yes", "evidence": ""})
    assert status == 400


def test_rejecting_an_unknown_suggestion_returns_404(base_url: str) -> None:
    status, _ = _call(f"{base_url}/api/suggestions/missing/reject", {"reason": "x"})
    assert status == 404


def test_unknown_route_returns_404(base_url: str) -> None:
    status, _ = _call(f"{base_url}/api/nothing")
    assert status == 404


def test_index_page_is_served(base_url: str) -> None:
    with urllib.request.urlopen(f"{base_url}/") as resp:
        assert b"<title>" in resp.read()
