"""Load the review data: a local snapshot of live Langfuse traces + HW3 scenarios.

Fetching every trace from Langfuse takes about a minute, so the app reads a
snapshot file and refreshes it only on request. Trace identifiers stay the
Langfuse identifiers, so scores written later still join to the right trace.
The snapshot is a local cache and is not committed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_SNAPSHOT = HERE / "data" / "traces.json"
DEFAULT_SCENARIOS = REPO / "scenarios" / "support_scenarios.jsonl"
_REFERENCE_KEYS = ("scenario_group", "data_quality_case_id", "tuple", "expected")


def refresh_snapshot(path: Path = DEFAULT_SNAPSHOT, prefix: str = "support-") -> int:
    """Pull scenario traces from live Langfuse (read-only) and save them."""
    from analysis.helpers import langfuse_io

    traces = [
        t for t in langfuse_io.fetch_traces(limit=5000)
        if str(t["meta"].get("scenario_id") or "").startswith(prefix)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(traces, ensure_ascii=False, default=str), encoding="utf-8")
    return len(traces)


def load_snapshot(path: Path = DEFAULT_SNAPSHOT) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"No trace snapshot at {path}. Run: python -m analysis.review_app.server --refresh"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_scenarios(path: Path = DEFAULT_SCENARIOS) -> dict[str, dict[str, Any]]:
    """Scenario id -> the reference fields shown behind "Show reference"."""
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["id"]] = {k: record.get(k) for k in _REFERENCE_KEYS}
    return out
