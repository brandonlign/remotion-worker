#!/usr/bin/env python3
"""GhostStream recovery gate v2 using stable parent clusters and untouched seasons.

The v1 gate showed a transparent failure mode: major showers were split into many
small, nearly pure HDBSCAN leaf clusters. This preregistered correction switches
to EOM parent-cluster selection. The frozen final test uses three shower seasons
that were not used in v1 development or evaluation.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN

from run_gate import Score, load_window, prepare

DEVELOPMENT = {
    "Quadrantids": ("2025-01-02", "2025-01-05", "QUA"),
    "Perseids": ("2025-08-10", "2025-08-14", "PER"),
    "Orionids": ("2025-10-19", "2025-10-23", "ORI"),
    "Leonids": ("2025-11-15", "2025-11-19", "LEO"),
    "Geminids": ("2025-12-11", "2025-12-15", "GEM"),
}
UNTOUCHED = {
    "Lyrids": ("2025-04-19", "2025-04-24", "LYR"),
    "Eta_Aquariids": ("2025-05-03", "2025-05-08", "ETA"),
    "Southern_Delta_Aquariids": ("2025-07-27", "2025-08-01", "SDA"),
}
SETTING = {
    "min_cluster_size": 40,
    "min_samples": 10,
    "scales": [4.0, 4.0, 3.0, 3.0],
    "cluster_selection_method": "eom",
}
SEED = 20260731


def target_score(labels: pd.Series, clusters: np.ndarray, target: str) -> Score:
    truth = labels.to_numpy(str)
    actual = truth == target
    total = int(actual.sum())
    best: Score | None = None
    for cluster in [int(value) for value in np.unique(clusters) if int(value) >= 0]:
        predicted = clusters == cluster
        true_positive = int(np.sum(actual & predicted))
        if true_positive == 0:
            continue
        size = int(predicted.sum())
        precision = true_positive / size
        recall = true_positive / total if total else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        candidate = Score(
            target,
            total,
            cluster,
            size,
            precision,
            recall,
            f1,
            total >= 40 and precision >= 0.35 and recall >= 0.35 and f1 >= 0.35,
        )
        if best is None or candidate.f1 > best.f1:
            best = candidate
    return best or Score(target, total, None, 0, 0.0, 0.0, 0.0, False)


def cluster(features: np.ndarray, labels: pd.Series, target: str) -> dict[str, Any]:
    model = HDBSCAN(
        min_cluster_size=SETTING["min_cluster_size"],
        min_samples=SETTING["min_samples"],
        cluster_selection_method=SETTING["cluster_selection_method"],
        leaf_size=60,
        n_jobs=-1,
    )
    assignments = model.fit_predict(features / np.asarray(SETTING["scales"])[None, :])
    sizes = pd.Series(assignments[assignments >= 0]).value_counts()
    result = target_score(labels, assignments, target)
    return {
        "target": target,
        "score": asdict(result),
        "cluster_count": int(len(sizes)),
        "noise_fraction": float(np.mean(assignments < 0)),
        "largest_cluster_fraction": float(sizes.max() / len(assignments)) if len(sizes) else 0.0,
    }


def execute(windows: dict[str, tuple[str, str, str]], seed_offset: int) -> tuple[dict[str, Any], dict[str, Any]]:
    results: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for index, (name, (start, end, target)) in enumerate(windows.items()):
        frame, download = load_window(name, start, end)
        data, features, prep = prepare(frame, SEED + seed_offset + index)
        result = cluster(features, data["label"], target)
        results[name] = result
        metadata[name] = {**download, **prep, "frozen_target": target}
        score = result["score"]
        print(
            f"{name}: target={target} n={score['true_count']} "
            f"precision={score['precision']:.3f} recall={score['recall']:.3f} "
            f"F1={score['f1']:.3f} recovered={score['recovered']} "
            f"noise={result['noise_fraction']:.1%}",
            flush=True,
        )
    return results, metadata


def main() -> int:
    out = Path("ghoststream_results_v2")
    out.mkdir(exist_ok=True)

    development, development_meta = execute(DEVELOPMENT, 0)
    untouched, untouched_meta = execute(UNTOUCHED, 100)

    recovered = sum(bool(item["score"]["recovered"]) for item in untouched.values())
    eligible = sum(int(item["score"]["true_count"] >= 40) for item in untouched.values())
    largest = max((item["largest_cluster_fraction"] for item in untouched.values()), default=1.0)
    if eligible < 3:
        verdict = "INCONCLUSIVE_MISSING_UNTOUCHED_CONTROLS"
    elif largest > 0.30:
        verdict = "NO_GO_DEGENERATE_PARENT_CLUSTER"
    elif recovered == eligible:
        verdict = "RECOVERY_GATE_PASS"
    else:
        verdict = "RECOVERY_GATE_FAIL"

    summary = {
        "pilot": "GhostStream",
        "stage": "known_shower_recovery_gate_v2",
        "reason_for_single_correction": "v1 leaf clustering fragmented major showers into small high-precision clusters",
        "labels_hidden_during_clustering": True,
        "setting_frozen_before_untouched_test": SETTING,
        "development_windows": DEVELOPMENT,
        "untouched_windows": UNTOUCHED,
        "frozen_recovery_rule": {
            "minimum_true_members": 40,
            "minimum_precision": 0.35,
            "minimum_recall": 0.35,
            "minimum_f1": 0.35,
        },
        "frozen_pass_rule": {
            "all_three_named_untouched_showers_recovered": True,
            "maximum_largest_cluster_fraction": 0.30,
        },
        "untouched_eligible": eligible,
        "untouched_recovered": recovered,
        "untouched_largest_cluster_fraction": largest,
        "verdict": verdict,
        "development": development,
        "untouched": untouched,
        "metadata": {"development": development_meta, "untouched": untouched_meta},
    }
    metrics = out / "ghoststream_recovery_gate_v2.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = [
        "# GhostStream known-shower recovery gate v2",
        "",
        f"**Verdict:** `{verdict}`",
        "",
        f"- Untouched named showers recovered: **{recovered}/{eligible}**",
        f"- Largest untouched cluster fraction: **{largest:.1%}**",
        f"- Frozen setting: `{SETTING}`",
        "",
        "## Untouched seasons",
        "",
    ]
    for name, item in untouched.items():
        score = item["score"]
        lines.append(
            f"- **{name} (`{score['shower']}`):** n={score['true_count']}, "
            f"precision={score['precision']:.3f}, recall={score['recall']:.3f}, "
            f"F1={score['f1']:.3f}, recovered={score['recovered']}"
        )
    lines += [
        "",
        "The v2 correction was chosen from the v1 fragmentation pattern. None of the three final seasons appeared in v1.",
        "Passing authorizes null-catalog and weak-stream injection tests; it does not claim a discovery.",
        "",
    ]
    report = out / "GHOSTSTREAM_RECOVERY_GATE_V2.md"
    report.write_text("\n".join(lines))

    print(f"\nVerdict: {verdict}")
    print(f"Untouched named showers recovered: {recovered}/{eligible}")
    print(f"Largest untouched cluster fraction: {largest:.6f}")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
