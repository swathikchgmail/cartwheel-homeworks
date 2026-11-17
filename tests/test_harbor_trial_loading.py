"""Trial loading for Harbor jobs that store each trial in its own folder.

Harbor 0.23.0 writes a job-level result.json without ``trial_results`` and one
``<trial>/result.json`` per trial. These tests pin the fallback that reads those
folders in start-time order, and the unchanged path for ``trial_results``.
"""

from __future__ import annotations

import json
from pathlib import Path

from harbor_adapter.analysis import analyze_capability_job
from harbor_adapter.summary import load_trial_results, summarize_job


def _trial(case_id: str, name: str, started_at: str, reward: float | None) -> dict:
    return {
        "task_name": f"cartwheel/evals__{case_id}",
        "trial_name": name,
        "started_at": started_at,
        "verifier_result": None if reward is None else {"rewards": {"reward": reward}},
        "exception_info": None if reward is not None else {"exception_type": "RuntimeError"},
        "agent_info": {"model_info": {"name": "example-model", "provider": None}},
    }


def _write_per_trial_job(job: Path, trials: list[dict]) -> None:
    job.mkdir()
    (job / "result.json").write_text(json.dumps({"n_total_trials": len(trials)}))
    for trial in trials:
        folder = job / trial["trial_name"]
        folder.mkdir()
        (folder / "result.json").write_text(json.dumps(trial))


def _write_case(path: Path, case_id: str) -> None:
    case = {
        "id": case_id,
        "mode": "response_quality",
        "input": {"role": "shopper", "user_id": 1, "message": "hello"},
        "initial_state": {"world": "reseed", "fixture": None},
        "expected": {"checks": [{"check": "reply_asks_question"}]},
    }
    path.write_text(json.dumps(case) + "\n")


def test_load_trial_results_keeps_job_level_trial_results(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    trials = [_trial("e-1", "b", "2026-01-01T00:00:02Z", 1), _trial("e-1", "a", "2026-01-01T00:00:01Z", 0)]
    (job / "result.json").write_text(json.dumps({"trial_results": trials}))

    loaded, order = load_trial_results(job)

    assert ([t["trial_name"] for t in loaded], order) == (["b", "a"], "result.json trial_results order")


def test_load_trial_results_reads_trial_folders_by_start_time(tmp_path: Path) -> None:
    job = tmp_path / "job"
    _write_per_trial_job(job, [
        _trial("e-1", "late", "2026-01-01T00:00:03Z", 1),
        _trial("e-1", "early", "2026-01-01T00:00:01Z", 0),
        _trial("e-1", "middle", "2026-01-01T00:00:02Z", 1),
    ])

    loaded, order = load_trial_results(job)

    assert ([t["trial_name"] for t in loaded], order) == (
        ["early", "middle", "late"], "trial result.json started_at order")


def test_load_trial_results_skips_folders_without_a_result(tmp_path: Path) -> None:
    job = tmp_path / "job"
    _write_per_trial_job(job, [_trial("e-1", "only", "2026-01-01T00:00:01Z", 1)])
    (job / "logs").mkdir()

    loaded, _ = load_trial_results(job)

    assert [t["trial_name"] for t in loaded] == ["only"]


def test_baseline_summary_classifies_per_trial_job(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_case(cases_path, "e-501")
    job = tmp_path / "job"
    _write_per_trial_job(job, [
        _trial("e-501", f"t{i}", f"2026-01-01T00:00:0{i}Z", reward)
        for i, reward in enumerate([1, 1, 0, 1, 1])
    ])

    markdown, _ = summarize_job(job, cases_path=cases_path, expected_attempts=5, classify=True)

    assert '| `e-501` | 4 | 5 | `kind: "capability"`, `baseline_pass_rate: 0.8` |' in markdown


def test_baseline_summary_flags_an_errored_per_trial_job(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_case(cases_path, "e-502")
    job = tmp_path / "job"
    _write_per_trial_job(job, [
        _trial("e-502", f"t{i}", f"2026-01-01T00:00:0{i}Z", reward)
        for i, reward in enumerate([1, 1, None, 1, 1])
    ])

    markdown, passed = summarize_job(job, cases_path=cases_path, expected_attempts=5, classify=True)

    assert (passed, "do not classify" in markdown) == (False, True)


def test_capability_analysis_records_per_trial_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("harbor_adapter.analysis.pass_at_k", lambda n, c, k: 0.0)
    job = tmp_path / "job"
    _write_per_trial_job(job, [
        _trial("e-601", f"t{i:02d}", f"2026-01-01T00:00:{i:02d}Z", i % 2)
        for i in range(15)
    ])

    result = analyze_capability_job(job, "e-601")

    assert (result["rewards"][:3], result["trial_order"]) == (
        [0, 1, 0], "trial result.json started_at order")
