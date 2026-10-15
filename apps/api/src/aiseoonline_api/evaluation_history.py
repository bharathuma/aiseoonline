"""Compare only compatible, actually recorded evaluation reports."""

import argparse
import json
from pathlib import Path


def compare_reports(previous: dict, current: dict) -> dict:
    for field in ("schema_version", "dataset_version", "dataset_sha256", "mode"):
        if previous.get(field) != current.get(field):
            raise ValueError(f"Cannot compare reports with different {field}")
    old_groups = previous["groups"]
    new_groups = current["groups"]
    if old_groups.keys() != new_groups.keys():
        raise ValueError("Evaluation groups changed")
    changes = {}
    for name in old_groups:
        past, now = old_groups[name], new_groups[name]
        if past["cases"] != now["cases"]:
            raise ValueError(f"Case count changed in group {name}")
        changes[name] = {
            "baseline": past["matched"],
            "candidate": now["matched"],
            "delta": now["matched"] - past["matched"],
            "cases": now["cases"],
        }
    return {
        "dataset_version": current["dataset_version"],
        "baseline_run_at_utc": previous["run_at_utc"],
        "candidate_run_at_utc": current["run_at_utc"],
        "baseline_model": previous["model"],
        "candidate_model": current["model"],
        "baseline_prompt_versions": previous["prompt_versions"],
        "candidate_prompt_versions": current["prompt_versions"],
        "changes": changes,
        "limitations": (
            "This is a paired fixture comparison only; it is not a model superiority test."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare compatible recorded benchmark runs")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    a = json.loads(args.baseline.read_text())
    b = json.loads(args.candidate.read_text())
    print(json.dumps(compare_reports(a, b), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
