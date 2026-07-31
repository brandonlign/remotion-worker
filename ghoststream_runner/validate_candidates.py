#!/usr/bin/env python3
"""Validate GhostStream residuals with orbital coherence and 2024 replication.

Four candidate centroids and cluster IDs were frozen by the source-preserving
2025 blind scan before this script was run. This script reconstructs their exact
members, tests orbital compactness against time-matched sporadic null groups,
compares each orbital medoid with known GMN shower medoids, and searches the
same feature-orbit region in the independent 2024 catalog.

No surviving object is automatically a discovery; IAU catalog and uncertainty-
clone validation would still be required.
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

from run_gate import circ_center, circ_diff, label

MONTHS = ("02", "04", "06", "09")
SCALES = np.asarray([4.0, 4.0, 3.0, 3.0], dtype=float)
MAX_SPORADIC = 35000
SEED = 20260731
MODEL = {"min_cluster_size": 15, "min_samples": 5, "cluster_selection_method": "leaf"}
NULL_DRAWS = 199
YEAR_NULL_DRAWS = 199
MIN_VALID_ORBITS = 15
MIN_VALID_ORBIT_FRACTION = 0.80
MAX_MEDIAN_D = 0.10
MAX_Q90_D = 0.20
MAX_ORBIT_NULL_P = 0.01
MIN_KNOWN_D = 0.10
MIN_2024_COUNT = 8
MAX_2024_P = 0.01
MAX_2024_MEDIAN_D = 0.15

TARGETS = [
    {"name": "GS-2025-06-A", "month": "06", "month_index": 2, "cluster": 124,
     "expected_scaled_centroid": [-36.54434775, 3.8293025, 11.757476666666667, 1.4628605890435533],
     "expected_size": 101},
    {"name": "GS-2025-02-A", "month": "02", "month_index": 0, "cluster": 153,
     "expected_scaled_centroid": [-37.33991575, 1.6176975, 13.716026666666666, 1.8099617691689787],
     "expected_size": 31},
    {"name": "GS-2025-06-B", "month": "06", "month_index": 2, "cluster": 90,
     "expected_scaled_centroid": [-34.435575625, -4.05179875, 11.051208333333333, -3.223115577623114],
     "expected_size": 16},
    {"name": "GS-2025-06-C", "month": "06", "month_index": 2, "cluster": 77,
     "expected_scaled_centroid": [-38.43460875, -5.402535, 14.239341666666668, -3.2691749109564414],
     "expected_size": 16},
]

BASE_COLUMNS = [
    "unique_trajectory_identifier", "beginning_utc_time", "iau_code",
    "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
    "a_au", "e", "i_deg", "peri_deg", "node_deg", "q_au", "tisserandj",
    "sigma_8", "sigma_9", "sigma_10", "sigma_11", "sigma_12", "sigma_15",
    "medianfiterr_arcsec", "num_stat",
]
ORBIT_COLUMNS = ["e", "q_au", "i_deg", "peri_deg", "node_deg"]


def numeric(frame: pd.DataFrame, name: str) -> np.ndarray:
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(float)


def prepare(frame: pd.DataFrame, year: int, month_index: int) -> dict[str, Any]:
    missing = [column for column in BASE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"GMN schema missing columns: {missing}")
    data = frame[BASE_COLUMNS].copy()
    data["label"] = data["iau_code"].map(label)
    for column in ["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s", *ORBIT_COLUMNS,
                   "a_au", "tisserandj", "sigma_8", "sigma_9", "sigma_10",
                   "sigma_11", "sigma_12", "sigma_15", "medianfiterr_arcsec", "num_stat"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = np.isfinite(data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]).all(axis=1)
    valid &= data["sol_lon_deg"].between(0, 360)
    valid &= data["lamgeo_deg"].between(0, 360)
    valid &= data["betgeo_deg"].between(-90, 90)
    valid &= data["vgeo_km_s"].between(5, 75)
    data = data.loc[valid].reset_index(drop=True)
    center = circ_center(data["sol_lon_deg"].to_numpy(float))
    features_raw = np.column_stack([
        circ_diff(data["lamgeo_deg"].to_numpy(float), data["sol_lon_deg"].to_numpy(float)),
        data["betgeo_deg"].to_numpy(float),
        data["vgeo_km_s"].to_numpy(float),
        circ_diff(data["sol_lon_deg"].to_numpy(float), center),
    ])
    features = features_raw / SCALES[None, :]

    known = data["label"].to_numpy(str) != "SPORADIC"
    sporadic = ~known
    known_data = data.loc[known].reset_index(drop=True)
    known_features = features[known]
    sporadic_data = data.loc[sporadic].reset_index(drop=True)
    sporadic_features = features[sporadic]
    before = int(len(sporadic_data))
    if year == 2025 and before > MAX_SPORADIC:
        rng = np.random.default_rng(SEED + month_index)
        selected = np.sort(rng.choice(before, size=MAX_SPORADIC, replace=False))
        sporadic_data = sporadic_data.iloc[selected].reset_index(drop=True)
        sporadic_features = sporadic_features[selected]
    return {
        "data": data, "center": center,
        "known_data": known_data, "known_features": known_features,
        "sporadic_data": sporadic_data, "sporadic_features": sporadic_features,
        "sporadic_before_sampling": before,
    }


def orbit_valid(frame: pd.DataFrame) -> np.ndarray:
    values = frame[ORBIT_COLUMNS].to_numpy(float)
    valid = np.isfinite(values).all(axis=1)
    valid &= frame["e"].to_numpy(float) >= 0.0
    valid &= frame["e"].to_numpy(float) < 1.5
    valid &= frame["q_au"].to_numpy(float) > 0.0
    valid &= frame["q_au"].to_numpy(float) < 2.0
    valid &= frame["i_deg"].to_numpy(float) >= 0.0
    valid &= frame["i_deg"].to_numpy(float) <= 180.0
    return valid


def perihelion_vector(orbits: np.ndarray) -> np.ndarray:
    # columns e, q, inclination, argument of perihelion, ascending node
    inc = np.deg2rad(orbits[:, 2])
    arg = np.deg2rad(orbits[:, 3])
    node = np.deg2rad(orbits[:, 4])
    return np.column_stack([
        np.cos(node) * np.cos(arg) - np.sin(node) * np.sin(arg) * np.cos(inc),
        np.sin(node) * np.cos(arg) + np.cos(node) * np.sin(arg) * np.cos(inc),
        np.sin(arg) * np.sin(inc),
    ])


def orbit_distance_matrix(orbits: np.ndarray, reference: np.ndarray | None = None) -> np.ndarray:
    a = orbits
    b = orbits if reference is None else reference
    e1, q1 = a[:, 0][:, None], a[:, 1][:, None]
    e2, q2 = b[:, 0][None, :], b[:, 1][None, :]
    i1, n1 = np.deg2rad(a[:, 2])[:, None], np.deg2rad(a[:, 4])[:, None]
    i2, n2 = np.deg2rad(b[:, 2])[None, :], np.deg2rad(b[:, 4])[None, :]
    cos_plane = np.cos(i1) * np.cos(i2) + np.sin(i1) * np.sin(i2) * np.cos(n1 - n2)
    plane = np.arccos(np.clip(cos_plane, -1.0, 1.0))
    p1, p2 = perihelion_vector(a), perihelion_vector(b)
    peri = np.arccos(np.clip(p1 @ p2.T, -1.0, 1.0))
    d2 = (
        (e1 - e2) ** 2
        + (q1 - q2) ** 2
        + (2.0 * np.sin(plane / 2.0)) ** 2
        + (((e1 + e2) / 2.0) * 2.0 * np.sin(peri / 2.0)) ** 2
    )
    return np.sqrt(np.maximum(d2, 0.0))


def medoid(orbits: np.ndarray) -> tuple[np.ndarray, int, np.ndarray]:
    matrix = orbit_distance_matrix(orbits)
    index = int(np.argmin(np.median(matrix, axis=1)))
    return orbits[index], index, matrix[index]


def dispersion(orbits: np.ndarray) -> dict[str, Any]:
    center, index, distances = medoid(orbits)
    return {
        "medoid": center.tolist(), "medoid_index": index,
        "median_d": float(np.median(distances)),
        "q90_d": float(np.percentile(distances, 90)),
        "fraction_d_lt_0_05": float(np.mean(distances < 0.05)),
        "fraction_d_lt_0_10": float(np.mean(distances < 0.10)),
        "distances": distances,
    }


def random_group_p(pool: pd.DataFrame, size: int, observed: float,
                   rng: np.random.Generator) -> tuple[float, list[float]]:
    if len(pool) < size:
        return 1.0, []
    values = pool[ORBIT_COLUMNS].to_numpy(float)
    null: list[float] = []
    for _ in range(NULL_DRAWS):
        sample = values[rng.choice(len(values), size=size, replace=False)]
        null.append(float(dispersion(sample)["median_d"]))
    p = (1 + sum(value <= observed for value in null)) / (NULL_DRAWS + 1)
    return float(p), null


def known_orbit_matches(known_data: pd.DataFrame, candidate_medoid: np.ndarray) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for shower, group in known_data.groupby("label"):
        good = group.loc[orbit_valid(group)]
        if len(good) < 15:
            continue
        values = good[ORBIT_COLUMNS].to_numpy(float)
        center, _, _ = medoid(values)
        distance = float(orbit_distance_matrix(candidate_medoid[None, :], center[None, :])[0, 0])
        output.append({"label": str(shower), "valid_members": int(len(good)),
                       "medoid": center.tolist(), "d": distance})
    return sorted(output, key=lambda item: item["d"])


def reconstruct_cluster(prepared: dict[str, Any], target: dict[str, Any]) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    features = prepared["sporadic_features"]
    model = HDBSCAN(min_cluster_size=MODEL["min_cluster_size"], min_samples=MODEL["min_samples"],
                    cluster_selection_method=MODEL["cluster_selection_method"], leaf_size=60, n_jobs=-1)
    assignments = model.fit_predict(features)
    expected = np.asarray(target["expected_scaled_centroid"], dtype=float)
    options = []
    for cluster in [int(value) for value in np.unique(assignments) if int(value) >= 0]:
        members = np.flatnonzero(assignments == cluster)
        center = np.median(features[members], axis=0)
        options.append((float(np.linalg.norm(center - expected)), cluster, members, center))
    if not options:
        raise RuntimeError(f"No clusters reconstructed for {target['name']}")
    options.sort(key=lambda item: item[0])
    distance, cluster, members, center = options[0]
    if distance > 0.05:
        raise RuntimeError(f"Could not reconstruct frozen cluster for {target['name']}: nearest distance={distance}")
    member_data = prepared["sporadic_data"].iloc[members].reset_index(drop=True)
    return member_data, features[members], {
        "requested_cluster": target["cluster"], "reconstructed_cluster": cluster,
        "centroid_distance_from_frozen": distance, "reconstructed_size": int(len(members)),
        "centroid": center.tolist(),
    }


def replicate_2024(prepared: dict[str, Any], center: np.ndarray, sigma: np.ndarray,
                   orbital_medoid: np.ndarray, rng: np.random.Generator) -> dict[str, Any]:
    features = prepared["sporadic_features"]
    data = prepared["sporadic_data"]
    sigma = np.maximum(sigma, np.asarray([0.20, 0.20, 0.20, 0.20]))
    radius2 = 9.0
    score = np.sum(((features - center[None, :]) / sigma[None, :]) ** 2, axis=1)
    selected = score <= radius2
    observed = int(selected.sum())
    null_counts: list[int] = []
    for _ in range(YEAR_NULL_DRAWS):
        permuted = features.copy()
        permuted[:, 3] = features[rng.permutation(len(features)), 3]
        value = np.sum(((permuted - center[None, :]) / sigma[None, :]) ** 2, axis=1)
        null_counts.append(int(np.sum(value <= radius2)))
    p = (1 + sum(value >= observed for value in null_counts)) / (YEAR_NULL_DRAWS + 1)
    selected_data = data.loc[selected]
    good = selected_data.loc[orbit_valid(selected_data)]
    if len(good):
        distances = orbit_distance_matrix(good[ORBIT_COLUMNS].to_numpy(float), orbital_medoid[None, :])[:, 0]
        median_d = float(np.median(distances))
        q90_d = float(np.percentile(distances, 90))
    else:
        median_d = None
        q90_d = None
    passed = observed >= MIN_2024_COUNT and p <= MAX_2024_P and median_d is not None and median_d <= MAX_2024_MEDIAN_D
    return {
        "observed_members": observed, "valid_orbit_members": int(len(good)),
        "permutation_p": float(p), "null_q95": float(np.percentile(null_counts, 95)),
        "null_max": int(max(null_counts)), "median_d_to_2025_medoid": median_d,
        "q90_d_to_2025_medoid": q90_d, "passed": bool(passed),
        "member_ids": list(map(str, good["unique_trajectory_identifier"].head(250).tolist())),
    }


def evaluate(target: dict[str, Any], cache: dict[tuple[int, str], dict[str, Any]]) -> dict[str, Any]:
    key_2025 = (2025, target["month"])
    if key_2025 not in cache:
        month = f"2025-{target['month']}"
        print(f"Downloading {month}...", flush=True)
        frame = reader.read_data(dd.get_monthly_file_content_by_date(month), output_camel_case=True).reset_index(drop=False)
        cache[key_2025] = prepare(frame, 2025, target["month_index"])
    p25 = cache[key_2025]
    members, member_features, reconstruction = reconstruct_cluster(p25, target)
    good = members.loc[orbit_valid(members)].reset_index(drop=True)
    valid_fraction = float(len(good) / len(members)) if len(members) else 0.0
    result: dict[str, Any] = {
        "name": target["name"], "month": target["month"], "reconstruction": reconstruction,
        "member_count": int(len(members)), "valid_orbit_count": int(len(good)),
        "valid_orbit_fraction": valid_fraction,
        "member_ids": list(map(str, good["unique_trajectory_identifier"].head(500).tolist())),
    }
    if len(good) < MIN_VALID_ORBITS:
        result.update({"verdict": "INSUFFICIENT_VALID_ORBITS", "orbit_passed": False, "year_passed": False})
        return result

    orbits = good[ORBIT_COLUMNS].to_numpy(float)
    spread = dispersion(orbits)
    medoid_orbit = np.asarray(spread.pop("medoid"), dtype=float)
    spread.pop("distances", None)
    local_width = max(5.0, float(np.std(member_features[:, 3]) * SCALES[3] * 2.0))
    candidate_sol = good["sol_lon_deg"].to_numpy(float)
    sol_center = circ_center(candidate_sol)
    pool_data = p25["sporadic_data"]
    pool_valid = orbit_valid(pool_data)
    pool_sol = pool_data["sol_lon_deg"].to_numpy(float)
    pool_mask = pool_valid & (np.abs(circ_diff(pool_sol, sol_center)) <= local_width)
    member_ids = set(map(str, good["unique_trajectory_identifier"].tolist()))
    pool = pool_data.loc[pool_mask & ~pool_data["unique_trajectory_identifier"].astype(str).isin(member_ids)].reset_index(drop=True)
    rng = np.random.default_rng(SEED + target["cluster"])
    orbit_p, null_values = random_group_p(pool, len(good), spread["median_d"], rng)
    known = known_orbit_matches(p25["known_data"], medoid_orbit)
    nearest = known[0] if known else None
    known_ok = nearest is None or nearest["d"] >= MIN_KNOWN_D
    orbit_passed = (
        valid_fraction >= MIN_VALID_ORBIT_FRACTION
        and spread["median_d"] <= MAX_MEDIAN_D
        and spread["q90_d"] <= MAX_Q90_D
        and orbit_p <= MAX_ORBIT_NULL_P
        and known_ok
    )

    key_2024 = (2024, target["month"])
    if key_2024 not in cache:
        month = f"2024-{target['month']}"
        print(f"Downloading {month}...", flush=True)
        frame = reader.read_data(dd.get_monthly_file_content_by_date(month), output_camel_case=True).reset_index(drop=False)
        cache[key_2024] = prepare(frame, 2024, target["month_index"])
    feature_center = np.median(member_features, axis=0)
    feature_sigma = np.median(np.abs(member_features - feature_center[None, :]), axis=0) * 1.4826
    year = replicate_2024(cache[key_2024], feature_center, feature_sigma, medoid_orbit, rng)

    if not known_ok:
        verdict = "LIKELY_KNOWN_SHOWER_LEAKAGE"
    elif not orbit_passed:
        verdict = "NOT_ORBIT_COHERENT"
    elif year["passed"]:
        verdict = "SURVIVES_ORBIT_AND_2024_REPLICATION"
    else:
        verdict = "ORBIT_COHERENT_NO_2024_REPLICATION"
    result.update({
        "orbital_medoid": medoid_orbit.tolist(), "orbit_dispersion": spread,
        "time_matched_null_pool": int(len(pool)), "orbit_null_p": float(orbit_p),
        "orbit_null_q05": float(np.percentile(null_values, 5)) if null_values else None,
        "orbit_null_median": float(np.median(null_values)) if null_values else None,
        "nearest_known_orbit": nearest, "nearest_known_top5": known[:5],
        "orbit_passed": bool(orbit_passed), "feature_center_scaled": feature_center.tolist(),
        "feature_sigma_scaled": feature_sigma.tolist(), "replication_2024": year,
        "year_passed": bool(year["passed"]), "verdict": verdict,
        "median_uncertainties": {
            "a_au": float(np.nanmedian(good["sigma_8"])), "e": float(np.nanmedian(good["sigma_9"])),
            "i_deg": float(np.nanmedian(good["sigma_10"])), "peri_deg": float(np.nanmedian(good["sigma_11"])),
            "node_deg": float(np.nanmedian(good["sigma_12"])), "q_au": float(np.nanmedian(good["sigma_15"])),
        },
    })
    return result


def main() -> int:
    output = Path("ghoststream_candidate_validation")
    output.mkdir(exist_ok=True)
    cache: dict[tuple[int, str], dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for target in TARGETS:
        print(f"\nValidating {target['name']}...", flush=True)
        try:
            result = evaluate(target, cache)
        except Exception as exc:
            result = {"name": target["name"], "month": target["month"],
                      "verdict": "VALIDATION_ERROR", "error": f"{type(exc).__name__}: {exc}",
                      "orbit_passed": False, "year_passed": False}
        results.append(result)
        print(
            f"{result['name']}: {result['verdict']} | n={result.get('member_count')} "
            f"valid={result.get('valid_orbit_count')} medianD={result.get('orbit_dispersion', {}).get('median_d')} "
            f"orbit_p={result.get('orbit_null_p')} known={result.get('nearest_known_orbit')} "
            f"rep2024={result.get('replication_2024', {}).get('observed_members')}", flush=True,
        )

    survivors = [item for item in results if item["verdict"] == "SURVIVES_ORBIT_AND_2024_REPLICATION"]
    orbit_only = [item for item in results if item["verdict"] == "ORBIT_COHERENT_NO_2024_REPLICATION"]
    if survivors:
        verdict = "CANDIDATES_SURVIVE_ORBIT_AND_INDEPENDENT_YEAR__IAU_AND_CLONE_VALIDATION_REQUIRED"
    elif orbit_only:
        verdict = "ORBIT_COHERENT_2025_ONLY__LOWER_PRIORITY_OR_OUTBURST_HYPOTHESES"
    else:
        verdict = "NO_CANDIDATE_SURVIVES_ORBIT_AND_INDEPENDENT_YEAR"
    summary = {
        "pilot": "GhostStream", "stage": "orbit_and_independent_year_validation",
        "targets_frozen_from": "2025 source-preserving blind scan v2",
        "orbit_fields": ORBIT_COLUMNS,
        "orbital_distance": "vector-perihelion Southworth-Hawkins-like distance",
        "frozen_orbit_rule": {"minimum_valid_orbits": MIN_VALID_ORBITS,
                              "minimum_valid_fraction": MIN_VALID_ORBIT_FRACTION,
                              "maximum_median_d": MAX_MEDIAN_D, "maximum_q90_d": MAX_Q90_D,
                              "time_matched_null_p_max": MAX_ORBIT_NULL_P,
                              "minimum_nearest_known_d": MIN_KNOWN_D},
        "frozen_2024_rule": {"minimum_members": MIN_2024_COUNT, "permutation_p_max": MAX_2024_P,
                             "maximum_median_d_to_2025_medoid": MAX_2024_MEDIAN_D},
        "verdict": verdict, "survivor_count": len(survivors),
        "orbit_only_count": len(orbit_only), "results": results,
        "interpretation_limit": "Survivors remain candidates, not discoveries. IAU catalog matching and uncertainty cloning remain required.",
    }
    metrics = output / "ghoststream_candidate_validation.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rows = []
    for item in results:
        rows.append({
            "name": item["name"], "verdict": item["verdict"],
            "members_2025": item.get("member_count"), "valid_orbits_2025": item.get("valid_orbit_count"),
            "median_d_2025": item.get("orbit_dispersion", {}).get("median_d"),
            "q90_d_2025": item.get("orbit_dispersion", {}).get("q90_d"),
            "orbit_null_p": item.get("orbit_null_p"),
            "nearest_known": (item.get("nearest_known_orbit") or {}).get("label"),
            "nearest_known_d": (item.get("nearest_known_orbit") or {}).get("d"),
            "members_2024": item.get("replication_2024", {}).get("observed_members"),
            "replication_p_2024": item.get("replication_2024", {}).get("permutation_p"),
            "median_d_2024_to_2025": item.get("replication_2024", {}).get("median_d_to_2025_medoid"),
        })
    pd.DataFrame(rows).to_csv(output / "ghoststream_candidate_validation.csv", index=False)
    lines = ["# GhostStream candidate validation", "", f"**Verdict:** `{verdict}`", "",
             f"- Orbit + independent-year survivors: **{len(survivors)}**",
             f"- Orbit-coherent 2025-only candidates: **{len(orbit_only)}**", "", "## Candidates", ""]
    for item in results:
        lines.append(
            f"- **{item['name']}:** `{item['verdict']}`; n2025={item.get('member_count')}; "
            f"median D={item.get('orbit_dispersion', {}).get('median_d')}; "
            f"nearest known={(item.get('nearest_known_orbit') or {}).get('label')} "
            f"(D={(item.get('nearest_known_orbit') or {}).get('d')}); "
            f"n2024={item.get('replication_2024', {}).get('observed_members')}."
        )
    lines += ["", "No survivor is a claimed discovery. IAU catalog and uncertainty-clone checks remain mandatory.", ""]
    report = output / "GHOSTSTREAM_CANDIDATE_VALIDATION.md"
    report.write_text("\n".join(lines))
    print(f"\nOverall verdict: {verdict}")
    print(f"Orbit + 2024 survivors: {len(survivors)}")
    print(f"Orbit-coherent 2025-only: {len(orbit_only)}")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    print(f"CSV: {output / 'ghoststream_candidate_validation.csv'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
