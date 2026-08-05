#!/usr/bin/env python3
"""All-season blind search for a genuinely uncatalogued meteor stream.

Discovery year: 2025. Independent replication years: 2024 and 2023.
Every parsable IAU MDC solution, including working-list and removed entries, is
used as a novelty veto. A surviving candidate must be compact in radiant, time,
and orbit; replicate across observing-night splits; avoid the broad sporadic
sources; pass a local orbital null; repeat in both untouched years; and remain
compact under reported measurement uncertainties.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader
from sklearn.cluster import HDBSCAN

SEED = 20260731
DISCOVERY_YEAR = 2025
VALIDATION_YEARS = (2024, 2023)
MONTHS = tuple(range(1, 13))
IAU_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamfulldata2026.txt"
FEATURE_SCALES = np.asarray([3.5, 3.0, 2.5, 2.5], dtype=float)
MIN_CLUSTER_SIZE = 12
MIN_SAMPLES = 4
MAX_MONTH_ROWS = 150000
MAX_CLUSTER_SIZE = 300
MAX_SCALED_RMS = 1.35
MAX_SOLAR_SIGMA_DEG = 2.5
MIN_MEMBERSHIP_PROB = 0.35
MIN_NIGHTS = 4
MIN_STATIONS = 6
MAX_ONE_NIGHT_FRACTION = 0.50
MAX_ONE_STATION_SET_FRACTION = 0.50
SPLIT_PERMUTATIONS = 199
ORBIT_NULL_DRAWS = 199
VALIDATION_NULL_DRAWS = 499
CLONE_DRAWS = 500
MAX_ORBIT_MEDIAN_D = 0.10
MAX_ORBIT_Q90_D = 0.20
MAX_ORBIT_NULL_P = 0.01
MAX_IAU_ORBIT_D = 0.15
MAX_IAU_SOLAR_DELTA = 7.0
MAX_IAU_RADIANT_SCALED = 2.5
MIN_VALIDATION_MEMBERS = 8
MIN_VALIDATION_NIGHTS = 3
MIN_VALIDATION_STATIONS = 5
MAX_VALIDATION_P = 0.01
MAX_VALIDATION_MEDIAN_D = 0.12
MAX_CANDIDATES_FOR_VALIDATION = 30
MIN_CLONE_PASS_FRACTION = 0.80
OUT = Path("ghoststream_novel_results")

BASE_COLUMNS = [
    "unique_trajectory_identifier", "beginning_utc_time", "iau_code",
    "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
    "e", "q_au", "i_deg", "peri_deg", "node_deg",
    "sigma_9", "sigma_15", "sigma_10", "sigma_11", "sigma_12",
    "medianfiterr_arcsec", "num_stat", "participating_stations",
]
ORBIT_COLUMNS = ["e", "q_au", "i_deg", "peri_deg", "node_deg"]
SIGMA_COLUMNS = ["sigma_9", "sigma_15", "sigma_10", "sigma_11", "sigma_12"]


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


def circ_center(values: np.ndarray) -> float:
    radians = np.deg2rad(values)
    return float(np.rad2deg(math.atan2(float(np.sin(radians).mean()), float(np.cos(radians).mean()))) % 360.0)


def number(value: Any) -> float | None:
    text = str(value).strip().replace("[", "").replace("]", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def shower_label(value: Any) -> str:
    if pd.isna(value):
        return "SPORADIC"
    text = str(value).strip().upper()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return "SPORADIC" if text in {"", "-1", "0", "...", "NONE", "NAN", "SPO", "SPORADIC"} else text


def station_tokens(value: Any) -> set[str]:
    return {token for token in re.split(r"[^A-Za-z0-9]+", str(value).upper()) if len(token) >= 4}


def source_region(lon: float, beta: float, speed: float) -> str | None:
    lon %= 360.0
    if abs(float(circ_diff(lon, 180.0))) <= 30 and abs(beta) <= 25 and speed < 40:
        return "ANTIHELION"
    if abs(float(circ_diff(lon, 0.0))) <= 30 and abs(beta) <= 25 and speed < 40:
        return "HELION"
    if abs(float(circ_diff(lon, 270.0))) <= 40 and abs(beta) <= 35 and speed >= 40:
        return "APEX"
    if abs(float(circ_diff(lon, 270.0))) <= 50 and abs(beta) > 30 and speed >= 35:
        return "TOROIDAL"
    return None


def perihelion_vector(orbits: np.ndarray) -> np.ndarray:
    inc = np.deg2rad(orbits[:, 2]); arg = np.deg2rad(orbits[:, 3]); node = np.deg2rad(orbits[:, 4])
    return np.column_stack([
        np.cos(node) * np.cos(arg) - np.sin(node) * np.sin(arg) * np.cos(inc),
        np.sin(node) * np.cos(arg) + np.cos(node) * np.sin(arg) * np.cos(inc),
        np.sin(arg) * np.sin(inc),
    ])


def orbit_distance_matrix(a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    b = a if b is None else b
    e1, q1 = a[:, 0][:, None], a[:, 1][:, None]
    e2, q2 = b[:, 0][None, :], b[:, 1][None, :]
    i1, n1 = np.deg2rad(a[:, 2])[:, None], np.deg2rad(a[:, 4])[:, None]
    i2, n2 = np.deg2rad(b[:, 2])[None, :], np.deg2rad(b[:, 4])[None, :]
    plane = np.arccos(np.clip(np.cos(i1) * np.cos(i2) + np.sin(i1) * np.sin(i2) * np.cos(n1 - n2), -1, 1))
    p1, p2 = perihelion_vector(a), perihelion_vector(b)
    peri = np.arccos(np.clip(p1 @ p2.T, -1, 1))
    d2 = ((e1 - e2) ** 2 + (q1 - q2) ** 2 + (2 * np.sin(plane / 2)) ** 2
          + (((e1 + e2) / 2) * 2 * np.sin(peri / 2)) ** 2)
    return np.sqrt(np.maximum(d2, 0.0))


def valid_orbits(frame: pd.DataFrame) -> np.ndarray:
    values = frame[ORBIT_COLUMNS].to_numpy(float)
    valid = np.isfinite(values).all(axis=1)
    valid &= (values[:, 0] >= 0) & (values[:, 0] < 1.5)
    valid &= (values[:, 1] > 0) & (values[:, 1] < 2.0)
    valid &= (values[:, 2] >= 0) & (values[:, 2] <= 180)
    return valid


def orbit_summary(orbits: np.ndarray) -> dict[str, Any]:
    matrix = orbit_distance_matrix(orbits)
    idx = int(np.argmin(np.median(matrix, axis=1)))
    distances = matrix[idx]
    return {
        "medoid": orbits[idx],
        "median_d": float(np.median(distances)),
        "q90_d": float(np.percentile(distances, 90)),
    }


def parse_iau() -> list[dict[str, Any]]:
    text = requests.get(IAU_URL, timeout=60).text
    solutions: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "|" not in line or not line.lstrip().startswith('"'):
            continue
        try:
            row = next(csv.reader(io.StringIO(line), delimiter="|", quotechar='"'))
        except Exception:
            continue
        if len(row) < 29:
            continue
        sol, vg, slon, beta = number(row[10]), number(row[15]), number(row[17]), number(row[18])
        if None in {sol, vg, slon, beta}:
            continue
        e, q, peri, node, inc = number(row[24]), number(row[23]), number(row[25]), number(row[26]), number(row[27])
        orbit = None if None in {e, q, peri, node, inc} else np.asarray([e, q, inc, peri, node], dtype=float)
        status = int(number(row[4]) or 0)
        solutions.append({
            "iau_no": row[1].strip(' "'), "code": row[3].strip(' "'), "status": status,
            "name": row[6].strip(' "'), "sol": float(sol),
            "slon": float(circ_diff(float(slon), 0.0)), "beta": float(beta), "vg": float(vg),
            "orbit": orbit,
        })
    if len(solutions) < 1500:
        raise RuntimeError(f"Only {len(solutions)} IAU solutions parsed")
    return solutions


def iau_match(center: np.ndarray, medoid: np.ndarray, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for item in catalog:
        solar = abs(float(circ_diff(center[3], item["sol"])))
        radiant = math.sqrt((float(circ_diff(center[0], item["slon"])) / 4.0) ** 2
                            + ((center[1] - item["beta"]) / 4.0) ** 2
                            + ((center[2] - item["vg"]) / 3.0) ** 2)
        od = None if item["orbit"] is None else float(orbit_distance_matrix(medoid[None, :], item["orbit"][None, :])[0, 0])
        score = (solar / 7.0) ** 2 + radiant ** 2 + ((od / 0.15) ** 2 if od is not None else 1.0)
        matched = solar <= MAX_IAU_SOLAR_DELTA and (
            (od is not None and radiant <= MAX_IAU_RADIANT_SCALED and od <= MAX_IAU_ORBIT_D)
            or (od is None and radiant <= 1.25)
        )
        candidate = {"matched": matched, "code": item["code"], "name": item["name"],
                     "status": item["status"], "solar_delta": solar,
                     "radiant_scaled_distance": radiant, "orbit_d": od, "score": score}
        if best is None or score < best["score"]:
            best = candidate
    return best or {"matched": False}


def load_month(year: int, month: int) -> pd.DataFrame:
    key = f"{year}-{month:02d}"
    print(f"Downloading {key}...", flush=True)
    return reader.read_data(dd.get_monthly_file_content_by_date(key), output_camel_case=True).reset_index(drop=False)


def prepare(frame: pd.DataFrame, year: int, month: int) -> dict[str, Any]:
    missing = [column for column in BASE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"Missing GMN columns: {missing}")
    data = frame[BASE_COLUMNS].copy()
    data["label"] = data["iau_code"].map(shower_label)
    numeric_cols = ["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s", *ORBIT_COLUMNS,
                    *SIGMA_COLUMNS, "medianfiterr_arcsec", "num_stat"]
    for col in numeric_cols:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    valid = np.isfinite(data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]).all(axis=1)
    valid &= data["sol_lon_deg"].between(0, 360) & data["lamgeo_deg"].between(0, 360)
    valid &= data["betgeo_deg"].between(-90, 90) & data["vgeo_km_s"].between(5, 75)
    valid &= data["num_stat"].fillna(0) >= 2
    valid &= data["medianfiterr_arcsec"].fillna(9999) <= 180
    data = data.loc[valid & (data["label"] == "SPORADIC")].reset_index(drop=True)
    if len(data) > MAX_MONTH_ROWS:
        data = data.sample(MAX_MONTH_ROWS, random_state=SEED + year * 100 + month).sort_index().reset_index(drop=True)
    center_sol = circ_center(data["sol_lon_deg"].to_numpy(float))
    raw = np.column_stack([
        circ_diff(data["lamgeo_deg"].to_numpy(float), data["sol_lon_deg"].to_numpy(float)),
        data["betgeo_deg"].to_numpy(float), data["vgeo_km_s"].to_numpy(float),
        circ_diff(data["sol_lon_deg"].to_numpy(float), center_sol),
    ])
    scaled = raw / FEATURE_SCALES[None, :]
    parsed = pd.to_datetime(data["beginning_utc_time"], errors="coerce", utc=True)
    nights = parsed.dt.floor("D").view("int64").to_numpy()
    return {"data": data, "raw": raw, "scaled": scaled, "center_sol": center_sol, "nights": nights}


def robust_sigma(values: np.ndarray, minimum: np.ndarray) -> np.ndarray:
    center = np.median(values, axis=0)
    sigma = np.median(np.abs(values - center[None, :]), axis=0) * 1.4826
    return np.maximum(sigma, minimum)


def density_test(train: np.ndarray, test: np.ndarray, rng: np.random.Generator) -> dict[str, Any]:
    center = np.median(train, axis=0)
    sigma = robust_sigma(train, np.asarray([0.20, 0.20, 0.20, 0.20]))
    observed = int(np.sum(np.sum(((test - center) / sigma) ** 2, axis=1) <= 9.0))
    null = []
    for _ in range(SPLIT_PERMUTATIONS):
        perm = test.copy(); perm[:, 3] = test[rng.permutation(len(test)), 3]
        null.append(int(np.sum(np.sum(((perm - center) / sigma) ** 2, axis=1) <= 9.0)))
    p = (1 + sum(value >= observed for value in null)) / (SPLIT_PERMUTATIONS + 1)
    return {"observed": observed, "p": float(p), "null_q95": float(np.percentile(null, 95))}


def orbit_null(data: pd.DataFrame, member_orbits: np.ndarray, sol: float, width: float,
               rng: np.random.Generator) -> dict[str, Any]:
    local = data.loc[valid_orbits(data) & (np.abs(circ_diff(data["sol_lon_deg"].to_numpy(float), sol)) <= width)]
    if len(local) < len(member_orbits) * 3:
        return {"p": 1.0, "pool": int(len(local))}
    values = local[ORBIT_COLUMNS].to_numpy(float)
    observed = orbit_summary(member_orbits)["median_d"]
    null = []
    for _ in range(ORBIT_NULL_DRAWS):
        sample = values[rng.choice(len(values), size=len(member_orbits), replace=False)]
        null.append(orbit_summary(sample)["median_d"])
    p = (1 + sum(value <= observed for value in null)) / (ORBIT_NULL_DRAWS + 1)
    return {"p": float(p), "pool": int(len(local)), "null_q05": float(np.percentile(null, 5))}


def scan_month(month: int, catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared = prepare(load_month(DISCOVERY_YEAR, month), DISCOVERY_YEAR, month)
    data, raw, scaled, nights = prepared["data"], prepared["raw"], prepared["scaled"], prepared["nights"]
    print(f"2025-{month:02d}: scanning {len(data):,} quality sporadics", flush=True)
    model = HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE, min_samples=MIN_SAMPLES,
                    cluster_selection_method="leaf", leaf_size=60, n_jobs=-1)
    assignments = model.fit_predict(scaled)
    probabilities = np.asarray(model.probabilities_, dtype=float)
    candidates: list[dict[str, Any]] = []
    for cluster in [int(x) for x in np.unique(assignments) if int(x) >= 0]:
        members = np.flatnonzero(assignments == cluster)
        if not MIN_CLUSTER_SIZE <= len(members) <= MAX_CLUSTER_SIZE:
            continue
        points = scaled[members]; center_scaled = np.median(points, axis=0)
        rms = float(np.sqrt(np.mean(np.sum((points - center_scaled) ** 2, axis=1))))
        sigma_raw = robust_sigma(raw[members], np.asarray([0.3, 0.3, 0.3, 0.3]))
        solar_sigma = float(sigma_raw[3])
        if rms > MAX_SCALED_RMS or solar_sigma > MAX_SOLAR_SIGMA_DEG:
            continue
        mean_prob = float(np.mean(probabilities[members]))
        if mean_prob < MIN_MEMBERSHIP_PROB:
            continue
        member_nights = nights[members]
        unique_nights, night_counts = np.unique(member_nights, return_counts=True)
        if len(unique_nights) < MIN_NIGHTS or night_counts.max() / len(members) > MAX_ONE_NIGHT_FRACTION:
            continue
        station_sets = data.iloc[members]["participating_stations"].fillna("").astype(str)
        all_stations = set().union(*(station_tokens(value) for value in station_sets))
        if len(all_stations) < MIN_STATIONS or station_sets.value_counts(normalize=True).iloc[0] > MAX_ONE_STATION_SET_FRACTION:
            continue
        member_frame = data.iloc[members].reset_index(drop=True)
        orbit_mask = valid_orbits(member_frame)
        if orbit_mask.sum() < MIN_CLUSTER_SIZE or orbit_mask.mean() < 0.80:
            continue
        member_orbits = member_frame.loc[orbit_mask, ORBIT_COLUMNS].to_numpy(float)
        orbit = orbit_summary(member_orbits)
        if orbit["median_d"] > MAX_ORBIT_MEDIAN_D or orbit["q90_d"] > MAX_ORBIT_Q90_D:
            continue
        ordered_nights = {value: index for index, value in enumerate(sorted(unique_nights.tolist()))}
        split_a_members = np.asarray([ordered_nights[value] % 2 == 0 for value in member_nights])
        split_a_all = np.asarray([ordered_nights.get(value, 0) % 2 == 0 for value in nights])
        if split_a_members.sum() < 5 or (~split_a_members).sum() < 5:
            continue
        rng = np.random.default_rng(SEED + month * 10000 + cluster)
        a_to_b = density_test(scaled[members][split_a_members], scaled[~split_a_all], rng)
        b_to_a = density_test(scaled[members][~split_a_members], scaled[split_a_all], rng)
        if min(a_to_b["observed"], b_to_a["observed"]) < 4 or max(a_to_b["p"], b_to_a["p"]) > 0.01:
            continue
        center_raw = center_scaled * FEATURE_SCALES
        absolute_center = np.asarray([center_raw[0], center_raw[1], center_raw[2],
                                      (prepared["center_sol"] + center_raw[3]) % 360.0])
        source = source_region(float(absolute_center[0]), float(absolute_center[1]), float(absolute_center[2]))
        if source is not None:
            continue
        null = orbit_null(data, member_orbits, float(absolute_center[3]), max(3 * solar_sigma, 1.5), rng)
        if null["p"] > MAX_ORBIT_NULL_P:
            continue
        iau = iau_match(absolute_center, orbit["medoid"], catalog)
        if iau.get("matched"):
            continue
        score = (math.log1p(len(members)) + mean_prob - rms - solar_sigma / 4
                 - orbit["median_d"] * 5 - max(a_to_b["p"], b_to_a["p"]) * 10)
        candidates.append({
            "month": month, "cluster": cluster, "members_2025": int(len(members)),
            "center": absolute_center.tolist(), "sigma_raw": sigma_raw.tolist(),
            "scaled_center": center_scaled.tolist(), "scaled_rms": rms,
            "solar_sigma_deg": solar_sigma, "mean_probability": mean_prob,
            "nights_2025": int(len(unique_nights)), "stations_2025": int(len(all_stations)),
            "orbit_medoid": orbit["medoid"].tolist(), "orbit_median_d": orbit["median_d"],
            "orbit_q90_d": orbit["q90_d"], "orbit_null": null,
            "split_a_to_b": a_to_b, "split_b_to_a": b_to_a,
            "nearest_iau": iau, "score": float(score),
            "member_ids_2025": member_frame["unique_trajectory_identifier"].astype(str).tolist(),
            "member_rows_2025": member_frame,
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        c = np.asarray(candidate["center"])
        duplicate = False
        for kept in deduped:
            k = np.asarray(kept["center"])
            distance = math.sqrt((float(circ_diff(c[0], k[0])) / 3.5) ** 2 + ((c[1]-k[1])/3) ** 2
                                 + ((c[2]-k[2])/2.5) ** 2 + (float(circ_diff(c[3], k[3]))/2.5) ** 2)
            if distance < 1.0:
                duplicate = True; break
        if not duplicate:
            deduped.append(candidate)
    print(f"2025-{month:02d}: uncatalogued candidates={len(deduped)}", flush=True)
    return deduped, {"quality_sporadics": int(len(data)), "clusters": int(len(set(assignments)) - (1 if -1 in assignments else 0)),
                     "uncatalogued_candidates": int(len(deduped))}


def validate(candidate: dict[str, Any], year: int, cache: dict[tuple[int, int], dict[str, Any]]) -> dict[str, Any]:
    key = (year, candidate["month"])
    if key not in cache:
        cache[key] = prepare(load_month(*key), *key)
    prepared = cache[key]; data, raw, nights = prepared["data"], prepared["raw"], prepared["nights"]
    center = np.asarray(candidate["center"], dtype=float)
    sigma = np.maximum(np.asarray(candidate["sigma_raw"], dtype=float), np.asarray([0.5, 0.5, 0.5, 0.5]))
    rad_score = ((circ_diff(raw[:, 0], center[0]) / sigma[0]) ** 2
                 + ((raw[:, 1] - center[1]) / sigma[1]) ** 2
                 + ((raw[:, 2] - center[2]) / sigma[2]) ** 2)
    orbit_mask = valid_orbits(data)
    orbit_dist = np.full(len(data), np.inf)
    orbit_dist[orbit_mask] = orbit_distance_matrix(data.loc[orbit_mask, ORBIT_COLUMNS].to_numpy(float),
                                                    np.asarray(candidate["orbit_medoid"])[None, :])[:, 0]
    local = (rad_score <= 9.0) & (orbit_dist <= 0.20)
    temporal = np.abs(circ_diff(data["sol_lon_deg"].to_numpy(float), center[3])) <= max(3 * sigma[3], 1.0)
    selected = local & temporal & (orbit_dist <= 0.15)
    observed = int(selected.sum())
    unique_nights = int(len(np.unique(nights[selected]))) if observed else 0
    stations = set().union(*(station_tokens(value) for value in data.loc[selected, "participating_stations"].fillna(""))) if observed else set()
    median_d = float(np.median(orbit_dist[selected])) if observed else None
    all_sol = data["sol_lon_deg"].to_numpy(float)
    local_count = int(local.sum())
    rng = np.random.default_rng(SEED + year * 10000 + candidate["month"] * 100 + candidate["cluster"])
    null = []
    width = max(3 * sigma[3], 1.0)
    for _ in range(VALIDATION_NULL_DRAWS):
        sampled_sol = all_sol[rng.choice(len(all_sol), size=local_count, replace=False)] if local_count <= len(all_sol) else all_sol
        null.append(int(np.sum(np.abs(circ_diff(sampled_sol, center[3])) <= width)))
    p = (1 + sum(value >= observed for value in null)) / (VALIDATION_NULL_DRAWS + 1)
    passed = (observed >= MIN_VALIDATION_MEMBERS and unique_nights >= MIN_VALIDATION_NIGHTS
              and len(stations) >= MIN_VALIDATION_STATIONS and p <= MAX_VALIDATION_P
              and median_d is not None and median_d <= MAX_VALIDATION_MEDIAN_D)
    return {"year": year, "members": observed, "local_pool": local_count, "nights": unique_nights,
            "stations": len(stations), "p": float(p), "null_q99": float(np.percentile(null, 99)),
            "median_d": median_d, "passed": bool(passed),
            "member_ids": data.loc[selected, "unique_trajectory_identifier"].astype(str).tolist()}


def clone_stability(candidate: dict[str, Any]) -> dict[str, Any]:
    frame = candidate["member_rows_2025"]
    mask = valid_orbits(frame)
    values = frame.loc[mask, ORBIT_COLUMNS].to_numpy(float)
    sigmas = frame.loc[mask, SIGMA_COLUMNS].to_numpy(float)
    sigmas = np.nan_to_num(np.abs(sigmas), nan=0.0, posinf=0.0, neginf=0.0)
    sigmas = np.minimum(sigmas, np.asarray([0.10, 0.10, 10.0, 20.0, 5.0])[None, :])
    rng = np.random.default_rng(SEED + candidate["month"] * 100 + candidate["cluster"])
    passed = 0; medians = []
    for _ in range(CLONE_DRAWS):
        clone = values + rng.normal(size=values.shape) * sigmas
        clone[:, 0] = np.clip(clone[:, 0], 0, 1.49); clone[:, 1] = np.clip(clone[:, 1], 0.01, 1.99)
        clone[:, 2] = np.clip(clone[:, 2], 0, 180); clone[:, 3:] %= 360
        summary = orbit_summary(clone); medians.append(summary["median_d"])
        if summary["median_d"] <= MAX_ORBIT_MEDIAN_D and summary["q90_d"] <= MAX_ORBIT_Q90_D:
            passed += 1
    fraction = passed / CLONE_DRAWS
    return {"draws": CLONE_DRAWS, "pass_fraction": fraction,
            "median_of_clone_medians": float(np.median(medians)), "passed": fraction >= MIN_CLONE_PASS_FRACTION}


def serializable(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if key != "member_rows_2025"}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    catalog = parse_iau()
    print(f"IAU solutions parsed: {len(catalog)}", flush=True)
    all_candidates: list[dict[str, Any]] = []; month_meta: dict[str, Any] = {}
    for month in MONTHS:
        try:
            candidates, meta = scan_month(month, catalog)
            all_candidates.extend(candidates); month_meta[f"2025-{month:02d}"] = meta
        except Exception as exc:
            month_meta[f"2025-{month:02d}"] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"2025-{month:02d}: ERROR {exc}", flush=True)
    all_candidates.sort(key=lambda item: item["score"], reverse=True)
    shortlisted = all_candidates[:MAX_CANDIDATES_FOR_VALIDATION]
    cache: dict[tuple[int, int], dict[str, Any]] = {}
    final: list[dict[str, Any]] = []
    for index, candidate in enumerate(shortlisted, start=1):
        print(f"Validating candidate {index}/{len(shortlisted)} month={candidate['month']:02d} n={candidate['members_2025']}...", flush=True)
        candidate["validation"] = {str(year): validate(candidate, year, cache) for year in VALIDATION_YEARS}
        both = all(item["passed"] for item in candidate["validation"].values())
        candidate["clone_stability"] = clone_stability(candidate) if both else {"passed": False, "not_run": True}
        candidate["novel_discovery_gate_passed"] = bool(both and candidate["clone_stability"]["passed"])
        if candidate["novel_discovery_gate_passed"]:
            final.append(candidate)
        print(f"  replication={both} clone={candidate['clone_stability'].get('passed')} final={candidate['novel_discovery_gate_passed']}", flush=True)
    verdict = "NOVEL_CANDIDATE_SURVIVES_FULL_GATE" if final else "NO_NOVEL_CANDIDATE_SURVIVES_FULL_GATE"
    result = {
        "pilot": "GhostStream", "stage": "all_season_novel_discovery_search", "verdict": verdict,
        "discovery_year": DISCOVERY_YEAR, "validation_years": VALIDATION_YEARS,
        "iau_catalog_url": IAU_URL, "iau_solutions_parsed": len(catalog),
        "months": month_meta, "prevalidation_candidates": len(all_candidates),
        "validated_candidates": len(shortlisted), "survivors": len(final),
        "familywise_upper_bound_from_two_year_rule": len(shortlisted) * (MAX_VALIDATION_P ** 2),
        "candidates": [serializable(item) for item in shortlisted],
    }
    (OUT / "ghoststream_novel_search.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    rows = []
    for item in shortlisted:
        row = {"month": item["month"], "members_2025": item["members_2025"], "score": item["score"],
               "solar_longitude": item["center"][3], "sun_centered_longitude": item["center"][0],
               "beta": item["center"][1], "vgeo": item["center"][2],
               "nearest_iau": item["nearest_iau"].get("code"),
               "rep2024": item["validation"]["2024"]["members"], "p2024": item["validation"]["2024"]["p"],
               "rep2023": item["validation"]["2023"]["members"], "p2023": item["validation"]["2023"]["p"],
               "clone_pass": item["clone_stability"].get("pass_fraction"),
               "survives": item["novel_discovery_gate_passed"]}
        rows.append(row)
    pd.DataFrame(rows).to_csv(OUT / "ghoststream_novel_candidates.csv", index=False)
    lines = ["# GhostStream all-season novel-discovery search", "", f"**Verdict:** `{verdict}`", "",
             f"- IAU solutions used as veto: **{len(catalog)}**", f"- 2025 months scanned: **{sum('error' not in x for x in month_meta.values())}/12**",
             f"- Uncatalogued 2025 structures before untouched-year validation: **{len(all_candidates)}**",
             f"- Candidates validated: **{len(shortlisted)}**", f"- Full-gate survivors: **{len(final)}**", "",
             "A full-gate survivor must be absent from every parsable IAU solution, repeat in both 2024 and 2023 at p <= 0.01, and pass 500 uncertainty-clone trials.", ""]
    for index, item in enumerate(shortlisted, start=1):
        lines += [f"## Candidate {index}", "",
                  f"- 2025 month/members: `{item['month']:02d}` / **{item['members_2025']}**",
                  f"- Center (solar longitude, sun-centered longitude, beta, Vg): **{item['center'][3]:.3f}, {item['center'][0]:.3f}, {item['center'][1]:.3f}, {item['center'][2]:.3f}**",
                  f"- Nearest IAU solution: `{item['nearest_iau'].get('code')}`; matched={item['nearest_iau'].get('matched')}",
                  f"- 2024: n={item['validation']['2024']['members']}, p={item['validation']['2024']['p']:.4f}, pass={item['validation']['2024']['passed']}",
                  f"- 2023: n={item['validation']['2023']['members']}, p={item['validation']['2023']['p']:.4f}, pass={item['validation']['2023']['passed']}",
                  f"- Uncertainty clones: {item['clone_stability'].get('pass_fraction', 'not run')}",
                  f"- Full gate: **{item['novel_discovery_gate_passed']}**", ""]
    (OUT / "GHOSTSTREAM_NOVEL_SEARCH.md").write_text("\n".join(lines))
    print(f"\nVerdict: {verdict}")
    print(f"Prevalidation candidates: {len(all_candidates)}")
    print(f"Validated candidates: {len(shortlisted)}")
    print(f"Full-gate survivors: {len(final)}")
    print(f"Report: {OUT / 'GHOSTSTREAM_NOVEL_SEARCH.md'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
