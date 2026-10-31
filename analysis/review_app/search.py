"""Part D depth searches over whole conversations (batch 3).

Each signal is a deterministic filter on tool activity and the scenario's
intent, never on the expected outcome: it marks a conversation worth reading
for one mode, and the human review decides whether the mode is present.
Picks reuse the seeded uniform draw from ``sampling`` so a seed gives the
same batch whatever the input order.

Run: uv run python -m analysis.review_app.sampling --batch 3
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from analysis.review_app.sampling import _item, _pool, uniform_items
from analysis.review_app.store import ReviewStore

RETURN_INTENTS = {"refund", "return_eligibility", "policy_question"}

Conv = dict[str, Any]


def _steps(conv: Conv) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(tool name, input, output) for every tool step; text payloads count as empty."""
    for turn in conv["turns"]:
        for step in turn["steps"]:
            inp, out = step.get("input"), step.get("output")
            yield step["name"], inp if isinstance(inp, dict) else {}, out if isinstance(out, dict) else {}


def _orders(out: dict[str, Any]) -> list[dict[str, Any]]:
    return [*(out.get("orders") or []), *([out["order"]] if out.get("order") else [])]


def store_override_signal(conv: Conv, override_stores: set[int]) -> bool:
    """A return or refund question where a tool showed an order from a store
    with its own return window."""
    if conv["reference"]["tuple"].get("intent") not in RETURN_INTENTS:
        return False
    return any(o.get("store_id") in override_stores for _, _, out in _steps(conv) for o in _orders(out))


def _orders_in_question(conv: Conv) -> set[int]:
    """Order ids the agent acted on (get_order, issue_refund) or named in a reply."""
    looked_up = {inp["order_id"] for name, inp, _ in _steps(conv)
                 if name in ("get_order", "issue_refund") and inp.get("order_id") is not None}
    named = {int(n) for t in conv["turns"] for n in re.findall(r"\b\d+\b", t.get("reply_text") or "")}
    return looked_up | named


def order_in_question_signal(conv: Conv, override_stores: set[int]) -> bool:
    """Round 2, after the definition revision: a return or refund question where
    the order in question (not just any listed order) is from an override store."""
    if conv["reference"]["tuple"].get("intent") not in RETURN_INTENTS:
        return False
    wanted = _orders_in_question(conv)
    return any(o.get("order_id") in wanted and o.get("store_id") in override_stores
               for _, _, out in _steps(conv) for o in _orders(out))


def draw_store_policy_round_2(convs: list[Conv], override_stores: set[int], seed: int,
                              exclude: set[str], min_traces: int = 4) -> list[dict[str, Any]]:
    return _search(convs, lambda c: order_in_question_signal(c, override_stores), min_traces, seed, set(exclude),
                   "search store_policy_ignored round 2: order in question is from an override store")


def _search_counts(conv: Conv) -> Iterator[tuple[Any, Any]]:
    for name, inp, out in _steps(conv):
        if name == "search_products" and "count" in out:
            yield inp.get("limit"), out["count"]


def truncated_search_signal(conv: Conv) -> bool:
    return any(limit and count == limit for limit, count in _search_counts(conv))


def untruncated_search_signal(conv: Conv) -> bool:
    return any(limit and count < limit for limit, count in _search_counts(conv))


def bad_data_signal(conv: Conv) -> str | None:
    """Name the first impossible value a tool returned, or None."""
    for _, _, out in _steps(conv):
        for product in out.get("products") or []:
            if (product.get("price_usd") or 0) < 0:
                return "negative price"
            if not (product.get("title") or "").strip():
                return "empty title"
        for order in _orders(out):
            shipped, delivered = order.get("shipped_at"), order.get("delivered_at")
            if shipped and delivered and delivered < shipped:
                return "delivered before shipped"
    return None


def _search(convs: list[Conv], hit: Callable[[Conv], bool], min_traces: int, seed: int,
            taken: set[str], reason: str) -> list[dict[str, Any]]:
    picked = uniform_items([c for c in convs if hit(c)], min_traces, seed, taken)
    taken |= {i["session_id"] for i in picked}
    return [{**i, "reason": reason} for i in picked]


def draw_batch_3(convs: list[Conv], override_stores: set[int], seed: int, exclude: set[str]) -> dict[str, Any]:
    """Every truncated search, 8 single-turn store-override traces (round 1),
    4 bad-data traces, and 2 close-negative searches. Time O(n log n)."""
    taken = set(exclude)
    truncated = [_item(c, "search results_truncated_silently: count == limit")
                 for c in _pool(convs, taken) if truncated_search_signal(c)]
    taken |= {i["session_id"] for i in truncated}
    single_override = lambda c: len(c["turns"]) == 1 and store_override_signal(c, override_stores)  # noqa: E731
    items = truncated + _search(convs, single_override, 8, seed, taken,
                                "search store_policy_ignored round 1: override store on a return question")
    items += _search(convs, lambda c: bad_data_signal(c) is not None, 4, seed, taken,
                     "search invalid_data_not_flagged: impossible value in a tool result")
    items += _search(convs, untruncated_search_signal, 2, seed, taken,
                     "search results_truncated_silently close negative: count < limit")
    return {
        "id": "batch-3",
        "label": "Batch 3: depth searches",
        "method": "deterministic retrieval signals on tool activity and intent (not outcomes); seeded draw within each signal",
        "final_check": False,
        "seed": seed,
        "excluded": sorted(exclude),
        "items": items,
    }


def extend_batch(store: ReviewStore, batch_id: str, items: list[dict[str, Any]]) -> None:
    """Append items to an existing batch, e.g. a repeat search after a definition revision."""
    manifest = store.manifest()
    batch = next(b for b in manifest["batches"] if b["id"] == batch_id)
    batch["items"] = [*batch["items"], *items]
    store.save_manifest(manifest)
