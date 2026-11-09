"""HW5: prepare judge inputs and split labels for one failure mode.

    uv run python -m analysis.run_judges prepare   # labels export + judge inputs
    uv run python -m analysis.run_judges split     # 20/40/40 split, run once
    uv run --env-file .env python -m analysis.run_judges dev analysis/prompts/<mode>-vN.txt
    uv run --env-file .env python -m analysis.run_judges resume <judge_id>   # after an interruption

One record per labeled conversation. A Fail conversation is represented by its
first Fail turn; a Pass conversation by its hardest Pass turn (a reply that
cites a policy id or states a policy-like number), else its last labeled turn.
Each record holds that turn and every earlier turn, with tool calls and
results, and nothing else: no labels, notes, scenario ids, or session ids.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from analysis.helpers import _state, freeze_judge, judge_alignment, register_judge, run_judge, split_labels

MODE = "policy_not_cited"
JUDGE_MODEL = "gpt-4o-mini"
ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "report"
TRACE_EXPORT = ROOT / "review_app" / "data" / "traces.json"
INPUTS_PATH = ROOT / "state" / "hw5_trace_inputs.json"
HW4_LABELS = ROOT / "state" / "labels" / f"{MODE}.jsonl"
HW5_LABELS = ROOT / "state" / "hw5_labels" / f"{MODE}.jsonl"

_CITATION = re.compile(r"\b(?:cw-[a-z-]+|store-[a-z-]+-policy)\b")
_POLICY_NUMBER = re.compile(
    r"\b\d+\s*(?:(?:-|–|to)\s*\d+\s*)?(?:business days|days|hours)\b|\d+\s*%|\$100\b", re.I)


# -- pure selection and formatting --------------------------------------------

def live_labels(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Current HW4 label per trace (1 = failure present); superseded rows drop out."""
    return {r["trace_id"]: r for r in rows if not r.get("superseded_by")}


def group_turns(traces: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Traces grouped by conversation, each list in turn order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for trace in traces:
        groups.setdefault(trace["meta"]["session_id"], []).append(trace)
    return {sid: sorted(turns, key=lambda t: t["timestamp"]) for sid, turns in groups.items()}


def reply_text(trace: dict[str, Any]) -> str:
    return "\n".join(p["content"] for m in trace["output"] for p in m["parts"] if p.get("type") == "text")


def difficulty(text: str) -> int:
    """2 if the reply cites a policy id, +1 if it states a policy-like number."""
    return 2 * bool(_CITATION.search(text)) + bool(_POLICY_NUMBER.search(text))


def choose_turn(turns: list[dict[str, Any]], labels: dict[str, dict[str, Any]]) -> int | None:
    """Index of the turn that represents this conversation, or None if unlabeled."""
    labeled = [i for i, t in enumerate(turns) if t["id"] in labels]
    if not labeled:
        return None
    fails = [i for i in labeled if labels[turns[i]["id"]]["label"] == 1]
    if fails:
        return fails[0]
    return max(labeled, key=lambda i: (difficulty(reply_text(turns[i])), i))


def tool_line(observation: dict[str, Any]) -> str:
    """One readable line per tool call: name, arguments, result. The shared
    normalizer renders a message's ``content`` only, so the call must live there."""
    args = json.dumps(observation.get("input"), ensure_ascii=False)
    result = json.dumps(observation.get("output"), ensure_ascii=False)
    return f"{observation['name']} {args} -> {result}"


def turn_messages(trace: dict[str, Any]) -> list[dict[str, Any]]:
    """User message, tool calls with results (in call order), then the reply."""
    messages = [{"role": "user", "content": p["content"]}
                for m in trace["input"] for p in m["parts"] if p.get("type") == "text"]
    tools = sorted((o for o in trace.get("observations") or [] if o.get("type") == "TOOL"),
                   key=lambda o: o["start_time"])
    messages += [{"role": "tool", "name": o["name"], "content": tool_line(o)} for o in tools]
    messages.append({"role": "assistant", "content": reply_text(trace)})
    return messages


def build_record(turns: list[dict[str, Any]], index: int) -> dict[str, Any]:
    """Judge input for turns[index]; earlier turns are context. No metadata."""
    trace = [msg for turn in turns[: index + 1] for msg in turn_messages(turn)]
    return {"trace_id": turns[index]["id"], "trace": trace}


def hw5_label(row: dict[str, Any]) -> dict[str, Any]:
    """HW4 row (1 = failure) to HW5 row (1 = Pass, 0 = Fail)."""
    return {"trace_id": row["trace_id"], "mode": MODE, "label": 1 - int(row["label"]),
            "evidence": row.get("evidence", ""), "source": "human", "ts": row["ts"]}


# -- file steps ----------------------------------------------------------------

def prepare_inputs() -> list[dict[str, Any]]:
    """Write the HW5 label export and the judge inputs; return the records."""
    labels = live_labels(_state.read_jsonl(HW4_LABELS))
    groups = group_turns(json.loads(TRACE_EXPORT.read_text()))
    records, exported = [], []
    for turns in groups.values():
        index = choose_turn(turns, labels)
        if index is None:
            continue
        records.append(build_record(turns, index))
        exported.append(hw5_label(labels[turns[index]["id"]]))
    _state.write_jsonl(HW5_LABELS, exported)
    INPUTS_PATH.write_text(json.dumps(records, indent=1))
    passes = sum(r["label"] for r in exported)
    print(f"{len(records)} records -> {INPUTS_PATH.name}; labels: {passes} Pass, {len(exported) - passes} Fail")
    return records


def split_data(mode: str = MODE) -> dict[str, list[str]]:
    """20/40/40 split over the saved inputs (seed 7); prints class counts."""
    records = json.loads(INPUTS_PATH.read_text())
    splits = split_labels(mode, fractions=(0.20, 0.40, 0.40), seed=7, min_per_class=10,
                          eligible_trace_ids=[r["trace_id"] for r in records])
    passes = {r["trace_id"] for r in _state.read_jsonl(HW5_LABELS) if r["label"] == 1}
    for name, ids in splits.items():
        n_pass = sum(tid in passes for tid in ids)
        print(f"{name:5} Pass {n_pass:3}  Fail {len(ids) - n_pass:3}")
    return splits


def run_development(mode: str, prompt_path: str | Path) -> dict[str, Any]:
    """Register a prompt version, judge the dev split, save and return metrics."""
    record = register_judge(mode=mode, prompt_text=Path(prompt_path).read_text(), judge_model=JUDGE_MODEL)
    return evaluate_dev(record["judge_id"], prompt_path)


def evaluate_dev(judge_id: str, prompt_path: str | Path = "") -> dict[str, Any]:
    """Judge the dev split for an already registered judge (cached; resumable)."""
    run_judge(judge_id, split="dev", batch_size=10)
    metrics = {"judge_id": judge_id, "prompt_path": str(prompt_path), "model": JUDGE_MODEL,
               **judge_alignment(judge_id, split="dev")}
    out = REPORT_DIR / f"dev-{judge_id}.json"
    out.write_text(json.dumps(metrics, indent=2))
    print(f"{judge_id}: TPR {metrics['tpr']} {metrics['tpr_interval']}  TNR {metrics['tnr']} "
          f"{metrics['tnr_interval']}  (TP {metrics['tp']} FN {metrics['fn']} TN {metrics['tn']} FP {metrics['fp']}) -> {out.name}")
    return metrics


def run_test(judge_id: str) -> dict[str, Any]:
    """Freeze the chosen judge (once), judge the test split, save and return metrics.
    Resumable: a judge that is already frozen is not frozen again."""
    if _state.read_json(_state.state_path("judges", f"{judge_id}.json"), default={}).get("status") != "frozen":
        freeze_judge(judge_id)
    run_judge(judge_id, split="test", batch_size=10)
    metrics = {"judge_id": judge_id, "model": JUDGE_MODEL, **judge_alignment(judge_id, split="test")}
    passes = {r["trace_id"] for r in _state.read_jsonl(HW5_LABELS) if r["label"] == 1}
    test_ids = _state.read_json(_state.state_path("splits.json"))[MODE]["test"]
    metrics["class_counts"] = {"pass": sum(t in passes for t in test_ids),
                               "fail": sum(t not in passes for t in test_ids)}
    out = REPORT_DIR / f"test-{judge_id}.json"
    out.write_text(json.dumps(metrics, indent=2))
    print(f"{judge_id} TEST: TPR {metrics['tpr']} {metrics['tpr_interval']}  TNR {metrics['tnr']} "
          f"{metrics['tnr_interval']}  (TP {metrics['tp']} FN {metrics['fn']} TN {metrics['tn']} FP {metrics['fp']}) "
          f"classes {metrics['class_counts']} -> {out.name}")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["prepare", "split", "dev", "resume", "test"])
    parser.add_argument("arg", nargs="?", help="dev: prompt file; resume/test: judge id")
    args = parser.parse_args()
    if args.step == "prepare":
        prepare_inputs()
    elif args.step == "split":
        split_data()
    elif args.step == "resume":
        evaluate_dev(args.arg)
    elif args.step == "test":
        run_test(args.arg)
    else:
        run_development(MODE, args.arg or ROOT / "prompts" / f"{MODE}-v0.txt")


if __name__ == "__main__":
    main()
