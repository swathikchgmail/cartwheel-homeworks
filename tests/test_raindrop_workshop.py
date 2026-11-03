"""Optional Raindrop Workshop mirror: off by default, one interaction per turn."""

from __future__ import annotations

from typing import Any

import pytest

from observability import raindrop_workshop as rw


class FakeInteraction:
    def __init__(self) -> None:
        self.output: str | None = None

    def finish(self, *, output: str | None = None) -> None:
        self.output = output


class FakeClient:
    def __init__(self) -> None:
        self.begun: list[dict[str, Any]] = []
        self.interaction = FakeInteraction()
        self.flushed = 0

    def begin(self, **kwargs: Any) -> FakeInteraction:
        self.begun.append(kwargs)
        return self.interaction

    def flush(self) -> None:
        self.flushed += 1


def _turn(client: FakeClient):
    return rw.workshop_turn(
        user_id="1", session_id="s1", message="hi", properties={"role": "shopper"}, client=client
    )


# -- off by default -------------------------------------------------------------


def test_disabled_without_the_env_var(monkeypatch):
    monkeypatch.delenv(rw.ENV_VAR, raising=False)
    assert rw.enabled() is False


def test_enabled_with_the_env_var(monkeypatch):
    monkeypatch.setenv(rw.ENV_VAR, "http://localhost:5899/v1/")
    assert rw.enabled() is True


def test_turn_yields_none_when_disabled(monkeypatch):
    monkeypatch.delenv(rw.ENV_VAR, raising=False)
    with rw.workshop_turn(user_id="1", session_id="s1", message="hi", properties={}) as interaction:
        assert interaction is None


def test_finish_turn_is_a_no_op_without_an_interaction():
    assert rw.finish_turn(None, "reply") is None


# -- one interaction per turn ---------------------------------------------------------


def test_turn_begins_one_interaction_with_the_turn_details():
    client = FakeClient()
    with _turn(client):
        pass
    assert client.begun == [{"user_id": "1", "event": "support_turn", "input": "hi", "convo_id": "s1",
                             "properties": {"role": "shopper"}}]


def test_finish_turn_records_the_reply_and_flushes():
    client = FakeClient()
    with _turn(client) as interaction:
        rw.finish_turn(interaction, "done", client=client)
    assert (client.interaction.output, client.flushed) == ("done", 1)


def test_turn_records_an_error_and_re_raises_it():
    client = FakeClient()
    with pytest.raises(RuntimeError, match="boom"):
        with _turn(client):
            raise RuntimeError("boom")
    assert client.interaction.output == "Error: boom"
