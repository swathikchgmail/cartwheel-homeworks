"""Accepted binary judgments go to Langfuse as scores and to local files.

The local label row is written even when the Langfuse write fails, and the
row records whether the score reached Langfuse so it can be retried.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from analysis.review_app.label_sync import LangfuseLabelSink, save_label, score_id
from analysis.review_app.store import ReviewStore


class FakeClient:
    def __init__(self, fail: bool = False, reachable: bool = True) -> None:
        self.fail = fail
        self.reachable = reachable
        self.scores: list[dict[str, Any]] = []
        self.flushed = 0

    def auth_check(self) -> bool:
        # The real client raises when the server is down and queues scores silently.
        if not self.reachable:
            raise ConnectionError("Connection refused")
        return True

    def create_score(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("langfuse down")
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushed += 1


@pytest.fixture
def store(tmp_path: Path) -> ReviewStore:
    return ReviewStore(tmp_path)


def test_sink_writes_a_numeric_score_named_after_the_mode() -> None:
    client = FakeClient()
    LangfuseLabelSink(client).write("a" * 32, "unconfirmed_write", 1, "queued")
    score = client.scores[0]
    assert (score["name"], score["value"], score["data_type"]) == ("unconfirmed_write", 1, "NUMERIC")


def test_sink_uses_a_stable_score_id_so_relabels_overwrite() -> None:
    client = FakeClient()
    sink = LangfuseLabelSink(client)
    sink.write("a" * 32, "unconfirmed_write", 1, None)
    sink.write("a" * 32, "unconfirmed_write", 0, None)
    assert client.scores[0]["score_id"] == client.scores[1]["score_id"]


def test_score_id_differs_by_mode() -> None:
    assert score_id("t1", "mode_a") != score_id("t1", "mode_b")


def test_save_label_records_a_synced_label(store: ReviewStore) -> None:
    result = save_label(store, LangfuseLabelSink(FakeClient()), "unconfirmed_write", "t1", 1, "queued")
    assert (result["synced"], store.live_labels("unconfirmed_write")["t1"]["langfuse_synced"]) == (True, True)


def test_failed_langfuse_write_still_saves_locally(store: ReviewStore) -> None:
    result = save_label(store, LangfuseLabelSink(FakeClient(fail=True)), "unconfirmed_write", "t1", 1, "q")
    assert (result["synced"], store.live_labels("unconfirmed_write")["t1"]["label"]) == (False, 1)


def test_failed_langfuse_write_reports_the_error(store: ReviewStore) -> None:
    result = save_label(store, LangfuseLabelSink(FakeClient(fail=True)), "unconfirmed_write", "t1", 1, "q")
    assert "langfuse down" in result["error"]


def test_unreachable_langfuse_saves_locally_as_unsynced(store: ReviewStore) -> None:
    result = save_label(store, LangfuseLabelSink(FakeClient(reachable=False)), "unconfirmed_write", "t1", 1, "q")
    assert store.live_labels("unconfirmed_write")["t1"]["langfuse_synced"] is False


def test_unreachable_langfuse_reports_the_error(store: ReviewStore) -> None:
    result = save_label(store, LangfuseLabelSink(FakeClient(reachable=False)), "unconfirmed_write", "t1", 1, "q")
    assert "Connection refused" in result["error"]


def test_unreachable_langfuse_queues_no_score() -> None:
    client = FakeClient(reachable=False)
    with pytest.raises(ConnectionError):
        LangfuseLabelSink(client).write("a" * 32, "unconfirmed_write", 1, None)
    assert client.scores == []


def test_offline_sink_saves_locally_as_unsynced(store: ReviewStore) -> None:
    result = save_label(store, None, "unconfirmed_write", "t1", 0, "")
    assert result["synced"] is False
