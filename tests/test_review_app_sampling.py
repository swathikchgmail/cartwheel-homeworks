"""Batch selection for Part B: uniform and cluster picks over conversations."""

from __future__ import annotations

import pytest

from analysis.review_app.sampling import (
    add_batch,
    cluster_items,
    conversation_features,
    draw_batch_1,
    draw_batch_2,
    draw_batch_4,
    manifest_sessions,
    resolve_exclude,
    uniform_items,
)
from analysis.review_app.store import ReviewStore


def _conv(sid: str, turns: int = 1, tools: int = 0, errors: int = 0, words: int = 5, role: str = "shopper") -> dict:
    steps = [{"name": f"tool_{i % 2}", "ok": i >= errors} for i in range(tools)]
    return {
        "session_id": sid,
        "scenario_id": sid,
        "role": role,
        "turns": [
            {"trace_id": f"{sid}-t{i}", "user_text": "w " * words, "reply_text": "r " * words, "steps": steps if i == 0 else []}
            for i in range(turns)
        ],
    }


def _traces(items: list[dict]) -> int:
    return sum(len(i["trace_ids"]) for i in items)


# -- features ---------------------------------------------------------------


def test_conversation_features_counts_shape_not_outcome():
    conv = _conv("a", turns=2, tools=3, errors=1, words=4)
    assert conversation_features(conv) == [2.0, 3.0, 2.0, 1.0, 8.0, 8.0]


# -- uniform ------------------------------------------------------------------


def test_uniform_items_stop_once_trace_minimum_is_reached():
    convs = [_conv(f"s{i}", turns=2) for i in range(20)]
    items = uniform_items(convs, min_traces=5, seed=1, exclude=set())
    assert _traces(items) == 6


def test_uniform_items_are_reproducible_for_a_seed():
    convs = [_conv(f"s{i}") for i in range(30)]
    first = uniform_items(convs, min_traces=5, seed=3, exclude=set())
    second = uniform_items(list(reversed(convs)), min_traces=5, seed=3, exclude=set())
    assert first == second


def test_uniform_items_skip_excluded_sessions():
    convs = [_conv(f"s{i}") for i in range(10)]
    items = uniform_items(convs, min_traces=8, seed=1, exclude={"s0", "s1"})
    assert {"s0", "s1"}.isdisjoint(i["session_id"] for i in items)


def test_uniform_items_record_trace_ids_and_reason():
    items = uniform_items([_conv("s0", turns=2)], min_traces=1, seed=1, exclude=set())
    assert items == [{"session_id": "s0", "scenario_id": "s0", "trace_ids": ["s0-t0", "s0-t1"], "reason": "uniform pick"}]


# -- cluster ------------------------------------------------------------------


def _two_groups() -> list[dict]:
    # Group A: short, no tools (5 members, s-a2 is the centre).
    # Group B: long with many tools (3 members, s-b1 is the centre).
    a = [_conv(f"s-a{i}", words=w) for i, w in enumerate([3, 4, 5, 6, 7])]
    b = [_conv(f"s-b{i}", turns=3, tools=t, words=40) for i, t in enumerate([5, 6, 7])]
    return a + b


def test_cluster_items_take_the_member_closest_to_each_centre():
    items = cluster_items(_two_groups(), min_traces=4, k=2, seed=1, exclude=set())
    assert [i["session_id"] for i in items] == ["s-a2", "s-b1"]


def test_cluster_items_start_with_the_biggest_cluster():
    items = cluster_items(_two_groups(), min_traces=1, k=2, seed=1, exclude=set())
    assert items[0]["session_id"] == "s-a2"


def test_cluster_items_go_round_again_until_minimum_is_reached():
    items = cluster_items(_two_groups(), min_traces=6, k=2, seed=1, exclude=set())
    assert _traces(items) >= 6


def test_cluster_items_skip_excluded_sessions():
    items = cluster_items(_two_groups(), min_traces=4, k=2, seed=1, exclude={"s-a2"})
    assert "s-a2" not in {i["session_id"] for i in items}


def test_cluster_items_name_the_cluster_in_the_reason():
    items = cluster_items(_two_groups(), min_traces=1, k=2, seed=1, exclude=set())
    assert items[0]["reason"].startswith("cluster ") and items[0]["reason"].endswith(" representative")


# -- batch 1 ------------------------------------------------------------------


def test_draw_batch_1_has_no_session_in_both_parts():
    convs = [_conv(f"s{i}", turns=1 + i % 3, tools=i % 4, words=3 + i) for i in range(60)]
    batch = draw_batch_1(convs, seed=5, exclude=set(), min_traces=15, k=10)
    sids = [i["session_id"] for i in batch["items"]]
    assert len(sids) == len(set(sids))


def test_draw_batch_1_reaches_the_minimum_in_each_part():
    convs = [_conv(f"s{i}", turns=1 + i % 3, tools=i % 4, words=3 + i) for i in range(60)]
    batch = draw_batch_1(convs, seed=5, exclude=set(), min_traces=15, k=10)
    uniform = [i for i in batch["items"] if i["reason"] == "uniform pick"]
    cluster = [i for i in batch["items"] if i["reason"] != "uniform pick"]
    assert (_traces(uniform) >= 15, _traces(cluster) >= 15) == (True, True)


def test_draw_batch_1_records_how_it_was_drawn():
    batch = draw_batch_1([_conv(f"s{i}") for i in range(40)], seed=5, exclude={"s0"}, min_traces=3, k=2)
    assert {k: batch[k] for k in ("id", "final_check", "seed", "excluded")} == {
        "id": "batch-1", "final_check": False, "seed": 5, "excluded": ["s0"],
    }


# -- batch 2 ------------------------------------------------------------------


def _roles() -> list[dict]:
    return [_conv(f"{r}{i}", turns=1 + i % 2, role=r) for r in ("shopper", "merchant", "support") for i in range(15)]


def test_draw_batch_2_reaches_the_minimum_for_each_role():
    batch = draw_batch_2(_roles(), seed=5, exclude=set(), min_traces=10)
    per_role = {r: sum(len(i["trace_ids"]) for i in batch["items"] if i["reason"] == f"role {r}") for r in ("shopper", "merchant", "support")}
    assert all(n >= 10 for n in per_role.values())


def test_draw_batch_2_skips_excluded_sessions():
    batch = draw_batch_2(_roles(), seed=5, exclude={"merchant0", "support3"}, min_traces=10)
    assert {"merchant0", "support3"}.isdisjoint(i["session_id"] for i in batch["items"])


def test_draw_batch_2_is_reproducible_for_a_seed():
    first = draw_batch_2(_roles(), seed=5, exclude=set(), min_traces=10)
    second = draw_batch_2(list(reversed(_roles())), seed=5, exclude=set(), min_traces=10)
    assert first["items"] == second["items"]


def test_draw_batch_2_records_how_it_was_drawn():
    batch = draw_batch_2(_roles(), seed=5, exclude={"shopper0"}, min_traces=10)
    assert {k: batch[k] for k in ("id", "final_check", "seed", "excluded")} == {
        "id": "batch-2", "final_check": False, "seed": 5, "excluded": ["shopper0"],
    }


# -- batch 4 ------------------------------------------------------------------


def test_draw_batch_4_reaches_fifteen_traces():
    batch = draw_batch_4(_roles(), seed=5, exclude=set())
    assert sum(len(i["trace_ids"]) for i in batch["items"]) >= 15


def test_draw_batch_4_is_the_final_check():
    assert draw_batch_4(_roles(), seed=5, exclude=set())["final_check"] is True


def test_draw_batch_4_skips_excluded_sessions():
    batch = draw_batch_4(_roles(), seed=5, exclude={"shopper0", "merchant1"})
    assert {"shopper0", "merchant1"}.isdisjoint(i["session_id"] for i in batch["items"])


def test_draw_batch_4_records_how_it_was_drawn():
    batch = draw_batch_4(_roles(), seed=5, exclude={"shopper0"})
    assert {k: batch[k] for k in ("id", "seed", "excluded")} == {"id": "batch-4", "seed": 5, "excluded": ["shopper0"]}


def test_draw_batch_4_can_draw_an_extra_final_check_batch():
    batch = draw_batch_4(_roles(), seed=5, exclude=set(), batch_id="batch-5")
    assert (batch["id"], batch["final_check"]) == ("batch-5", True)


def test_manifest_sessions_lists_every_batched_session(tmp_path):
    store = ReviewStore(tmp_path)
    add_batch(store, {"id": "batch-1", "items": [{"session_id": "s0", "trace_ids": ["t"]}]})
    assert manifest_sessions(store) == {"s0"}


# -- exclusions -----------------------------------------------------------------


def test_resolve_exclude_maps_scenario_ids_to_session_ids():
    convs = [{"session_id": "hex1", "scenario_id": "support-0001"}, {"session_id": "hex2", "scenario_id": "support-0002"}]
    assert resolve_exclude(convs, {"support-0002"}) == {"hex2"}


def test_resolve_exclude_rejects_an_unknown_id():
    with pytest.raises(ValueError, match="support-9999"):
        resolve_exclude([{"session_id": "hex1", "scenario_id": "support-0001"}], {"support-9999"})


# -- saving -------------------------------------------------------------------


def test_add_batch_appends_to_the_manifest(tmp_path):
    store = ReviewStore(tmp_path)
    add_batch(store, {"id": "batch-1", "items": [{"session_id": "s0", "trace_ids": ["t"]}]})
    assert [b["id"] for b in store.manifest()["batches"]] == ["batch-1"]


def test_add_batch_refuses_an_existing_batch_id(tmp_path):
    store = ReviewStore(tmp_path)
    add_batch(store, {"id": "batch-1", "items": []})
    with pytest.raises(ValueError, match="already"):
        add_batch(store, {"id": "batch-1", "items": []})
