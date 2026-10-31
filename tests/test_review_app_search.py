"""Part D depth searches: retrieval signals that pick batch-3 conversations.

A signal only says a conversation is worth reading for a mode; the human
review decides whether the mode is present.
"""

from __future__ import annotations

from analysis.review_app.search import (
    RETURN_INTENTS,
    bad_data_signal,
    draw_batch_3,
    draw_store_policy_round_2,
    extend_batch,
    order_in_question_signal,
    store_override_signal,
    truncated_search_signal,
    untruncated_search_signal,
)
from analysis.review_app.sampling import add_batch
from analysis.review_app.store import ReviewStore


def _conv(sid: str, steps: list[dict], intent: str = "refund", turns: int = 1) -> dict:
    return {
        "session_id": sid,
        "scenario_id": sid,
        "role": "shopper",
        "reference": {"tuple": {"intent": intent}},
        "turns": [{"trace_id": f"{sid}-t{i}", "steps": steps if i == 0 else []} for i in range(turns)],
    }


def _order(store_id: int = 1, shipped: str = "2026-06-02", delivered: str = "2026-06-04") -> dict:
    return {"name": "get_order", "ok": True, "input": {}, "output": {"ok": True, "order": {
        "store_id": store_id, "ordered_at": "2026-06-01", "shipped_at": shipped, "delivered_at": delivered}}}


def _search(limit: int, count: int, price: float = 10.0, title: str = "Mug") -> dict:
    return {"name": "search_products", "ok": True, "input": {"limit": limit},
            "output": {"ok": True, "products": [{"title": title, "price_usd": price}], "count": count}}


# -- store override -----------------------------------------------------------


def test_store_override_signal_matches_an_override_store_on_a_return_question():
    assert store_override_signal(_conv("a", [_order(store_id=7)]), {7}) is True


def test_store_override_signal_ignores_stores_without_an_override():
    assert store_override_signal(_conv("a", [_order(store_id=3)]), {7}) is False


def test_store_override_signal_ignores_non_return_intents():
    assert store_override_signal(_conv("a", [_order(store_id=7)], intent="order_status"), {7}) is False


def test_store_override_signal_reads_order_lists():
    step = {"name": "find_order", "ok": True, "input": {}, "output": {"orders": [{"store_id": 7}]}}
    assert store_override_signal(_conv("a", [step]), {7}) is True


def test_return_intents_cover_refund_return_and_policy_questions():
    assert RETURN_INTENTS == {"refund", "return_eligibility", "policy_question"}


# -- truncated search -----------------------------------------------------------


def test_truncated_search_signal_matches_count_equal_to_limit():
    assert truncated_search_signal(_conv("a", [_search(limit=5, count=5)])) is True


def test_truncated_search_signal_ignores_fewer_results_than_limit():
    assert truncated_search_signal(_conv("a", [_search(limit=5, count=3)])) is False


def test_untruncated_search_signal_matches_fewer_results_than_limit():
    assert untruncated_search_signal(_conv("a", [_search(limit=5, count=3)])) is True


def test_tool_output_as_text_is_ignored_not_an_error():
    step = {"name": "search_products", "ok": False, "input": "x", "output": "boom"}
    assert truncated_search_signal(_conv("a", [step])) is False


# -- bad data -----------------------------------------------------------------


def test_bad_data_signal_finds_delivery_before_shipment():
    conv = _conv("a", [_order(shipped="2026-06-25", delivered="2026-06-23")])
    assert bad_data_signal(conv) == "delivered before shipped"


def test_bad_data_signal_finds_a_negative_price():
    assert bad_data_signal(_conv("a", [_search(5, 1, price=-5)])) == "negative price"


def test_bad_data_signal_finds_an_empty_title():
    assert bad_data_signal(_conv("a", [_search(5, 1, title=" ")])) == "empty title"


def test_bad_data_signal_is_none_for_clean_data():
    assert bad_data_signal(_conv("a", [_order(), _search(5, 1)])) is None


# -- batch 3 ------------------------------------------------------------------


def _pool() -> list[dict]:
    over = [_conv(f"over{i}", [_order(store_id=7)]) for i in range(12)]
    trunc = [_conv(f"trunc{i}", [_search(5, 5)], intent="product_search") for i in range(2)]
    clean = [_conv(f"clean{i}", [_search(5, 2)], intent="product_search") for i in range(5)]
    bad = [_conv(f"bad{i}", [_order(store_id=2, shipped="2026-06-25", delivered="2026-06-23")], intent="order_status") for i in range(5)]
    return over + trunc + clean + bad


def _reasons(batch: dict) -> list[str]:
    return [i["reason"] for i in batch["items"]]


def test_draw_batch_3_has_no_session_twice():
    sids = [i["session_id"] for i in draw_batch_3(_pool(), {7}, seed=1, exclude=set())["items"]]
    assert len(sids) == len(set(sids))


def test_draw_batch_3_takes_eight_store_override_traces_in_round_one():
    batch = draw_batch_3(_pool(), {7}, seed=1, exclude=set())
    assert sum(r.startswith("search store_policy_ignored round 1") for r in _reasons(batch)) == 8


def test_draw_batch_3_takes_every_truncated_search():
    batch = draw_batch_3(_pool(), {7}, seed=1, exclude=set())
    assert {i["session_id"] for i in batch["items"] if "results_truncated_silently: count" in i["reason"]} == {"trunc0", "trunc1"}


def test_draw_batch_3_adds_two_close_negative_searches():
    batch = draw_batch_3(_pool(), {7}, seed=1, exclude=set())
    assert sum("close negative" in r for r in _reasons(batch)) == 2


def test_draw_batch_3_takes_four_bad_data_traces():
    batch = draw_batch_3(_pool(), {7}, seed=1, exclude=set())
    assert sum(r.startswith("search invalid_data_not_flagged") for r in _reasons(batch)) == 4


def test_draw_batch_3_skips_excluded_sessions():
    batch = draw_batch_3(_pool(), {7}, seed=1, exclude={"trunc0"})
    assert "trunc0" not in {i["session_id"] for i in batch["items"]}


def test_draw_batch_3_is_reproducible_for_a_seed():
    first = draw_batch_3(_pool(), {7}, seed=1, exclude=set())
    second = draw_batch_3(list(reversed(_pool())), {7}, seed=1, exclude=set())
    assert first["items"] == second["items"]


def test_draw_batch_3_records_how_it_was_drawn():
    batch = draw_batch_3(_pool(), {7}, seed=1, exclude={"x"})
    assert {k: batch[k] for k in ("id", "final_check", "seed", "excluded")} == {
        "id": "batch-3", "final_check": False, "seed": 1, "excluded": ["x"],
    }


# -- round 2: the order in question ---------------------------------------------


def _listing(*orders: tuple[int, int]) -> dict:
    return {"name": "find_order", "ok": True, "input": {},
            "output": {"orders": [{"order_id": oid, "store_id": sid} for oid, sid in orders]}}


def _with_reply(conv: dict, text: str) -> dict:
    conv["turns"][0]["reply_text"] = text
    return conv


def test_order_in_question_signal_matches_a_looked_up_override_order():
    step = {"name": "get_order", "ok": True, "input": {"order_id": 11}, "output": {"order": {"order_id": 11, "store_id": 7}}}
    assert order_in_question_signal(_with_reply(_conv("a", [step]), "x"), {7}) is True


def test_order_in_question_signal_ignores_an_override_order_only_listed():
    conv = _with_reply(_conv("a", [_listing((11, 7), (12, 3))]), "Order #12 is eligible")
    assert order_in_question_signal(conv, {7}) is False


def test_order_in_question_signal_matches_a_listed_override_order_the_reply_names():
    conv = _with_reply(_conv("a", [_listing((11, 7), (12, 3))]), "Order #11 was delivered")
    assert order_in_question_signal(conv, {7}) is True


def test_order_in_question_signal_ignores_non_return_intents():
    conv = _with_reply(_conv("a", [_listing((11, 7))], intent="order_status"), "Order #11")
    assert order_in_question_signal(conv, {7}) is False


def test_draw_store_policy_round_2_takes_the_trace_minimum():
    convs = [_with_reply(_conv(f"r{i}", [_listing((i, 7))]), f"order {i}") for i in range(10)]
    items = draw_store_policy_round_2(convs, {7}, seed=1, exclude=set(), min_traces=4)
    assert sum(len(i["trace_ids"]) for i in items) == 4


def test_draw_store_policy_round_2_names_the_round_in_the_reason():
    convs = [_with_reply(_conv("r0", [_listing((5, 7))]), "order 5")]
    [item] = draw_store_policy_round_2(convs, {7}, seed=1, exclude=set(), min_traces=1)
    assert item["reason"].startswith("search store_policy_ignored round 2")


# -- extending a batch ----------------------------------------------------------


def test_extend_batch_appends_items_to_an_existing_batch(tmp_path):
    store = ReviewStore(tmp_path)
    add_batch(store, {"id": "batch-3", "items": [{"session_id": "s0", "trace_ids": ["t"]}]})
    extend_batch(store, "batch-3", [{"session_id": "s1", "trace_ids": ["u"]}])
    assert [i["session_id"] for i in store.manifest()["batches"][0]["items"]] == ["s0", "s1"]
