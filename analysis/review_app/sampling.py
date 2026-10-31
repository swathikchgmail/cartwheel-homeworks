"""Part B batch selection over whole conversations.

Every turn of a picked conversation counts toward a batch, so each picker
adds conversations until the batch reaches its trace minimum. Clustering
uses conversation shape only (turns, tool calls, errors, words), never
expected outcomes, and reuses the k-means in ``analysis.helpers.selection``.

Run: uv run python -m analysis.review_app.sampling --exclude support-0033,...
"""

from __future__ import annotations

import argparse
import math
import random
from pathlib import Path
from typing import Any

from analysis.helpers.selection import _kmeans, _standardize
from analysis.review_app.store import ReviewStore

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
DEFAULT_SEED = 2026102701


def conversation_features(conv: dict[str, Any]) -> list[float]:
    """Turns, tool calls, distinct tools, tool errors, user words, reply words."""
    turns = conv["turns"]
    steps = [s for t in turns for s in t["steps"]]
    return [
        float(len(turns)),
        float(len(steps)),
        float(len({s["name"] for s in steps})),
        float(sum(1 for s in steps if not s["ok"])),
        float(sum(len(t["user_text"].split()) for t in turns)),
        float(sum(len(t["reply_text"].split()) for t in turns)),
    ]


def _item(conv: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "session_id": conv["session_id"],
        "scenario_id": conv["scenario_id"],
        "trace_ids": [t["trace_id"] for t in conv["turns"]],
        "reason": reason,
    }


def _pool(convs: list[dict[str, Any]], exclude: set[str]) -> list[dict[str, Any]]:
    """Sorted by session id so a seed gives the same draw whatever the input order."""
    return sorted((c for c in convs if c["session_id"] not in exclude), key=lambda c: c["session_id"])


def uniform_items(convs: list[dict[str, Any]], min_traces: int, seed: int, exclude: set[str]) -> list[dict[str, Any]]:
    """Shuffle once, then take conversations until the trace minimum is met.
    Time O(n log n), space O(n)."""
    pool = _pool(convs, exclude)
    random.Random(seed).shuffle(pool)
    items: list[dict[str, Any]] = []
    traces = 0
    for conv in pool:
        if traces >= min_traces:
            break
        items.append(_item(conv, "uniform pick"))
        traces += len(conv["turns"])
    return items


def _ranked_clusters(pool: list[dict[str, Any]], k: int, seed: int) -> list[list[dict[str, Any]]]:
    """Clusters biggest first; members ordered nearest to their centroid first.
    Time O(iters * n * k * d) for k-means plus O(n log n) for ordering."""
    vectors = _standardize([conversation_features(c) for c in pool])
    groups: dict[int, list[int]] = {}
    for i, c in enumerate(_kmeans(vectors, k=k, seed=seed)):
        groups.setdefault(c, []).append(i)
    ranked = []
    for members in groups.values():
        centre = [sum(vectors[i][d] for i in members) / len(members) for d in range(len(vectors[0]))]
        members.sort(key=lambda i: (math.dist(vectors[i], centre), pool[i]["session_id"]))
        ranked.append([pool[i] for i in members])
    ranked.sort(key=lambda m: (-len(m), m[0]["session_id"]))
    return ranked


def cluster_items(convs: list[dict[str, Any]], min_traces: int, k: int, seed: int, exclude: set[str]) -> list[dict[str, Any]]:
    """One representative per cluster per round, biggest cluster first, until
    the trace minimum is met."""
    pool = _pool(convs, exclude)
    if not pool:
        return []
    clusters = _ranked_clusters(pool, k, seed)
    items: list[dict[str, Any]] = []
    traces = 0
    depth = 0
    while traces < min_traces and any(depth < len(m) for m in clusters):
        for rank, members in enumerate(clusters, start=1):
            if traces >= min_traces:
                break
            if depth < len(members):
                items.append(_item(members[depth], f"cluster {rank} ({len(members)} conversations) representative"))
                traces += len(members[depth]["turns"])
        depth += 1
    return items


def draw_batch_1(
    convs: list[dict[str, Any]], seed: int, exclude: set[str], min_traces: int = 15, k: int = 10
) -> dict[str, Any]:
    """Uniform picks first, then cluster picks from what is left."""
    uniform = uniform_items(convs, min_traces, seed, exclude)
    taken = exclude | {i["session_id"] for i in uniform}
    cluster = cluster_items(convs, min_traces, k, seed, taken)
    return {
        "id": "batch-1",
        "label": "Batch 1: uniform + cluster",
        "method": f"{min_traces}+ traces uniform (seeded shuffle), then {min_traces}+ traces from {k} k-means clusters on conversation shape, nearest to centre first",
        "final_check": False,
        "seed": seed,
        "excluded": sorted(exclude),
        "items": uniform + cluster,
    }


ROLES = ("shopper", "merchant", "support")


def draw_batch_2(
    convs: list[dict[str, Any]], seed: int, exclude: set[str], min_traces: int = 10
) -> dict[str, Any]:
    """Spread across role: a seeded uniform draw within each role until it
    reaches the trace minimum. Time O(n log n), space O(n)."""
    items: list[dict[str, Any]] = []
    for role in ROLES:
        picked = uniform_items([c for c in convs if c["role"] == role], min_traces, seed, exclude)
        items += [{**i, "reason": f"role {role}"} for i in picked]
    return {
        "id": "batch-2",
        "label": "Batch 2: spread across role",
        "method": f"{min_traces}+ traces per role ({', '.join(ROLES)}), seeded shuffle within each role",
        "final_check": False,
        "seed": seed,
        "excluded": sorted(exclude),
        "items": items,
    }


def draw_batch_4(
    convs: list[dict[str, Any]], seed: int, exclude: set[str], min_traces: int = 15,
    batch_id: str = "batch-4",
) -> dict[str, Any]:
    """Final uniform check after the taxonomy is drafted; batch_id names an
    extra check when the previous one surfaced new modes. Time O(n log n)."""
    return {
        "id": batch_id,
        "label": f"{batch_id.replace('-', ' ').capitalize()}: final uniform check",
        "method": f"{min_traces}+ traces uniform (seeded shuffle) from conversations not in any earlier batch",
        "final_check": True,
        "seed": seed,
        "excluded": sorted(exclude),
        "items": uniform_items(convs, min_traces, seed, exclude),
    }


def manifest_sessions(store: ReviewStore) -> set[str]:
    return {i["session_id"] for b in store.manifest()["batches"] for i in b["items"]}


def resolve_exclude(convs: list[dict[str, Any]], ids: set[str]) -> set[str]:
    """Map scenario ids (or session ids) to session ids; unknown ids fail fast."""
    found = {c["session_id"]: c for c in convs if c["session_id"] in ids or c["scenario_id"] in ids}
    matched = {c["session_id"] for c in found.values()} | {c["scenario_id"] for c in found.values()}
    unknown = sorted(ids - matched)
    if unknown:
        raise ValueError(f"unknown ids to exclude: {', '.join(unknown)}")
    return set(found)


def add_batch(store: ReviewStore, batch: dict[str, Any]) -> None:
    manifest = store.manifest()
    if any(b["id"] == batch["id"] for b in manifest["batches"]):
        raise ValueError(f"batch {batch['id']} is already in the manifest")
    manifest["batches"].append(batch)
    store.save_manifest(manifest)


def override_stores() -> set[int]:
    """Stores whose own policy page sets a return window."""
    import sqlite3

    from agent.config import db_path

    with sqlite3.connect(db_path()) as db:
        return {r[0] for r in db.execute("SELECT id FROM stores WHERE return_window_days_override IS NOT NULL")}


def main() -> None:
    from analysis.review_app import snapshot
    from analysis.review_app.conversations import build_conversations
    from analysis.review_app.search import draw_batch_3, draw_store_policy_round_2, extend_batch

    parser = argparse.ArgumentParser(description="Draw an HW4 batch into sample_manifest.json")
    parser.add_argument("--batch", type=int, choices=(1, 2, 3, 4, 5), default=1)
    parser.add_argument("--round", type=int, choices=(1, 2), default=1, help="batch 3 only: 2 = repeat store-policy search")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--exclude", default="", help="comma-separated session ids to leave out")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    args = parser.parse_args()
    store = ReviewStore(args.state_dir)
    conversations = build_conversations(snapshot.load_snapshot(), snapshot.load_scenarios())
    exclude = resolve_exclude(conversations, {s.strip() for s in args.exclude.split(",") if s.strip()})
    if args.batch == 1:
        batch = draw_batch_1(conversations, args.seed, exclude)
    elif args.batch == 2:
        batch = draw_batch_2(conversations, args.seed, exclude | manifest_sessions(store))
    elif args.batch in (4, 5):
        batch = draw_batch_4(conversations, args.seed, exclude | manifest_sessions(store), batch_id=f"batch-{args.batch}")
    elif args.round == 2:
        items = draw_store_policy_round_2(conversations, override_stores(), args.seed, exclude | manifest_sessions(store))
        extend_batch(store, "batch-3", items)
        batch = {"items": items}
    else:
        batch = draw_batch_3(conversations, override_stores(), args.seed, exclude | manifest_sessions(store))
    if args.round == 1:
        add_batch(store, batch)
    for item in batch["items"]:
        print(f"{item['scenario_id']}\t{len(item['trace_ids'])} trace(s)\t{item['reason']}")


if __name__ == "__main__":
    main()
