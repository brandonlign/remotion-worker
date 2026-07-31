#!/usr/bin/env python3
"""Source-preserving GhostStream blind residual scan v2.

This corrects the v1 blind-scan null, which independently permuted every feature
and therefore destroyed the real helion/antihelion/apex/toroidal correlations.
V2 preserves the three radiant-speed coordinates and permutes only solar
longitude. Replication uses alternating observing nights rather than random rows.
Broad established sporadic-source regions are flagged and excluded from the
novel-candidate shortlist. Cluster fragments are greedily deduplicated.
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

from run_gate import circ_center, circ_diff, columns, label, pick

MONTHS = ("2025-02", "2025-04", "2025-06", "2025-09")
MAX_SPORADIC = 35000
SEED = 20260731
SCALES = np.asarray([4.0, 4.0, 3.0, 3.0], dtype=float)
FULL_MODEL = {"min_cluster_size": 15, "min_samples": 5, "cluster_selection_method": "leaf"}
HALF_MODEL = {"min_cluster_size": 8, "min_samples": 4, "cluster_selection_method": "leaf"}
PERMUTATIONS = 199
MAX_CLUSTER_SIZE = 600
MAX_SCALED_RMS = 1.25
MAX_SOLAR_SIGMA_DEG = 3.0
MAX_HALF_CENTROID_DISTANCE = 1.25
MIN_KNOWN_DISTANCE = 1.25
MIN_MEAN_PROBABILITY = 0.40
DEDUP_DISTANCE = 1.0


def time_values(frame: pd.DataFrame) -> np.ndarray:
    cols = list(map(str, frame.columns))
    try:
        column = pick(cols, [("beginning", "utc", "time"), ("beg", "utc")])
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
        return parsed.dt.floor("D").astype("int64", errors="ignore").to_numpy()
    except Exception:
        pass
    try:
        column = pick(cols, [("beginning", "julian", "date"), ("jd", "ref")])
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(float)
        return np.floor(values).astype(np.int64)
    except Exception:
        return np.arange(len(frame), dtype=np.int64)


def prepare_month(frame: pd.DataFrame, seed: int) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    col = columns(frame)
    days = time_values(frame)
    data = pd.DataFrame({
        "sol": pd.to_numeric(frame[col["sol"]], errors="coerce"),
        "lam": pd.to_numeric(frame[col["lam"]], errors="coerce"),
        "bet": pd.to_numeric(frame[col["bet"]], errors="coerce"),
        "vel": pd.to_numeric(frame[col["vel"]], errors="coerce"),
        "label": frame[col["label"]].map(label),
        "day": days,
    })
    valid = np.isfinite(data[["sol", "lam", "bet", "vel"]]).all(axis=1)
    valid &= data["sol"].between(0, 360) & data["lam"].between(0, 360)
    valid &= data["bet"].between(-90, 90) & data["vel"].between(5, 75)
    data = data.loc[valid].reset_index(drop=True)
    center = circ_center(data["sol"].to_numpy(float))
    raw_features = np.column_stack([
        circ_diff(data["lam"].to_numpy(float), data["sol"].to_numpy(float)),
        data["bet"].to_numpy(float),
        data["vel"].to_numpy(float),
        circ_diff(data["sol"].to_numpy(float), center),
    ])
    scaled = raw_features / SCALES[None, :]

    known: list[dict[str, Any]] = []
    labels = data["label"].to_numpy(str)
    for shower, count in data["label"].value_counts().items():
        if shower == "SPORADIC" or int(count) < 20:
            continue
        mask = labels == str(shower)
        known.append({"label": str(shower), "count": int(mask.sum()),
                      "centroid": np.median(scaled[mask], axis=0).tolist()})

    sporadic = labels == "SPORADIC"
    data = data.loc[sporadic].reset_index(drop=True)
    scaled = scaled[sporadic]
    raw_features = raw_features[sporadic]
    original = int(len(data))
    if original > MAX_SPORADIC:
        rng = np.random.default_rng(seed)
        selected = np.sort(rng.choice(original, size=MAX_SPORADIC, replace=False))
        data = data.iloc[selected].reset_index(drop=True)
        scaled = scaled[selected]
        raw_features = raw_features[selected]
    meta = {
        "columns": col,
        "valid_rows": int(valid.sum()),
        "sporadic_rows_before_sampling": original,
        "sporadic_rows_scanned": int(len(data)),
        "solar_longitude_center": center,
        "known_shower_centroids": known,
    }
    return data, scaled, {**meta, "raw_features": raw_features}


def run_hdbscan(features: np.ndarray, setting: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    model = HDBSCAN(
        min_cluster_size=setting["min_cluster_size"],
        min_samples=setting["min_samples"],
        cluster_selection_method=setting["cluster_selection_method"],
        leaf_size=60,
        n_jobs=-1,
    )
    assignments = model.fit_predict(features)
    return assignments, np.asarray(model.probabilities_, dtype=float)


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
        axis_sigma = np.median(np.abs(points - centroid[None, :]), axis=0) * 1.4826
        output.append({
            "cluster": cluster,
            "size": int(members.size),
            "members": members,
            "centroid": centroid,
            "rms": float(np.sqrt(np.mean(distance ** 2))),
            "axis_sigma": axis_sigma,
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
    distances = [float(np.linalg.norm(centroid - np.asarray(item["centroid"]))) for item in known]
    index = int(np.argmin(distances))
    return str(known[index]["label"]), distances[index]


def circular_distance(value: float, center: float) -> float:
    return abs((value - center + 180.0) % 360.0 - 180.0)


def sporadic_source(longitude: float, latitude: float, speed: float) -> str | None:
    lon = longitude % 360.0
    if circular_distance(lon, 180.0) <= 30.0 and abs(latitude) <= 25.0 and speed < 40.0:
        return "ANTIHELION"
    if circular_distance(lon, 0.0) <= 30.0 and abs(latitude) <= 25.0 and speed < 40.0:
        return "HELION"
    if circular_distance(lon, 270.0) <= 40.0 and abs(latitude) <= 35.0 and speed >= 40.0:
        return "APEX"
    if circular_distance(lon, 270.0) <= 50.0 and abs(latitude) > 30.0 and speed >= 35.0:
        return "TOROIDAL"
    return None


def source_preserving_density_test(train_points: np.ndarray, test_features: np.ndarray,
                                   rng: np.random.Generator) -> dict[str, Any]:
    center = np.median(train_points, axis=0)
    sigma = np.median(np.abs(train_points - center[None, :]), axis=0) * 1.4826
    sigma = np.maximum(sigma, np.asarray([0.20, 0.20, 0.20, 0.20]))
    radius2 = 9.0

    def count_inside(values: np.ndarray) -> int:
        score = np.sum(((values - center[None, :]) / sigma[None, :]) ** 2, axis=1)
        return int(np.sum(score <= radius2))

    observed = count_inside(test_features)
    null_counts: list[int] = []
    # Preserve the real radiant-speed source structure. Only decouple it from
    # solar longitude, which is where a shower must show temporal concentration.
    for _ in range(PERMUTATIONS):
        permuted = test_features.copy()
        permuted[:, 3] = test_features[rng.permutation(test_features.shape[0]), 3]
        null_counts.append(count_inside(permuted))
    p_value = (1 + sum(value >= observed for value in null_counts)) / (PERMUTATIONS + 1)
    return {"observed": observed, "null_q95": float(np.percentile(null_counts, 95)),
            "null_max": int(max(null_counts)), "p": float(p_value)}


def deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: item["candidate_score"], reverse=True):
        center = np.asarray(candidate["scaled_centroid"], dtype=float)
        duplicate = None
        for existing in kept:
            if candidate["month"] != existing["month"]:
                continue
            distance = float(np.linalg.norm(center - np.asarray(existing["scaled_centroid"], dtype=float)))
            if distance <= DEDUP_DISTANCE:
                duplicate = existing
                break
        if duplicate is None:
            candidate["merged_cluster_ids"] = [candidate["cluster"]]
            kept.append(candidate)
        else:
            duplicate["merged_cluster_ids"].append(candidate["cluster"])
    return kept


def scan_month(month: str, month_index: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    print(f"Downloading {month} monthly GMN file...", flush=True)
    frame = reader.read_data(dd.get_monthly_file_content_by_date(month), output_camel_case=True).reset_index(drop=False)
    data, features, meta = prepare_month(frame, SEED + month_index)
    raw_features = meta.pop("raw_features")
    print(f"{month}: valid={meta['valid_rows']:,}; sporadic scanned={len(data):,}", flush=True)

    day_values = pd.to_numeric(data["day"], errors="coerce").fillna(np.arange(len(data))).to_numpy(np.int64)
    split_a_mask = day_values % 2 == 0
    if min(int(split_a_mask.sum()), int((~split_a_mask).sum())) < 1000:
        rng = np.random.default_rng(SEED + month_index)
        split_a_mask = rng.random(len(data)) < 0.5
    split_b_mask = ~split_a_mask
    a_indices, b_indices = np.flatnonzero(split_a_mask), np.flatnonzero(split_b_mask)

    full_assignments, full_prob = run_hdbscan(features, FULL_MODEL)
    a_assignments, a_prob = run_hdbscan(features[a_indices], HALF_MODEL)
    b_assignments, b_prob = run_hdbscan(features[b_indices], HALF_MODEL)
    full_clusters = summaries(features, full_assignments, full_prob, FULL_MODEL["min_cluster_size"])
    a_clusters = summaries(features[a_indices], a_assignments, a_prob, HALF_MODEL["min_cluster_size"])
    b_clusters = summaries(features[b_indices], b_assignments, b_prob, HALF_MODEL["min_cluster_size"])

    output: list[dict[str, Any]] = []
    for candidate in full_clusters:
        solar_sigma_deg = float(candidate["axis_sigma"][3] * SCALES[3])
        if candidate["rms"] > MAX_SCALED_RMS or solar_sigma_deg > MAX_SOLAR_SIGMA_DEG:
            continue
        if candidate["mean_probability"] < MIN_MEAN_PROBABILITY:
            continue
        a_match, a_distance = closest(candidate, a_clusters)
        b_match, b_distance = closest(candidate, b_clusters)
        if a_match is None or b_match is None or a_distance > MAX_HALF_CENTROID_DISTANCE or b_distance > MAX_HALF_CENTROID_DISTANCE:
            continue
        known_label, known_distance = known_match(candidate["centroid"], meta["known_shower_centroids"])
        if known_distance < MIN_KNOWN_DISTANCE:
            continue
        rng = np.random.default_rng(SEED + 10000 * month_index + candidate["cluster"])
        a_to_b = source_preserving_density_test(features[a_indices][a_match["members"]], features[b_indices], rng)
        b_to_a = source_preserving_density_test(features[b_indices][b_match["members"]], features[a_indices], rng)
        if a_to_b["p"] > 0.01 or b_to_a["p"] > 0.01:
            continue

        center_raw = candidate["centroid"] * SCALES
        solar_longitude = (meta["solar_longitude_center"] + center_raw[3]) % 360.0
        source = sporadic_source(float(center_raw[0]), float(center_raw[1]), float(center_raw[2]))
        score = (min(candidate["size"] / 40.0, 3.0) + candidate["mean_probability"]
                 + min(known_distance / 3.0, 1.5) - candidate["rms"]
                 - solar_sigma_deg / 6.0 - 0.25 * (a_distance + b_distance))
        output.append({
            "month": month, "cluster": candidate["cluster"], "size": candidate["size"],
            "scaled_centroid": candidate["centroid"].tolist(),
            "sun_centered_radiant_longitude_deg": float(center_raw[0]),
            "ecliptic_latitude_deg": float(center_raw[1]),
            "geocentric_speed_km_s": float(center_raw[2]),
            "solar_longitude_deg": float(solar_longitude),
            "solar_longitude_sigma_deg": solar_sigma_deg,
            "scaled_rms": candidate["rms"],
            "mean_membership_probability": candidate["mean_probability"],
            "split_a_size": a_match["size"], "split_b_size": b_match["size"],
            "split_a_centroid_distance": a_distance, "split_b_centroid_distance": b_distance,
            "nearest_known_label": known_label,
            "nearest_known_scaled_distance": known_distance,
            "sporadic_source_region": source,
            "a_to_b_source_preserving_test": a_to_b,
            "b_to_a_source_preserving_test": b_to_a,
            "candidate_score": float(score),
        })

    output = deduplicate(output)
    novel = [item for item in output if item["sporadic_source_region"] is None]
    meta.update({"full_cluster_count": len(full_clusters),
                 "source_preserving_replicated_structures": len(output),
                 "non_sporadic_source_shortlist": len(novel)})
    print(f"{month}: source-preserving structures={len(output)}; non-source shortlist={len(novel)}", flush=True)
    return novel, meta


def main() -> int:
    out = Path("ghoststream_blind_scan_v2_results")
    out.mkdir(exist_ok=True)
    candidates: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for index, month in enumerate(MONTHS):
        try:
            found, meta = scan_month(month, index)
            candidates.extend(found)
            metadata[month] = meta
        except Exception as exc:
            errors.append({"month": month, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{month}: ERROR {type(exc).__name__}: {exc}", flush=True)
    candidates.sort(key=lambda item: item["candidate_score"], reverse=True)
    if len(metadata) < 3:
        verdict = "BLIND_SCAN_V2_INCONCLUSIVE_DATA_FAILURE"
    elif candidates:
        verdict = "SOURCE_PRESERVING_RESIDUALS_FOUND__ORBIT_VALIDATION_REQUIRED"
    else:
        verdict = "NO_SOURCE_PRESERVING_RESIDUAL_IN_PILOT_MONTHS"
    summary = {
        "pilot": "GhostStream", "stage": "source_preserving_blind_scan_v2",
        "reason_for_correction": "v1 feature-wise permutation destroyed established sporadic-source correlations and produced 264 apparent residuals",
        "months_preselected": list(MONTHS), "known_labels_visible_to_clustering": False,
        "broad_sporadic_sources_excluded": ["HELION", "ANTIHELION", "APEX", "TOROIDAL"],
        "feature_scales": SCALES.tolist(), "full_model": FULL_MODEL, "half_model": HALF_MODEL,
        "frozen_filters": {"maximum_cluster_size": MAX_CLUSTER_SIZE,
                           "maximum_scaled_rms": MAX_SCALED_RMS,
                           "maximum_solar_longitude_sigma_deg": MAX_SOLAR_SIGMA_DEG,
                           "maximum_half_centroid_distance": MAX_HALF_CENTROID_DISTANCE,
                           "minimum_known_scaled_distance": MIN_KNOWN_DISTANCE,
                           "minimum_mean_membership_probability": MIN_MEAN_PROBABILITY,
                           "source_preserving_cross_half_p_max": 0.01,
                           "permutations_each_direction": PERMUTATIONS,
                           "dedup_scaled_distance": DEDUP_DISTANCE},
        "verdict": verdict, "months_completed": list(metadata), "errors": errors,
        "candidate_count": len(candidates), "candidates": candidates[:50], "metadata": metadata,
        "interpretation_limit": "Residuals are not discoveries; orbit coherence, uncertainty cloning, IAU matching, and independent-year replication remain required.",
    }
    metrics = out / "ghoststream_blind_scan_v2.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    pd.DataFrame([{k: v for k, v in item.items() if not isinstance(v, dict)} for item in candidates]).to_csv(out / "ghoststream_candidate_shortlist_v2.csv", index=False)
    lines = ["# GhostStream source-preserving blind scan v2", "", f"**Verdict:** `{verdict}`", "",
             f"- Months completed: **{len(metadata)}/{len(MONTHS)}**",
             f"- Non-source replicated residuals: **{len(candidates)}**", "", "## Shortlist", ""]
    if not candidates:
        lines.append("No residual passed the source-preserving, independent-night, duration, known-shower, and broad-source filters.")
    for rank, item in enumerate(candidates[:15], 1):
        lines.append(f"{rank}. `{item['month']}` n={item['size']}, λ☉={item['solar_longitude_deg']:.2f}°, λg−λ☉={item['sun_centered_radiant_longitude_deg']:.2f}°, β={item['ecliptic_latitude_deg']:.2f}°, vg={item['geocentric_speed_km_s']:.2f} km/s, σλ☉={item['solar_longitude_sigma_deg']:.2f}°.")
    lines += ["", "No item is a claimed meteor-shower discovery.", ""]
    report = out / "GHOSTSTREAM_BLIND_SCAN_V2.md"
    report.write_text("\n".join(lines))
    print(f"\nVerdict: {verdict}")
    print(f"Months completed: {len(metadata)}/{len(MONTHS)}")
    print(f"Non-source replicated residuals: {len(candidates)}")
    for rank, item in enumerate(candidates[:10], 1):
        print(f"Candidate {rank}: month={item['month']} n={item['size']} sol={item['solar_longitude_deg']:.3f} lambda_sol={item['sun_centered_radiant_longitude_deg']:.3f} beta={item['ecliptic_latitude_deg']:.3f} vg={item['geocentric_speed_km_s']:.3f} sol_sigma={item['solar_longitude_sigma_deg']:.3f} score={item['candidate_score']:.3f}")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    print(f"Shortlist: {out / 'ghoststream_candidate_shortlist_v2.csv'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
