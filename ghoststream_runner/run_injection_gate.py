#!/usr/bin/env python3
"""Weak-stream injection and permutation-null gate for GhostStream.

Synthetic stream members are inserted into real GMN sporadic backgrounds. The
clustering receives no labels. Recovery is scored afterward and compared with
99 random label permutations on the exact same clustered dataset.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN

from run_gate import load_window, prepare

BACKGROUNDS = {
    "February": ("2025-02-10", "2025-02-16"),
    "June": ("2025-06-10", "2025-06-16"),
    "September": ("2025-09-10", "2025-09-16"),
}
SIZES = (20, 40, 80)
SEEDS = (11, 29, 47)
MAX_BACKGROUND = 12000
PERMUTATIONS = 99
SCALES = np.asarray([4.0, 4.0, 3.0, 3.0], dtype=float)
# Diffuse but still physically stream-like widths in the four pilot features:
# sun-centered radiant longitude, ecliptic latitude, geocentric speed, solar longitude.
INJECTION_SIGMA = np.asarray([1.2, 0.8, 1.2, 1.2], dtype=float)
MODEL = {
    "min_cluster_size": 15,
    "min_samples": 5,
    "cluster_selection_method": "leaf",
}


def best_score(assignments: np.ndarray, truth: np.ndarray) -> dict[str, Any]:
    positive_count = int(truth.sum())
    best = {"cluster": None, "cluster_size": 0, "true_positive": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0}
    for cluster in [int(value) for value in np.unique(assignments) if int(value) >= 0]:
        predicted = assignments == cluster
        true_positive = int(np.sum(predicted & truth))
        if true_positive == 0:
            continue
        cluster_size = int(predicted.sum())
        precision = true_positive / cluster_size
        recall = true_positive / positive_count if positive_count else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best["f1"]:
            best = {
                "cluster": cluster,
                "cluster_size": cluster_size,
                "true_positive": true_positive,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
    return best


def permutation_p(assignments: np.ndarray, truth: np.ndarray, observed_f1: float,
                  rng: np.random.Generator) -> tuple[float, list[float]]:
    count = int(truth.sum())
    null_f1: list[float] = []
    for _ in range(PERMUTATIONS):
        indices = rng.choice(assignments.size, size=count, replace=False)
        permuted = np.zeros(assignments.size, dtype=bool)
        permuted[indices] = True
        null_f1.append(float(best_score(assignments, permuted)["f1"]))
    p_value = (1 + sum(value >= observed_f1 for value in null_f1)) / (PERMUTATIONS + 1)
    return float(p_value), null_f1


def valid_centers(features: np.ndarray) -> np.ndarray:
    return (
        (np.abs(features[:, 0]) < 170.0)
        & (np.abs(features[:, 1]) < 80.0)
        & (features[:, 2] > 10.0)
        & (features[:, 2] < 70.0)
        & (np.abs(features[:, 3]) < 2.0)
    )


def inject(background: np.ndarray, size: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    candidates = np.flatnonzero(valid_centers(background))
    if candidates.size == 0:
        raise RuntimeError("No valid injection centers")
    center = background[int(rng.choice(candidates))].copy()
    stream = rng.normal(center, INJECTION_SIGMA, size=(size, 4))
    stream[:, 0] = (stream[:, 0] + 180.0) % 360.0 - 180.0
    stream[:, 1] = np.clip(stream[:, 1], -89.0, 89.0)
    stream[:, 2] = np.clip(stream[:, 2], 5.1, 74.9)
    combined = np.vstack([background, stream])
    truth = np.zeros(combined.shape[0], dtype=bool)
    truth[-size:] = True
    return combined, truth, center


def cluster(features: np.ndarray) -> np.ndarray:
    model = HDBSCAN(
        min_cluster_size=MODEL["min_cluster_size"],
        min_samples=MODEL["min_samples"],
        cluster_selection_method=MODEL["cluster_selection_method"],
        leaf_size=60,
        n_jobs=-1,
    )
    return model.fit_predict(features / SCALES[None, :])


def main() -> int:
    output = Path("ghoststream_injection_results")
    output.mkdir(exist_ok=True)
    backgrounds: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] = {}

    for index, (name, window) in enumerate(BACKGROUNDS.items()):
        frame, download = load_window(name, *window)
        data, features, prep = prepare(frame, 900 + index)
        sporadic = data["label"].to_numpy(str) == "SPORADIC"
        features = features[sporadic]
        rng = np.random.default_rng(7000 + index)
        if features.shape[0] > MAX_BACKGROUND:
            indices = rng.choice(features.shape[0], size=MAX_BACKGROUND, replace=False)
            features = features[indices]
        if features.shape[0] < 3000:
            raise RuntimeError(f"Insufficient sporadic background for {name}: {features.shape[0]}")
        backgrounds[name] = features
        metadata[name] = {**download, **prep, "sporadic_background_rows": int(features.shape[0])}
        print(f"{name}: sporadic background={features.shape[0]:,}", flush=True)

    runs: list[dict[str, Any]] = []
    for background_index, (background_name, background) in enumerate(backgrounds.items()):
        for size in SIZES:
            for seed in SEEDS:
                rng = np.random.default_rng(100000 * background_index + 1000 * size + seed)
                combined, truth, center = inject(background, size, rng)
                assignments = cluster(combined)
                score = best_score(assignments, truth)
                p_value, null_f1 = permutation_p(assignments, truth, float(score["f1"]), rng)
                recovered = (
                    score["precision"] >= 0.50
                    and score["recall"] >= 0.50
                    and score["f1"] >= 0.50
                    and p_value <= 0.01
                )
                result = {
                    "background": background_name,
                    "injection_size": size,
                    "seed": seed,
                    "center": center.tolist(),
                    "score": score,
                    "permutation_p": p_value,
                    "null_f1_q95": float(np.percentile(null_f1, 95)),
                    "null_f1_max": float(np.max(null_f1)),
                    "cluster_count": int(len(set(assignments.tolist()) - {-1})),
                    "noise_fraction": float(np.mean(assignments < 0)),
                    "recovered": recovered,
                }
                runs.append(result)
                print(
                    f"{background_name} n={size} seed={seed}: "
                    f"precision={score['precision']:.3f} recall={score['recall']:.3f} "
                    f"F1={score['f1']:.3f} p={p_value:.3f} recovered={recovered}",
                    flush=True,
                )

    by_size: dict[str, Any] = {}
    for size in SIZES:
        subset = [run for run in runs if run["injection_size"] == size]
        recovered = sum(bool(run["recovered"]) for run in subset)
        by_size[str(size)] = {
            "runs": len(subset),
            "recovered": recovered,
            "recovery_rate": recovered / len(subset),
            "median_f1": float(np.median([run["score"]["f1"] for run in subset])),
            "median_precision": float(np.median([run["score"]["precision"] for run in subset])),
            "median_recall": float(np.median([run["score"]["recall"] for run in subset])),
        }

    pass_40 = by_size["40"]["recovery_rate"] >= 0.50
    pass_80 = by_size["80"]["recovery_rate"] >= 0.80
    verdict = "INJECTION_GATE_PASS" if pass_40 and pass_80 else "INJECTION_GATE_FAIL"
    summary = {
        "pilot": "GhostStream",
        "stage": "weak_stream_injection_and_permutation_null",
        "known_shower_labels_used_for": "controlled removal of labeled shower members from injection backgrounds only",
        "labels_visible_to_clustering": False,
        "background_windows": BACKGROUNDS,
        "model": MODEL,
        "feature_scales": SCALES.tolist(),
        "injection_sigma": INJECTION_SIGMA.tolist(),
        "permutations_per_run": PERMUTATIONS,
        "frozen_recovery_rule": {"precision": 0.50, "recall": 0.50, "f1": 0.50, "permutation_p_max": 0.01},
        "frozen_pass_rule": {"n40_minimum_rate": 0.50, "n80_minimum_rate": 0.80},
        "by_size": by_size,
        "verdict": verdict,
        "metadata": metadata,
        "runs": runs,
    }
    metrics = output / "ghoststream_injection_gate.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = [
        "# GhostStream weak-stream injection gate",
        "",
        f"**Verdict:** `{verdict}`",
        "",
    ]
    for size in SIZES:
        item = by_size[str(size)]
        lines.append(
            f"- n={size}: {item['recovered']}/{item['runs']} recovered "
            f"({item['recovery_rate']:.1%}); median F1={item['median_f1']:.3f}"
        )
    lines += [
        "",
        "Each recovery was compared with 99 random label permutations on the same clustered data.",
        "Passing supports moving to full null-catalog calibration; it does not claim an unknown stream.",
        "",
    ]
    report = output / "GHOSTSTREAM_INJECTION_GATE.md"
    report.write_text("\n".join(lines))

    print(f"\nVerdict: {verdict}")
    for size in SIZES:
        item = by_size[str(size)]
        print(f"n={size} recovery: {item['recovered']}/{item['runs']} ({item['recovery_rate']:.6f})")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
