"""Evaluation framework regression and provenance tests (offline only)."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from aiseoonline_api.evaluation import DATASET, benchmark, load_dataset
from aiseoonline_api.evaluation_history import compare_reports


def test_dataset_provenance_is_stable_and_public_safe() -> None:
    data, fingerprint = load_dataset()
    assert fingerprint == hashlib.sha256(DATASET.read_bytes()).hexdigest()
    assert data["version"] == "seo-evaluation-v1"
    assert data["license"] == "CC0-1.0"
    assert len(data["documents"]) == 6
    assert all(item["url"].startswith("https://example.org/") for item in data["documents"])
    assert all(
        phrase not in DATASET.read_text().lower()
        for phrase in ("sk-proj-", "authorization: bearer", "private_key")
    )


def test_offline_benchmark_runs_real_regression_paths_without_network() -> None:
    data, digest = load_dataset()
    report = benchmark(data, digest, run_at="2026-10-15T12:00:00Z")
    assert report["case_count"] == 18
    assert report["paid_calls"] == 0
    assert report["mode"] == "offline_scripted_fixture"
    assert report["dataset_sha256"] == digest
    assert sum(group["cases"] for group in report["groups"].values()) == 18
    case_ids = {item["id"] for item in report["cases"]}
    assert len(case_ids) == report["case_count"]
    # Deliberately measured blind spot: exact quote checks do not prove
    # entailment of every semantic claim. Never advertise perfect grounding.
    bad = next(row for row in report["cases"] if row["id"] == "rag-semantic-overclaim")
    assert bad["expected"] == "rejected"
    assert bad["observed"] == "accepted"
    assert bad["matched_expectation"] is False
    assert all(
        row["matched_expectation"]
        for row in report["cases"]
        if row["id"] != "rag-semantic-overclaim"
    )


def test_bad_dataset_references_are_rejected(tmp_path: Path) -> None:
    data, _ = load_dataset()
    altered = copy.deepcopy(data)
    altered["retrieval"][0]["semantic_ids"].append("outside-project")
    location = tmp_path / "invalid.json"
    location.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="missing synthetic document"):
        load_dataset(location)


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    data, _ = load_dataset()
    altered = copy.deepcopy(data)
    altered["rag"][0]["id"] = altered["structured"][0]["id"]
    location = tmp_path / "duplicate.json"
    location.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="Duplicate evaluation case"):
        load_dataset(location)


def test_reporting_is_reproducible_for_same_inputs_and_timestamp() -> None:
    data, digest = load_dataset()
    first = benchmark(data, digest, run_at="2026-10-15T12:00:00Z")
    second = benchmark(data, digest, run_at="2026-10-15T12:00:00Z")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_history_compares_observed_measures_not_invented_delta() -> None:
    data, digest = load_dataset()
    old = benchmark(data, digest, run_at="2026-10-15T12:00:00Z")
    now = benchmark(data, digest, run_at="2026-10-15T12:01:00Z")
    changes = compare_reports(old, now)
    assert all(value["delta"] == 0 for value in changes["changes"].values())
    assert changes["baseline_run_at_utc"] == old["run_at_utc"]


def test_history_refuses_cross_dataset_or_mode_comparison() -> None:
    data, digest = load_dataset()
    before = benchmark(data, digest, run_at="2026-10-15T12:00:00Z")
    after = copy.deepcopy(before)
    after["dataset_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="dataset_sha256"):
        compare_reports(before, after)
    after = copy.deepcopy(before)
    after["mode"] = "paid"
    with pytest.raises(ValueError, match="mode"):
        compare_reports(before, after)


def test_published_report_matches_executed_fixture_cases() -> None:
    public_report = Path(__file__).resolve().parents[2] / "web/src/data/benchmarks.json"
    report = json.loads(public_report.read_text())
    assert report["verified"] is True
    assert report["verification"]["run_url"].startswith(
        "https://github.com/bharathumashankar/aiseoonline/actions/runs/"
    )
    assert report["dataset_sha256"] == load_dataset()[1]
    data, digest = load_dataset()
    actual = benchmark(data, digest, run_at=report["run_at_utc"])
    for key in actual:
        assert report[key] == actual[key], key
    assert any(not case["matched_expectation"] for case in report["cases"])
