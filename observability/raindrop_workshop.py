"""Optional Raindrop Workshop mirror of agent turns (HW4 Part C).

Off unless RAINDROP_LOCAL_DEBUGGER is set (for example
``http://localhost:5899/v1/``). When on, each server turn is recorded as one
Workshop interaction with its input, reply and properties. The interaction
shares the turn's OpenTelemetry trace id, so the matching Langfuse trace holds
the tool calls.

Local only: no write key is passed, so the SDK skips Raindrop Cloud and sends
to the Workshop URL alone. Tool spans are not sent: in raindrop-ai 0.0.75 they
need Raindrop tracing, which requires a cloud write key and attaches an
exporter to the Langfuse tracer provider.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

ENV_VAR = "RAINDROP_LOCAL_DEBUGGER"
_sdk: Any = None


def enabled() -> bool:
    return bool(os.environ.get(ENV_VAR, "").strip())


def _client() -> Any:  # pragma: no cover - imports the optional SDK
    global _sdk
    if _sdk is None:
        import raindrop.analytics as rd

        rd.init(
            api_key=None,
            tracing_enabled=False,
            auto_instrument=False,
            local_workshop_url=os.environ[ENV_VAR],
            app_git=False,
        )
        _sdk = rd
    return _sdk


@contextmanager
def workshop_turn(
    *, user_id: str, session_id: str, message: str, properties: dict[str, Any], client: Any = None
) -> Iterator[Any]:
    """Yield a Workshop interaction for one turn, or None when Workshop is off.

    An exception inside the block finishes the interaction with the error and
    is re-raised unchanged.
    """
    if client is None and not enabled():
        yield None
        return
    rd = client or _client()
    interaction = rd.begin(
        user_id=user_id, event="support_turn", input=message,
        convo_id=session_id, properties=properties,
    )
    try:
        yield interaction
    except Exception as exc:
        interaction.finish(output=f"Error: {exc}")
        rd.flush()
        raise


def finish_turn(interaction: Any, reply: str, client: Any = None) -> None:
    """Record the reply on the interaction, then flush."""
    if interaction is None:
        return
    interaction.finish(output=reply)
    (client or _client()).flush()
