#!/usr/bin/env python3
"""Preliminary blind GhostStream scan in four preselected low-activity 2025 months.

Known GMN shower labels are used only to remove assigned shower members before
clustering and to reject residual clusters close to known shower centroids after
clustering. Candidate discovery is blind within the remaining sporadic sample.
Each candidate must independently reappear in two random halves and pass a
cross-half feature-permutation density test in both directions.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader
from sklearn.cluster import HDBSCAN

from run_gate import circ_center, circ_diff, columns, label

MONTHS = ("2025-02", "2025-04", "2025-06", "2025-09")
MAX_SPORADIC = 35000
SEED = 20260731
SCALES = np.asarray([4.0, 4.0, 3.0, 3.0], dtype=float)
FULL_MODEL = {"min_cluster_size": 15, "min_samples": 5, "cluster_selection_method": "leaf"}
HALF_MODEL = {"min_cluster_size": 8, "min_samples": 4, "cluster_selection_method": "leaf"}
PERMUTATIONS = 199
MAX_CLUSTER_SIZE = 600
MAX_SCALED_RMS = 1.25
MAX_HALF_CENTROID_DISTANCE = 1.25
MIN_KNOWN_DISTANCE = 1.25
MIN_MEAN_PROBABILITY = 0.40


def prepare_month(frame: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    col = columns(frame)
    data = pd.DataFrame({
        "sol": pd.to_numeric(frame[col["sol"]], errors="coerce"),
        "lam": pd.to_numeric(frame[col["lam"]], errors="coerce"),
        "bet": pd.to_numeric(frame[col["bet"]], errors="coerce"),
        "vel": pd.to_numeric(frame[col["vel"]], errors="coerce"),
        "label": frame[col["label"]].map(label),
    })
    valid = np.isfinite(data[["sol", "lam", "bet", "vel"]]).all(axis=1)
    valid &= data["sol"].between(0, 360) & data["lam"].between(0, 360)
    valid &= data["bet"].between(-90, 90) & data["vel"].between(5, 75)
    data = data.loc[valid].reset_index(drop=True)
    center = circ_center(data["sol"].to_numpy(float))
    features = np.column_stack([
        circ_diff(data["lam"].to_numpy(float), data["sol"].to_numpy(float)),
        data["bet"].to_numpy(float),
        data["vel"].to_numpy(float),
        circ_diff(data["sol"].to_numpy(float), center),
    ])
    scaled = features / SCALES[None, :]

    known_centroids: list[dict[str, Any]] = []
    counts = data["label"].value_counts()
    for shower, count in counts.items():
        if shower == "SPORADIC" or int(count) < 20:
            continue
        mask = data["label"].to_numpy(str) == str(shower)
        known_centroids.append({
            "label": str(shower),
            "count": int(mask.sum()),
            "centroid": np.median(scaled[mask], axis=0).tolist(),
        })

    sporadic = data["label"].to_numpy(str) == "SPORADIC"
    sporadic_data = data.loc[sporadic].reset_index(drop=True)
    sporadic_features = features[sporadic]
    sporadic_scaled = scaled[sporadic]
    original_sporadic = int(sporadic_scaled.shape[0])
    if original_sporadic > MAX_SPORADIC:
        rng = np.random.default_rng(seed)
        selected = np.sort(rng.choice(original_sporadic, size=MAX_SPORADIC, replace=False))
        sporadic_data = sporadic_data.iloc[selected].reset_index(drop=True)
        sporadic_features = sporadic_features[selected]
        sporadic_scaled = sporadic_scaled[selected]
    meta = {
        "columns": col,
        "valid_rows": int(len(data)),
        "sporadic_rows_before_sampling": original_sporadic,
        "sporadic_rows_scanned": int(len(sporadic_data)),
        "solar_longitude_center": center,
        "known_shower_centroids": known_centroids,
    }
    return sporadic_data, sporadic_scaled, meta


def run_hdbscan(features: np.ndarray, setting: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    model = HDBSCAN(
        min_cluster_size=setting["min_cluster_size"],
        min_samples=setting["min_samples"],
        cluster_selection_method=setting["cluster_selection_method"],
        leaf_size=60,
        n_jobs=-1,
    )
    labels_out = model.fit_predict(features)
    probabilities = np.asarray(model.probabilities_, dtype=float)
    return labels_out, probabilities


def summaries(features: np.ndarray, assignments: np.ndarray, probabilities: np.ndarray,
              minimum: int) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for cluster in [int(value) for value in np.unique(assignments) if int(value) >= 0]:
        members = np.flatnonzero(assignments == cluster)
        if members.size < minimum or members.size > MAX_CLUSTER_SIZE:
            continue
        points = features[members]
        centroid = np.median(points, axis=0)
        distance = np.linalg.norm(points - centroid[None, :], axis=1)
        rms = float(np.sqrt(np.mean(distance ** 2)))
        output.append({
            "cluster": cluster,
            "size": int(members.size),
            "members": members,
            "centroid": centroid,
            "rms": rms,
            "mean_probability": float(np.mean(probabilities[members])),
        })
    return output


def closest(candidate: dict[str, Any], options: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    if not options:
        return None, math.inf
    distances = [float(np.linalg.norm(candidate["centroid"] - item["centroid"])) for item in options]
    index = int(np.argmin(distances))
    return options[index], distances[index]


def known_match(centroid: np.ndarray, known: list[dict[str, Any]]) -> tuple[str | None, float]:
    if not known:
        return None, math.inf
    distances = [float(np.linalg.norm(centroid - np.asarray(item["centroid"], dtype=float))) for item in known]
    index = int(np.argmin(distances))
    return str(known[index]["label"]), distances[index]


def density_test(train_points: np.ndarray, test_features: np.ndarray,
                 rng: np.random.Generator) -> dict[str, Any]:
    center = np.median(train_points, axis=0)
    mad = np.median(np.abs(train_points - center[None, :]), axis=0) * 1.4826
    sigma = np.maximum(mad, np.asarray([0.20, 0.20, 0.20, 0.20]))
    radius2 = 9.0

    def count_inside(values: np.ndarray) -> int:
        score = np.sum(((values - center[None, :]) / sigma[None, :]) ** 2, axis=1)
        return int(np.sum(score <= radius2))

    observed = count_inside(test_features)
    null_counts: list[int] = []
    for _ in range(PERMUTATIONS):
        permuted = np.empty_like(test_features)
        for column in range(test_features.shape[1]):
            permuted[:, column] = test_features[rng.permutation(test_features.shape[0]), column]
        null_counts.append(count_inside(permuted))
    p_value = (1 + sum(value >= observed for value in null_counts)) / (PERMUTATIONS + 1)
    return {
        "observed": observed,
        "null_q95": float(np.percentile(null_counts, 95)),
        "null_max": int(max(null_counts)),
        "p": float(p_value),
        "center": center.tolist(),
        "sigma": sigma.tolist(),
    }


def serialize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    output = dict(candidate)
    output.pop("members", None)
    if isinstance(output.get("centroid"), np.ndarray):
        output["centroid"] = output["centroid"].tolist()
    return output


def scan_month(month: str, month_index: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    print(f"Downloading {month} monthly GMN file...", flush=True)
    text = dd.get_monthly_file_content_by_date(month)
    frame = reader.read_data(text, output_camel_case=True).reset_index(drop=False)
    data, features, meta = prepare_month(frame, SEED + month_index)
    print(f"{month}: valid={meta['valid_rows']:,}; sporadic scanned={len(data):,}", flush=True)

    rng = np.random.default_rng(SEED + 1000 + month_index)
    order = rng.permutation(features.shape[0])
    split_a_mask = np.zeros(features.shape[0], dtype=bool)
    split_a_mask[order[: features.shape[0] // 2]] = True
    split_b_mask = ~split_a_mask
    a_indices = np.flatnonzero(split_a_mask)
    b_indices = np.flatnonzero(split_b_mask)

    full_assignments, full_prob = run_hdbscan(features, FULL_MODEL)
    a_assignments, a_prob = run_hdbscan(features[a_indices], HALF_MODEL)
    b_assignments, b_prob = run_hdbscan(features[b_indices], HALF_MODEL)
    full_clusters = summaries(features, full_assignments, full_prob, FULL_MODEL["min_cluster_size"])
    a_clusters = summaries(features[a_indices], a_assignments, a_prob, HALF_MODEL["min_cluster_size"])
    b_clusters = summaries(features[b_indices], b_assignments, b_prob, HALF_MODEL["min_cluster_size"])

    candidates_out: list[dict[str, Any]] = []
    for candidate in full_clusters:
        if candidate["rms"] > MAX_SCALED_RMS or candidate["mean_probability"] < MIN_MEAN_PROBABILITY:
            continue
        a_match, a_distance = closest(candidate, a_clusters)
        b_match, b_distance = closest(candidate, b_clusters)
        if a_match is None or b_match is None:
            continue
        if a_distance > MAX_HALF_CENTROID_DISTANCE or b_distance > MAX_HALF_CENTROID_DISTANCE:
            continue
        known_label, known_distance = known_match(candidate["centroid"], meta["known_shower_centroids"])
        if known_distance < MIN_KNOWN_DISTANCE:
            continue

        test_rng = np.random.default_rng(SEED + month_index * 10000 + candidate["cluster"])
        a_to_b = density_test(features[a_indices][a_match["members"]], features[b_indices], test_rng)
        b_to_a = density_test(features[b_indices][b_match["members"]], features[a_indices], test_rng)
        replicated = a_to_b["p"] <= 0.01 and b_to_a["p"] <= 0.01
        if not replicated:
            continue

        center_scaled = candidate["centroid"]
        center_unscaled = center_scaled * SCALES
        absolute_sol = (meta["solar_longitude_center"] + center_unscaled[3]) % 360.0
        score = (
            min(candidate["size"] / 40.0, 3.0)
            + candidate["mean_probability"]
            + min(known_distance / 3.0, 1.5)
            - candidate["rms"]
            - 0.25 * (a_distance + b_distance)
        )
        candidates_out.append({
            "month": month,
            "cluster": candidate["cluster"],
            "size": candidate["size"],
            "scaled_centroid": center_scaled.tolist(),
            "sun_centered_radiant_longitude_deg": float(center_unscaled[0]),
            "ecliptic_latitude_deg": float(center_unscaled[1]),
            "geocentric_speed_km_s": float(center_unscaled[2]),
            "solar_longitude_deg": float(absolute_sol),
            "scaled_rms": candidate["rms"],
            "mean_membership_probability": candidate["mean_probability"],
            "split_a_size": a_match["size"],
            "split_b_size": b_match["size"],
            "split_a_centroid_distance": a_distance,
            "split_b_centroid_distance": b_distance,
            "nearest_known_label": known_label,
            "nearest_known_scaled_distance": known_distance,
            "a_to_b_density_test": a_to_b,
            "b_to_a_density_test": b_to_a,
            "candidate_score": float(score),
        })

    candidates_out.sort(key=lambda item: item["candidate_score"], reverse=True)
    meta.update({
        "full_cluster_count": int(len(full_clusters)),
        "split_a_cluster_count": int(len(a_clusters)),
        "split_b_cluster_count": int(len(b_clusters)),
        "replicated_residual_candidates": int(len(candidates_out)),
    })
    print(f"{month}: replicated residual candidates={len(candidates_out)}", flush=True)
    return candidates_out, meta


def main() -> int:
    output = Path("ghoststream_blind_scan_results")
    output.mkdir(exist_ok=True)
    all_candidates: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    errors: list[dict[str, str]] = []

    for index, month in enumerate(MONTHS):
        try:
            candidates, meta = scan_month(month, index)
            all_candidates.extend(candidates)
            metadata[month] = meta
        except Exception as exc:
            errors.append({"month": month, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{month}: ERROR {type(exc).__name__}: {exc}", flush=True)

    all_candidates.sort(key=lambda item: item["candidate_score"], reverse=True)
    if len(metadata) < 3:
        verdict = "BLIND_SCAN_INCONCLUSIVE_DATA_FAILURE"
    elif all_candidates:
        verdict = "REPLICATED_RESIDUAL_CANDIDATES_FOUND__REQUIRES_ORBIT_VALIDATION"
    else:
        verdict = "NO_REPLICATED_RESIDUAL_CANDIDATE_IN_PILOT_MONTHS"

    summary = {
        "pilot": "GhostStream",
        "stage": "preliminary_blind_residual_scan",
        "months_preselected": list(MONTHS),
        "known_labels_visible_to_clustering": False,
        "known_labels_used_for": "remove assigned known-shower members before clustering and post-hoc nearest-known filtering",
        "feature_definition": [
            "sun-centered geocentric ecliptic radiant longitude",
            "geocentric ecliptic latitude",
            "geocentric speed",
            "solar-longitude offset within month",
        ],
        "feature_scales": SCALES.tolist(),
        "full_model": FULL_MODEL,
        "half_model": HALF_MODEL,
        "frozen_filters": {
            "maximum_cluster_size": MAX_CLUSTER_SIZE,
            "maximum_scaled_rms": MAX_SCALED_RMS,
            "maximum_half_centroid_distance": MAX_HALF_CENTROID_DISTANCE,
            "minimum_known_scaled_distance": MIN_KNOWN_DISTANCE,
            "minimum_mean_membership_probability": MIN_MEAN_PROBABILITY,
            "cross_half_permutation_p_max": 0.01,
            "permutations_each_direction": PERMUTATIONS,
        },
        "verdict": verdict,
        "months_completed": list(metadata),
        "errors": errors,
        "candidate_count": len(all_candidates),
        "candidates": all_candidates[:50],
        "metadata": metadata,
        "interpretation_limit": "These are statistical residual clusters, not discoveries. Orbit-element coherence, uncertainty cloning, IAU catalog matching, and independent-year replication are still required.",
    }
    metrics = output / "ghoststream_blind_scan.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    csv_rows = []
    for item in all_candidates:
        csv_rows.append({key: value for key, value in item.items() if not isinstance(value, dict)})
    pd.DataFrame(csv_rows).to_csv(output / "ghoststream_candidate_shortlist.csv", index=False)

    lines = [
        "# GhostStream preliminary blind scan",
        "",
        f"**Verdict:** `{verdict}`",
        "",
        f"- Months completed: **{len(metadata)}/{len(MONTHS)}**",
        f"- Replicated residual candidates: **{len(all_candidates)}**",
        "",
        "## Highest-ranked residuals",
        "",
    ]
    if not all_candidates:
        lines.append("No candidate passed every frozen replication and known-shower-distance filter.")
    for rank, item in enumerate(all_candidates[:15], start=1):
        lines.append(
            f"{rank}. `{item['month']}` cluster {item['cluster']}: n={item['size']}, "
            f"solar longitude={item['solar_longitude_deg']:.2f}°, "
            f"radiant λ-λ☉={item['sun_centered_radiant_longitude_deg']:.2f}°, "
            f"β={item['ecliptic_latitude_deg']:.2f}°, v_g={item['geocentric_speed_km_s']:.2f} km/s, "
            f"nearest known={item['nearest_known_label']} at scaled distance {item['nearest_known_scaled_distance']:.2f}."
        )
    lines += [
        "",
        "No item in this report is a claimed meteor-shower discovery.",
        "Candidates must next pass orbit-element, uncertainty-clone, IAU-catalog, and independent-year validation.",
        "",
    ]
    report = output / "GHOSTSTREAM_BLIND_SCAN.md"
    report.write_text("\n".join(lines))

    print(f"\nVerdict: {verdict}")
    print(f"Months completed: {len(metadata)}/{len(MONTHS)}")
    print(f"Replicated residual candidates: {len(all_candidates)}")
    for rank, item in enumerate(all_candidates[:10], start=1):
        print(
            f"Candidate {rank}: month={item['month']} n={item['size']} "
            f"sol={item['solar_longitude_deg']:.3f} lambda_sol={item['sun_centered_radiant_longitude_deg']:.3f} "
            f"beta={item['ecliptic_latitude_deg']:.3f} vg={item['geocentric_speed_km_s']:.3f} "
            f"known_distance={item['nearest_known_scaled_distance']:.3f} score={item['candidate_score']:.3f}"
        )
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    print(f"Shortlist: {output / 'ghoststream_candidate_shortlist.csv'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
