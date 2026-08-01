#!/usr/bin/env python3
"""Prospective independent-year correction for the GhostStream control gate.

The recovered v2 gate applied a 30% ceiling to the largest cluster, including
the real target-shower cluster. That rule is mathematically infeasible whenever
the target shower itself exceeds 30% of the sample. This correction preserves
the exact v2 HDBSCAN setting, recovery thresholds, 30% threshold, and label
hiding during clustering. It applies the 30% ceiling only to the largest cluster
other than the selected target-shower cluster and evaluates untouched 2024
seasons.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN

from run_gate import load_window, prepare

SOURCE_COMMIT = "4175e5187fcc6faf3d1befb099a9e35be96850f2"
SETTING = {
    "min_cluster_size": 40,
    "min_samples": 10,
    "scales": [4.0, 4.0, 3.0, 3.0],
    "cluster_selection_method": "eom",
}
RECOVERY_RULE = {
    "minimum_true_members": 40,
    "minimum_precision": 0.35,
    "minimum_recall": 0.35,
    "minimum_f1": 0.35,
}
MAXIMUM_LARGEST_NON_TARGET_CLUSTER_FRACTION = 0.30
HOLDOUT = {
    "Lyrids_2024": ("2024-04-19", "2024-04-24", "LYR"),
    "Eta_Aquariids_2024": ("2024-05-03", "2024-05-08", "ETA"),
    "Southern_Delta_Aquariids_2024": ("2024-07-27", "2024-08-01", "SDA"),
}
SEED = 20260801
OUT = Path("ghoststream_method_controls_v3")


def score_target(labels: pd.Series, assignments: np.ndarray, target: str) -> dict[str, Any]:
    truth = labels.to_numpy(str)
    actual = truth == target
    true_count = int(actual.sum())
    best: dict[str, Any] | None = None
    for cluster_id in [int(value) for value in np.unique(assignments) if int(value) >= 0]:
        predicted = assignments == cluster_id
        true_positive = int(np.sum(actual & predicted))
        if true_positive == 0:
            continue
        cluster_size = int(predicted.sum())
        precision = true_positive / cluster_size
        recall = true_positive / true_count if true_count else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        recovered = (
            true_count >= RECOVERY_RULE["minimum_true_members"]
            and precision >= RECOVERY_RULE["minimum_precision"]
            and recall >= RECOVERY_RULE["minimum_recall"]
            and f1 >= RECOVERY_RULE["minimum_f1"]
        )
        candidate = {
            "target": target,
            "true_count": true_count,
            "cluster": cluster_id,
            "cluster_size": cluster_size,
            "true_positive": true_positive,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "recovered": recovered,
        }
        if best is None or candidate["f1"] > best["f1"]:
            best = candidate
    return best or {
        "target": target,
        "true_count": true_count,
        "cluster": None,
        "cluster_size": 0,
        "true_positive": 0,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "recovered": False,
    }


def run_control(name: str, start: str, end: str, target: str, seed: int) -> dict[str, Any]:
    frame, download = load_window(name, start, end)
    data, features, prep = prepare(frame, seed)
    assignments = HDBSCAN(
        min_cluster_size=SETTING["min_cluster_size"],
        min_samples=SETTING["min_samples"],
        cluster_selection_method=SETTING["cluster_selection_method"],
        leaf_size=60,
        n_jobs=-1,
    ).fit_predict(features / np.asarray(SETTING["scales"])[None, :])
    score = score_target(data["label"], assignments, target)
    sizes = {
        int(cluster_id): int(np.sum(assignments == cluster_id))
        for cluster_id in np.unique(assignments)
        if int(cluster_id) >= 0
    }
    target_cluster = score["cluster"]
    non_target_sizes = [
        size for cluster_id, size in sizes.items()
        if target_cluster is None or cluster_id != int(target_cluster)
    ]
    sampled_rows = int(len(assignments))
    largest_non_target_size = max(non_target_sizes, default=0)
    largest_non_target_fraction = largest_non_target_size / sampled_rows if sampled_rows else 1.0
    target_cluster_fraction = score["cluster_size"] / sampled_rows if sampled_rows else 0.0
    non_target_pass = largest_non_target_fraction <= MAXIMUM_LARGEST_NON_TARGET_CLUSTER_FRACTION
    passed = bool(score["recovered"] and non_target_pass)
    result = {
        "name": name,
        "start": start,
        "end": end,
        "target": target,
        "labels_hidden_during_clustering": True,
        "sampled_rows": sampled_rows,
        "target_prevalence": score["true_count"] / sampled_rows if sampled_rows else 0.0,
        "score": score,
        "cluster_count": len(sizes),
        "noise_fraction": float(np.mean(assignments < 0)),
        "target_cluster_fraction": target_cluster_fraction,
        "largest_non_target_cluster_size": largest_non_target_size,
        "largest_non_target_cluster_fraction": largest_non_target_fraction,
        "non_target_degeneracy_gate_passed": non_target_pass,
        "passed": passed,
        "download_and_preparation": {**download, **prep},
    }
    print(
        f"{name}: n={score['true_count']} precision={score['precision']:.3f} "
        f"recall={score['recall']:.3f} F1={score['f1']:.3f} "
        f"target_fraction={target_cluster_fraction:.3f} "
        f"largest_non_target={largest_non_target_fraction:.3f} passed={passed}",
        flush=True,
    )
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {
        name: run_control(name, start, end, target, SEED + index)
        for index, (name, (start, end, target)) in enumerate(HOLDOUT.items())
    }
    eligible = sum(int(item["score"]["true_count"] >= RECOVERY_RULE["minimum_true_members"]) for item in results.values())
    recovered = sum(int(item["score"]["recovered"]) for item in results.values())
    non_target_passes = sum(int(item["non_target_degeneracy_gate_passed"]) for item in results.values())
    passed = eligible == 3 and recovered == 3 and non_target_passes == 3
    verdict = "CORRECTED_INDEPENDENT_YEAR_CONTROL_PASS" if passed else "CORRECTED_INDEPENDENT_YEAR_CONTROL_FAIL"
    evidence = {
        "status": verdict,
        "source_commit": SOURCE_COMMIT,
        "correction_frozen_before_2024_holdout_run": True,
        "setting_unchanged_from_v2": SETTING,
        "recovery_rule_unchanged_from_v2": RECOVERY_RULE,
        "corrected_pass_rule": {
            "all_three_independent_year_controls_recovered": True,
            "maximum_largest_non_target_cluster_fraction": MAXIMUM_LARGEST_NON_TARGET_CLUSTER_FRACTION,
        },
        "holdout_windows": HOLDOUT,
        "seed": SEED,
        "eligible_controls": eligible,
        "recovered_controls": recovered,
        "non_target_degeneracy_passes": non_target_passes,
        "passed": passed,
        "controls": results,
    }
    (OUT / "method_controls_v3.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    lines = [
        "# GhostStream corrected independent-year method controls", "",
        f"**Verdict:** `{verdict}`", "",
        "The historical v2 no-go remains preserved. This prospective correction "
        "uses independent 2024 seasons and applies the original 30% ceiling only "
        "to non-target clusters.", "",
    ]
    for name, item in results.items():
        score = item["score"]
        lines.append(
            f"- **{name}:** n={score['true_count']}, precision={score['precision']:.3f}, "
            f"recall={score['recall']:.3f}, F1={score['f1']:.3f}, "
            f"largest non-target={item['largest_non_target_cluster_fraction']:.3f}, "
            f"passed={item['passed']}"
        )
    (OUT / "METHOD_CONTROLS_V3.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if passed else 3


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
