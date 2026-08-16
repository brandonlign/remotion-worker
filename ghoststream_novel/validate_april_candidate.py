#!/usr/bin/env python3
"""Rigorous audit of the frozen April 2026 GhostStream candidate.

The candidate template was frozen by the blind 2026 scan before this script.
This audit:
- deduplicates exact-time trajectory solutions conservatively;
- applies the same radiant/time/orbit template to April 2019--2026;
- tests solar-longitude enrichment within the local radiant-orbit population;
- audits observing nights, station IDs, and country-code diversity;
- performs leave-one-night and leave-one-station robustness checks;
- fits radiant and speed drift from deduplicated members;
- compares yearly orbital medoids and uncertainty clones;
- compares against every parsable IAU MDC shower solution by activity,
  drifted radiant, speed, and orbit.

A positive result remains a discovery *candidate*, not an official discovery.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import warnings
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader

OUT = Path("ghoststream_april_validation")
IAU_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamfulldata2026.txt"
SEED = 20260731
YEARS = tuple(range(2019, 2027))
MONTH = 4
NULL_DRAWS = 999
BOOTSTRAPS = 1000
CLONE_DRAWS = 1000

# Frozen from blind April 2026 candidate cluster 429.
CENTER = np.asarray([-149.297555, 7.45007, 37.42224, 36.901963], dtype=float)
SIGMA = np.asarray([0.881190723, 0.579296298, 1.099081032, 1.329624591], dtype=float)
ORBIT_MEDOID = np.asarray([0.950783, 0.073747, 25.286643, 334.338586, 37.363391], dtype=float)
RADIANT_RADIUS2 = 9.0
ORBIT_LOCAL_D = 0.20
ORBIT_MEMBER_D = 0.15
TEMPORAL_WIDTH = max(3.0 * SIGMA[3], 1.0)
MIN_YEAR_MEMBERS = 8
MAX_YEAR_P = 0.01
MAX_YEAR_MEDIAN_D = 0.12
MAX_CROSS_YEAR_MEDOID_D = 0.12
MIN_TOTAL_UNIQUE_MEMBERS = 35
MIN_SIGNIFICANT_YEARS = 3
MIN_UNTOUCHED_YEARS = 2  # 2019--2023 are untouched by discovery/model development.
MIN_NIGHTS = 4
MIN_STATIONS = 8
MAX_TOP_NIGHT_FRACTION = 0.50
MAX_TOP_STATION_FRACTION = 0.70
MIN_JACKKNIFE_RETAINED = 0.60
MAX_CLONE_MEDIAN_D = 0.10
MAX_CLONE_Q90_D = 0.20
MIN_CLONE_PASS = 0.80

ORBIT_COLUMNS = ["e", "q_au", "i_deg", "peri_deg", "node_deg"]
SIGMA_COLUMNS = ["sigma_9", "sigma_15", "sigma_10", "sigma_11", "sigma_12"]
BASE_COLUMNS = [
    "unique_trajectory_identifier", "beginning_utc_time", "iau_code",
    "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
    *ORBIT_COLUMNS, *SIGMA_COLUMNS,
    "medianfiterr_arcsec", "num_stat", "participating_stations",
]


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


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


def event_key(value: Any) -> str:
    text = str(value)
    match = re.match(r"(\d{14})", text)
    return match.group(1) if match else text


def station_ids(value: Any) -> set[str]:
    text = str(value).upper()
    # GMN station IDs generally use a two-letter country prefix followed by
    # four or more alphanumeric characters. Keep this strict to avoid counting
    # punctuation, Python-list syntax, or words as stations.
    found = set(re.findall(r"(?<![A-Z0-9])[A-Z]{2}[A-Z0-9]{4,8}(?![A-Z0-9])", text))
    return found


def country_codes(stations: set[str]) -> set[str]:
    return {station[:2] for station in stations if len(station) >= 2}


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
    valid &= (values[:, 0] >= 0.0) & (values[:, 0] < 1.5)
    valid &= (values[:, 1] > 0.0) & (values[:, 1] < 2.0)
    valid &= (values[:, 2] >= 0.0) & (values[:, 2] <= 180.0)
    return valid


def orbit_summary(orbits: np.ndarray) -> dict[str, Any]:
    matrix = orbit_distance_matrix(orbits)
    index = int(np.argmin(np.median(matrix, axis=1)))
    distances = matrix[index]
    return {
        "medoid": orbits[index],
        "median_d": float(np.median(distances)),
        "q90_d": float(np.percentile(distances, 90)),
    }


def deduplicate(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    data = frame.copy()
    data["event_key"] = data["unique_trajectory_identifier"].map(event_key)
    data["_fit"] = pd.to_numeric(data["medianfiterr_arcsec"], errors="coerce").fillna(1e9)
    data["_nst"] = pd.to_numeric(data["num_stat"], errors="coerce").fillna(0)
    data = data.sort_values(["event_key", "_fit", "_nst"], ascending=[True, True, False])
    counts = data["event_key"].value_counts()
    duplicate_groups = counts[counts > 1]
    examples = []
    for key in duplicate_groups.head(20).index:
        group = data.loc[data["event_key"] == key]
        examples.append({
            "event_key": str(key),
            "solutions": int(len(group)),
            "trajectory_ids": group["unique_trajectory_identifier"].astype(str).tolist(),
            "station_strings": group["participating_stations"].astype(str).tolist(),
        })
    output = data.drop_duplicates("event_key", keep="first").drop(columns=["_fit", "_nst"]).reset_index(drop=True)
    return output, {
        "before": int(len(frame)), "after": int(len(output)),
        "removed": int(len(frame) - len(output)),
        "duplicate_groups": int(len(duplicate_groups)),
        "examples": examples,
    }


def load_year(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    stamp = f"{year}-{MONTH:02d}"
    print(f"Downloading {stamp}...", flush=True)
    frame = reader.read_data(dd.get_monthly_file_content_by_date(stamp), output_camel_case=True).reset_index(drop=False)
    missing = [column for column in BASE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{stamp} missing columns: {missing}")
    data = frame[BASE_COLUMNS].copy()
    data["label"] = data["iau_code"].map(shower_label)
    for column in ["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s", *ORBIT_COLUMNS,
                   *SIGMA_COLUMNS, "medianfiterr_arcsec", "num_stat"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = np.isfinite(data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]).all(axis=1)
    valid &= data["sol_lon_deg"].between(0, 360) & data["lamgeo_deg"].between(0, 360)
    valid &= data["betgeo_deg"].between(-90, 90) & data["vgeo_km_s"].between(5, 75)
    valid &= data["num_stat"].fillna(0) >= 2
    valid &= data["medianfiterr_arcsec"].fillna(9999) <= 180
    quality = data.loc[valid & (data["label"] == "SPORADIC")].reset_index(drop=True)
    deduped, audit = deduplicate(quality)
    audit["raw_month_rows"] = int(len(frame))
    audit["quality_sporadic_rows"] = int(len(quality))
    return deduped, audit


def select_members(data: pd.DataFrame) -> dict[str, Any]:
    sunlon = circ_diff(data["lamgeo_deg"].to_numpy(float), data["sol_lon_deg"].to_numpy(float))
    radiant_score = ((circ_diff(sunlon, CENTER[0]) / SIGMA[0]) ** 2
                     + ((data["betgeo_deg"].to_numpy(float) - CENTER[1]) / SIGMA[1]) ** 2
                     + ((data["vgeo_km_s"].to_numpy(float) - CENTER[2]) / SIGMA[2]) ** 2)
    orbit_mask = valid_orbits(data)
    orbit_d = np.full(len(data), np.inf)
    orbit_d[orbit_mask] = orbit_distance_matrix(
        data.loc[orbit_mask, ORBIT_COLUMNS].to_numpy(float), ORBIT_MEDOID[None, :]
    )[:, 0]
    local = (radiant_score <= RADIANT_RADIUS2) & (orbit_d <= ORBIT_LOCAL_D)
    temporal = np.abs(circ_diff(data["sol_lon_deg"].to_numpy(float), CENTER[3])) <= TEMPORAL_WIDTH
    selected = local & temporal & (orbit_d <= ORBIT_MEMBER_D)
    members = data.loc[selected].copy().reset_index(drop=True)
    members["sun_centered_lon"] = circ_diff(members["lamgeo_deg"].to_numpy(float), members["sol_lon_deg"].to_numpy(float))
    members["orbit_d_to_frozen"] = orbit_d[selected]
    dates = pd.to_datetime(members["beginning_utc_time"], errors="coerce", utc=True).dt.floor("D")
    members["night"] = dates.astype(str)
    station_sets = members["participating_stations"].map(station_ids)
    members["parsed_station_ids"] = station_sets.map(lambda value: ";".join(sorted(value)))
    all_stations = set().union(*station_sets.tolist()) if len(station_sets) else set()
    all_countries = country_codes(all_stations)
    station_counts: Counter[str] = Counter()
    country_counts: Counter[str] = Counter()
    for stations in station_sets:
        station_counts.update(stations)
        country_counts.update(country_codes(stations))
    night_counts = dates.value_counts()
    orbit = orbit_summary(members.loc[valid_orbits(members), ORBIT_COLUMNS].to_numpy(float)) if valid_orbits(members).sum() >= 2 else None
    return {
        "members": members,
        "selected_count": int(len(members)),
        "local_pool_count": int(local.sum()),
        "nights": int(len(night_counts)),
        "stations": int(len(all_stations)),
        "countries": int(len(all_countries)),
        "station_ids": sorted(all_stations),
        "country_codes": sorted(all_countries),
        "station_counts": dict(station_counts),
        "country_counts": dict(country_counts),
        "night_counts": {str(key): int(value) for key, value in night_counts.items()},
        "top_night_fraction": float(night_counts.iloc[0] / len(members)) if len(members) else 1.0,
        "top_station_fraction": float(max(station_counts.values()) / len(members)) if station_counts and len(members) else 1.0,
        "orbit": orbit,
        "local_mask": local,
        "selected_mask": selected,
    }


def temporal_null(data: pd.DataFrame, selection: dict[str, Any], year: int) -> dict[str, Any]:
    local_mask = selection["local_mask"]
    local_sol = data.loc[local_mask, "sol_lon_deg"].to_numpy(float)
    observed = selection["selected_count"]
    if len(local_sol) == 0:
        return {"p": 1.0, "null_q99": 0.0, "null_max": 0}
    all_sol = data["sol_lon_deg"].to_numpy(float)
    rng = np.random.default_rng(SEED + year)
    null = []
    for _ in range(NULL_DRAWS):
        sampled = all_sol[rng.choice(len(all_sol), size=len(local_sol), replace=False)] if len(local_sol) <= len(all_sol) else all_sol
        null.append(int(np.sum(np.abs(circ_diff(sampled, CENTER[3])) <= TEMPORAL_WIDTH)))
    p = (1 + sum(value >= observed for value in null)) / (NULL_DRAWS + 1)
    return {
        "p": float(p),
        "null_q99": float(np.percentile(null, 99)),
        "null_max": int(max(null)),
    }


def jackknife(selection: dict[str, Any]) -> dict[str, Any]:
    members = selection["members"]
    total = len(members)
    if total == 0:
        return {"passed": False, "reason": "no_members"}
    night_min = total
    for night in members["night"].unique():
        night_min = min(night_min, int((members["night"] != night).sum()))
    station_min = total
    station_counts = Counter(selection["station_counts"])
    for station, _ in station_counts.most_common(20):
        keep = ~members["parsed_station_ids"].map(lambda value: station in value.split(";") if value else False)
        station_min = min(station_min, int(keep.sum()))
    retained = min(night_min, station_min) / total
    passed = (
        selection["top_night_fraction"] <= MAX_TOP_NIGHT_FRACTION
        and selection["top_station_fraction"] <= MAX_TOP_STATION_FRACTION
        and retained >= MIN_JACKKNIFE_RETAINED
    )
    return {
        "night_min_members": int(night_min),
        "station_min_members": int(station_min),
        "minimum_retained_fraction": float(retained),
        "passed": bool(passed),
    }


def linear_fit(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    centered = circ_diff(x, CENTER[3]).astype(float)
    slope, intercept = np.polyfit(centered, y, 1)
    residuals = y - (intercept + slope * centered)
    rng = np.random.default_rng(SEED + int(abs(float(np.mean(y))) * 1000) % 100000)
    boot_slopes = []
    for _ in range(BOOTSTRAPS):
        idx = rng.choice(len(x), size=len(x), replace=True)
        if np.std(centered[idx]) < 1e-8:
            continue
        boot_slopes.append(float(np.polyfit(centered[idx], y[idx], 1)[0]))
    return {
        "value_at_center": float(intercept),
        "slope_per_solar_degree": float(slope),
        "slope_ci95": [float(np.percentile(boot_slopes, 2.5)), float(np.percentile(boot_slopes, 97.5))] if boot_slopes else [None, None],
        "residual_sigma": float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0,
    }


def drift_fit(all_members: pd.DataFrame) -> dict[str, Any]:
    sol = all_members["sol_lon_deg"].to_numpy(float)
    sunlon = all_members["sun_centered_lon"].to_numpy(float)
    # unwrap around the frozen center before linear fitting
    sunlon_unwrapped = CENTER[0] + circ_diff(sunlon, CENTER[0])
    return {
        "sun_centered_longitude": linear_fit(sol, sunlon_unwrapped),
        "ecliptic_latitude": linear_fit(sol, all_members["betgeo_deg"].to_numpy(float)),
        "geocentric_speed": linear_fit(sol, all_members["vgeo_km_s"].to_numpy(float)),
    }


def clone_stability(all_members: pd.DataFrame) -> dict[str, Any]:
    mask = valid_orbits(all_members)
    values = all_members.loc[mask, ORBIT_COLUMNS].to_numpy(float)
    sigmas = all_members.loc[mask, SIGMA_COLUMNS].to_numpy(float)
    if len(values) < MIN_TOTAL_UNIQUE_MEMBERS:
        return {"passed": False, "reason": "too_few_members", "members": int(len(values))}
    sigmas = np.nan_to_num(np.abs(sigmas), nan=0.0, posinf=0.0, neginf=0.0)
    sigmas = np.minimum(sigmas, np.asarray([0.10, 0.10, 10.0, 20.0, 5.0])[None, :])
    rng = np.random.default_rng(SEED + 999)
    medians, q90s = [], []
    passed = 0
    for _ in range(CLONE_DRAWS):
        clone = values + rng.normal(size=values.shape) * sigmas
        clone[:, 0] = np.clip(clone[:, 0], 0.0, 1.49)
        clone[:, 1] = np.clip(clone[:, 1], 0.01, 1.99)
        clone[:, 2] = np.clip(clone[:, 2], 0.0, 180.0)
        clone[:, 3:] %= 360.0
        summary = orbit_summary(clone)
        medians.append(summary["median_d"]); q90s.append(summary["q90_d"])
        if summary["median_d"] <= MAX_CLONE_MEDIAN_D and summary["q90_d"] <= MAX_CLONE_Q90_D:
            passed += 1
    fraction = passed / CLONE_DRAWS
    return {
        "draws": CLONE_DRAWS,
        "pass_fraction": float(fraction),
        "median_clone_median_d": float(np.median(medians)),
        "median_clone_q90_d": float(np.median(q90s)),
        "passed": bool(fraction >= MIN_CLONE_PASS),
    }


def ecliptic_to_equatorial(lam_deg: float, beta_deg: float) -> tuple[float, float]:
    lam, beta, eps = np.deg2rad([lam_deg, beta_deg, 23.43928])
    x = np.cos(beta) * np.cos(lam); y = np.cos(beta) * np.sin(lam); z = np.sin(beta)
    ye = y * np.cos(eps) - z * np.sin(eps); ze = y * np.sin(eps) + z * np.cos(eps)
    return float(np.rad2deg(np.arctan2(ye, x)) % 360.0), float(np.rad2deg(np.arcsin(np.clip(ze, -1, 1))))


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a1, d1, a2, d2 = np.deg2rad([ra1, dec1, ra2, dec2])
    cosine = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(a1 - a2)
    return float(np.rad2deg(np.arccos(np.clip(cosine, -1.0, 1.0))))


def active_at(sol: float, start: float | None, end: float | None, mean: float, pad: float = 3.0) -> bool:
    if start is None or end is None:
        return abs(float(circ_diff(sol, mean))) <= 12.0
    span = (end - start) % 360.0
    phase = (sol - start) % 360.0
    return bool(phase <= span or abs(float(circ_diff(sol, start))) <= pad or abs(float(circ_diff(sol, end))) <= pad)


def parse_iau() -> list[dict[str, Any]]:
    response = requests.get(IAU_URL, timeout=60)
    response.raise_for_status()
    output = []
    for line in response.text.splitlines():
        if "|" not in line or not line.lstrip().startswith('"'):
            continue
        try:
            row = next(csv.reader(io.StringIO(line), delimiter="|", quotechar='"'))
        except Exception:
            continue
        if len(row) < 29:
            continue
        sol, ra, dec, vg = number(row[10]), number(row[11]), number(row[12]), number(row[15])
        if None in {sol, ra, dec, vg}:
            continue
        e, q, peri, node, inc = number(row[24]), number(row[23]), number(row[25]), number(row[26]), number(row[27])
        orbit = None if None in {e, q, peri, node, inc} else np.asarray([e, q, inc, peri, node], dtype=float)
        output.append({
            "iau_no": row[1].strip(' "'), "code": row[3].strip(' "'),
            "status": int(number(row[4]) or 0), "name": row[6].strip(' "'),
            "sol_start": number(row[8]), "sol_end": number(row[9]), "sol": float(sol),
            "ra": float(ra), "dec": float(dec), "dra": number(row[13]), "ddec": number(row[14]),
            "vg": float(vg), "orbit": orbit,
        })
    if len(output) < 1500:
        raise RuntimeError(f"Only {len(output)} IAU solutions parsed")
    return output


def catalog_audit(catalog: list[dict[str, Any]], refined_orbit: np.ndarray) -> dict[str, Any]:
    lam = (CENTER[3] + CENTER[0]) % 360.0
    ra, dec = ecliptic_to_equatorial(lam, CENTER[1])
    rows = []
    for item in catalog:
        delta = float(circ_diff(CENTER[3], item["sol"]))
        predicted_ra = (item["ra"] + (item["dra"] or 0.0) * delta) % 360.0
        predicted_dec = item["dec"] + (item["ddec"] or 0.0) * delta
        sky = angular_separation(ra, dec, predicted_ra, predicted_dec)
        speed_delta = abs(CENTER[2] - item["vg"])
        orbit_d = None if item["orbit"] is None else float(orbit_distance_matrix(refined_orbit[None, :], item["orbit"][None, :])[0, 0])
        active = active_at(CENTER[3], item["sol_start"], item["sol_end"], item["sol"])
        combined = ((0.0 if active else 4.0) + (sky / 5.0) ** 2 + (speed_delta / 5.0) ** 2
                    + ((orbit_d / 0.20) ** 2 if orbit_d is not None else 1.0))
        hard_match = bool(active and speed_delta <= 6.0 and (
            (orbit_d is not None and orbit_d <= 0.12)
            or (sky <= 5.0 and (orbit_d is None or orbit_d <= 0.25))
        ))
        rows.append({
            "iau_no": item["iau_no"], "code": item["code"], "name": item["name"],
            "status": item["status"], "active": active,
            "solar_delta_from_mean": abs(delta), "sky_distance_with_drift_deg": sky,
            "speed_delta_km_s": speed_delta, "orbit_d": orbit_d,
            "combined_score": combined, "hard_match": hard_match,
        })
    by_combined = sorted(rows, key=lambda row: row["combined_score"])[:25]
    by_orbit = sorted([row for row in rows if row["orbit_d"] is not None], key=lambda row: row["orbit_d"])[:25]
    by_sky = sorted(rows, key=lambda row: (not row["active"], row["sky_distance_with_drift_deg"], row["speed_delta_km_s"]))[:25]
    hard = [row for row in rows if row["hard_match"]]
    return {
        "candidate_ra_deg": ra, "candidate_dec_deg": dec,
        "hard_match_count": int(len(hard)), "hard_matches": hard,
        "nearest_combined": by_combined,
        "nearest_orbit": by_orbit,
        "nearest_active_radiant": by_sky,
    }


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def main() -> int:
    OUT.mkdir(exist_ok=True)
    yearly: dict[str, Any] = {}
    member_frames = []
    dedup_audits = {}
    for year in YEARS:
        data, audit = load_year(year)
        selection = select_members(data)
        null = temporal_null(data, selection, year)
        significant = bool(
            selection["selected_count"] >= MIN_YEAR_MEMBERS
            and null["p"] <= MAX_YEAR_P
            and selection["orbit"] is not None
            and selection["orbit"]["median_d"] <= MAX_YEAR_MEDIAN_D
        )
        selection["temporal_null"] = null
        selection["significant"] = significant
        selection["jackknife"] = jackknife(selection)
        dedup_audits[str(year)] = audit
        members = selection["members"].copy()
        members["year"] = year
        member_frames.append(members)
        yearly[str(year)] = {key: value for key, value in selection.items() if key not in {"members", "local_mask", "selected_mask"}}
        print(
            f"{year}: unique={len(data):,} members={selection['selected_count']} local={selection['local_pool_count']} "
            f"nights={selection['nights']} stations={selection['stations']} countries={selection['countries']} "
            f"p={null['p']:.4g} medianD={selection['orbit']['median_d'] if selection['orbit'] else None} "
            f"significant={significant}", flush=True
        )

    all_members = pd.concat(member_frames, ignore_index=True, sort=False)
    # A second global exact-time dedup is harmless across years and documents that
    # no event appears twice after per-year deduplication.
    all_members, global_dedup = deduplicate(all_members)
    all_orbits = all_members.loc[valid_orbits(all_members), ORBIT_COLUMNS].to_numpy(float)
    overall_orbit = orbit_summary(all_orbits)
    drift = drift_fit(all_members)
    clones = clone_stability(all_members)

    significant_years = [int(year) for year, result in yearly.items() if result["significant"]]
    untouched_significant = [year for year in significant_years if year <= 2023]
    yearly_medoids = {
        int(year): np.asarray(result["orbit"]["medoid"], dtype=float)
        for year, result in yearly.items() if result["significant"] and result["orbit"] is not None
    }
    cross_year = []
    for i, year_a in enumerate(sorted(yearly_medoids)):
        for year_b in sorted(yearly_medoids)[i + 1:]:
            distance = float(orbit_distance_matrix(yearly_medoids[year_a][None, :], yearly_medoids[year_b][None, :])[0, 0])
            cross_year.append({"year_a": year_a, "year_b": year_b, "d": distance})
    max_cross_year_d = max((item["d"] for item in cross_year), default=999.0)

    catalog = parse_iau()
    catalog_result = catalog_audit(catalog, np.asarray(overall_orbit["medoid"], dtype=float))

    years_2024_2026_robust = all(
        yearly[str(year)]["jackknife"]["passed"]
        and yearly[str(year)]["nights"] >= MIN_NIGHTS
        and yearly[str(year)]["stations"] >= MIN_STATIONS
        for year in (2024, 2025, 2026)
    )
    discovery_candidate_passed = bool(
        len(all_members) >= MIN_TOTAL_UNIQUE_MEMBERS
        and len(significant_years) >= MIN_SIGNIFICANT_YEARS
        and len(untouched_significant) >= MIN_UNTOUCHED_YEARS
        and max_cross_year_d <= MAX_CROSS_YEAR_MEDOID_D
        and years_2024_2026_robust
        and clones["passed"]
        and catalog_result["hard_match_count"] == 0
    )
    verdict = "APRIL_STREAM_DISCOVERY_CANDIDATE_SURVIVES_AUDIT" if discovery_candidate_passed else "APRIL_STREAM_CANDIDATE_FAILS_AUDIT"

    # Save exact deduplicated members for independent review.
    member_columns = [
        "year", "event_key", "unique_trajectory_identifier", "beginning_utc_time",
        "sol_lon_deg", "sun_centered_lon", "betgeo_deg", "vgeo_km_s",
        *ORBIT_COLUMNS, "orbit_d_to_frozen", "num_stat", "medianfiterr_arcsec",
        "participating_stations", "parsed_station_ids", "night",
    ]
    all_members[member_columns].to_csv(OUT / "april_candidate_members.csv", index=False)

    payload = {
        "stage": "frozen_april_2026_candidate_audit",
        "verdict": verdict,
        "discovery_candidate_passed": discovery_candidate_passed,
        "frozen_template": {
            "center": CENTER, "sigma": SIGMA, "orbit_medoid": ORBIT_MEDOID,
            "temporal_width_deg": TEMPORAL_WIDTH,
            "radiant_radius_squared": RADIANT_RADIUS2,
            "orbit_member_d": ORBIT_MEMBER_D,
        },
        "deduplication": {
            "per_year": dedup_audits,
            "global": global_dedup,
            "rule": "one best-quality solution per 14-digit UTC prefix",
        },
        "yearly": yearly,
        "total_unique_members": int(len(all_members)),
        "significant_years": significant_years,
        "untouched_significant_years": untouched_significant,
        "overall_orbit": overall_orbit,
        "cross_year_medoid_distances": cross_year,
        "maximum_cross_year_medoid_d": float(max_cross_year_d),
        "radiant_speed_drift": drift,
        "uncertainty_clones": clones,
        "iau_catalog": {"url": IAU_URL, "solutions_parsed": len(catalog), **catalog_result},
        "gate_components": {
            "minimum_total_members": len(all_members) >= MIN_TOTAL_UNIQUE_MEMBERS,
            "minimum_significant_years": len(significant_years) >= MIN_SIGNIFICANT_YEARS,
            "minimum_untouched_years": len(untouched_significant) >= MIN_UNTOUCHED_YEARS,
            "cross_year_orbit_consistency": max_cross_year_d <= MAX_CROSS_YEAR_MEDOID_D,
            "recent_year_night_station_robustness": years_2024_2026_robust,
            "uncertainty_clone_stability": clones["passed"],
            "no_hard_iau_match": catalog_result["hard_match_count"] == 0,
        },
    }
    (OUT / "april_candidate_validation.json").write_text(json.dumps(jsonable(payload), indent=2) + "\n")

    lines = [
        "# GhostStream April candidate validation", "",
        f"**Verdict:** `{verdict}`", "",
        f"- Deduplicated members, 2019–2026: **{len(all_members)}**",
        f"- Significant years: **{significant_years}**",
        f"- Untouched significant years (≤2023): **{untouched_significant}**",
        f"- Overall median orbital distance: **{overall_orbit['median_d']:.5f}**",
        f"- Maximum significant-year medoid distance: **{max_cross_year_d:.5f}**",
        f"- Uncertainty-clone pass fraction: **{clones.get('pass_fraction')}**",
        f"- Hard IAU catalog matches: **{catalog_result['hard_match_count']}**", "",
        "## Year-by-year", "",
        "| Year | Members | Local pool | Nights | Stations | Countries | p-value | Median D | Significant |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for year in YEARS:
        result = yearly[str(year)]
        median_d = result["orbit"]["median_d"] if result["orbit"] else None
        lines.append(
            f"| {year} | {result['selected_count']} | {result['local_pool_count']} | {result['nights']} | "
            f"{result['stations']} | {result['countries']} | {result['temporal_null']['p']:.4g} | "
            f"{median_d if median_d is not None else '—'} | {result['significant']} |"
        )
    lines += ["", "## Nearest official solutions", ""]
    for item in catalog_result["nearest_combined"][:10]:
        lines.append(
            f"- `{item['code']}` {item['name']}: active={item['active']}, sky={item['sky_distance_with_drift_deg']:.3f}°, "
            f"ΔV={item['speed_delta_km_s']:.3f} km/s, D={item['orbit_d']}, hard_match={item['hard_match']}"
        )
    lines += ["", "A passing result is a high-priority discovery candidate, not an official discovery. Independent catalog/network and expert validation remain required.", ""]
    (OUT / "APRIL_CANDIDATE_VALIDATION.md").write_text("\n".join(lines))

    print(f"\nVerdict: {verdict}")
    print(f"Total unique members: {len(all_members)}")
    print(f"Significant years: {significant_years}")
    print(f"Untouched significant years: {untouched_significant}")
    print(f"Hard IAU matches: {catalog_result['hard_match_count']}")
    print(f"Report: {OUT / 'APRIL_CANDIDATE_VALIDATION.md'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
