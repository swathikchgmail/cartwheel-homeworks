"""Turn normalized per-turn traces into conversations a reviewer can read.

Cartwheel writes one Langfuse trace per user turn. This module groups traces
by ``session_id``, orders the turns by timestamp, keeps only the tool
observations as visible steps (wrapper spans and model calls carry no
reviewable content), and attaches the HW3 scenario record as the reference.

Time:  O(n log n) for n traces (sorting turns within sessions).
Space: O(n) for the grouped output.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from analysis.helpers.normalization import _text

# Fields worth showing on a tool card, in display order. Anything else stays
# in the expandable JSON.
_SUMMARY_KEYS = (
    "status",
    "refund_id",
    "ticket_id",
    "amount_usd",
    "delivered_at",
    "refund_eligible",
    "total_usd",
    "policy_id",
    "count",
)
_MAX_SUMMARY_FIELDS = 3


def build_conversations(
    traces: list[dict[str, Any]],
    scenarios: dict[str, dict[str, Any]],
    prefix: str = "support-",
) -> list[dict[str, Any]]:
    """Group traces whose scenario id starts with ``prefix`` into conversations."""
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        meta = trace.get("meta") or {}
        if str(meta.get("scenario_id") or "").startswith(prefix):
            sessions[meta.get("session_id") or trace["trace_id"]].append(trace)
    conversations = [
        _conversation(session_id, turns, scenarios)
        for session_id, turns in sessions.items()
    ]
    conversations.sort(key=lambda c: c["scenario_id"])
    return conversations


def _conversation(
    session_id: str, traces: list[dict[str, Any]], scenarios: dict[str, Any]
) -> dict[str, Any]:
    ordered = sorted(traces, key=lambda t: str(t.get("timestamp") or ""))
    first = ordered[0]
    meta = first.get("meta") or {}
    scenario_id = meta.get("scenario_id")
    return {
        "session_id": session_id,
        "scenario_id": scenario_id,
        "role": meta.get("role"),
        "user_id": (first.get("metadata") or {}).get("cartwheel.user_id"),
        "prompt_version": meta.get("prompt_version"),
        "reference": scenarios.get(scenario_id),
        "system_prompt": _system_prompt(first),
        "turns": [_turn(i, t) for i, t in enumerate(ordered, start=1)],
    }


def _turn(index: int, trace: dict[str, Any]) -> dict[str, Any]:
    observations = trace.get("observations") or []
    tools = sorted(
        (o for o in observations if o.get("type") == "TOOL"),
        key=lambda o: str(o.get("start_time") or ""),
    )
    return {
        "index": index,
        "trace_id": trace["trace_id"],
        "timestamp": trace.get("timestamp"),
        "user_text": _text(trace.get("input")),
        "reply_text": _text(trace.get("output")),
        "steps": [_tool_step(o) for o in tools],
        "model_calls": sum(1 for o in observations if o.get("type") == "GENERATION"),
    }


def _tool_step(observation: dict[str, Any]) -> dict[str, Any]:
    output = _parsed(observation.get("output"))
    return {
        "name": observation.get("name"),
        "input": _parsed(observation.get("input")),
        "output": output,
        "ok": output.get("ok") is not False if isinstance(output, dict) else None,
        "summary": tool_summary(output),
    }


def tool_summary(output: Any) -> str:
    """One line with the fields a reviewer checks first on a tool result."""
    if not isinstance(output, dict):
        return str(output)
    if output.get("ok") is False:
        return f"{output.get('error', 'error')}: {output.get('reason', '')}".strip()
    record = _first_record(output)
    parts = [f"order {record['order_id']}"] if "order_id" in record else []
    if "product_id" in record and "order_id" not in record:
        parts.append(f"product {record['product_id']}")
    for key in _SUMMARY_KEYS:
        if key in record and len(parts) < _MAX_SUMMARY_FIELDS:
            parts.append(f"{key} {_fmt(record[key])}")
    return " · ".join(parts) or ", ".join(k for k in output if k != "ok")


def _first_record(output: dict[str, Any]) -> dict[str, Any]:
    """The order/product/result a list-shaped tool output leads with."""
    for key in ("orders", "products", "results"):
        if isinstance(output.get(key), list) and output[key]:
            return output[key][0]
    if isinstance(output.get("order"), dict):
        return output["order"]
    return output


def _fmt(value: Any) -> str:
    return json.dumps(value) if isinstance(value, bool) or value is None else str(value)


def _parsed(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _system_prompt(trace: dict[str, Any]) -> str:
    """The system prompt from the first model call, shown collapsed in the UI."""
    for observation in trace.get("observations") or []:
        if observation.get("type") != "GENERATION":
            continue
        for message in observation.get("input") or []:
            if isinstance(message, dict) and message.get("role") == "system":
                return _text([message])
    return ""
