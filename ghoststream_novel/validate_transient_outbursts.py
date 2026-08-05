#!/usr/bin/env python3
"""Confirmatory test for one-time meteor-shower outbursts.

The five candidate templates were frozen by the 2025 all-season blind search.
This script does not require annual recurrence. Instead, it requires a large
2025 excess relative to the same local radiant-orbit population in untouched
2024 and 2023 data, a conservative veto against every IAU MDC solution,
robustness to individual observing nights and stations, and stability under
reported orbit uncertainties.
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
from scipy.stats import fisher_exact

SEED = 20260731
YEARS = (2025, 2024, 2023)
IAU_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamfulldata2026.txt"
OUT = Path("ghoststream_transient_results")
ORBIT_COLUMNS = ["e", "q_au", "i_deg", "peri_deg", "node_deg"]
SIGMA_COLUMNS = ["sigma_9", "sigma_15", "sigma_10", "sigma_11", "sigma_12"]
BASE_COLUMNS = [
    "unique_trajectory_identifier", "beginning_utc_time", "iau_code",
    "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
    *ORBIT_COLUMNS, *SIGMA_COLUMNS,
    "medianfiterr_arcsec", "num_stat", "participating_stations",
]
N_TESTS = 5
ALPHA = 0.01 / N_TESTS
MIN_2025_MEMBERS = 12
MIN_NIGHTS = 4
MIN_STATIONS = 8
MIN_EXCESS_RATIO = 2.0
MAX_PRIOR_TO_2025_RATIO = 0.75
MAX_ORBIT_MEDIAN_D = 0.10
MAX_ORBIT_Q90_D = 0.20
MIN_CLONE_PASS = 0.80
CLONE_DRAWS = 500
MAX_TOP_NIGHT_FRACTION = 0.50
MAX_TOP_STATION_FRACTION = 0.50
MIN_JACKKNIFE_RETAINED = 0.60

# Frozen from the drift-aware 2025 blind scan before this confirmatory test.
CANDIDATES = [
    {"name": "GS-T-2025-01", "month": 1, "members_blind": 28,
     "center": [-175.85933, -61.28954, 26.84882, 285.8765025],
     "sigma": [2.7741766269, 1.3834585380, 0.83826204, 1.1213637687],
     "orbit": [0.784883, 0.867992, 38.485728, 42.834541, 106.320665]},
    {"name": "GS-T-2025-03A", "month": 3, "members_blind": 66,
     "center": [-148.779991, -35.314615, 45.013655, 0.914641],
     "sigma": [0.9025950192, 1.5754997160, 1.1220983970, 1.7667958875],
     "orbit": [0.986276, 0.441992, 67.621832, 96.923966, 181.410897]},
    {"name": "GS-T-2025-03B", "month": 3, "members_blind": 18,
     "center": [104.1364435, 64.68648, 13.92342, 359.02425],
     "sigma": [3.0868006281, 1.7331149220, 0.3218279820, 0.9714595653],
     "orbit": [0.6136, 0.994005, 19.234296, 185.156237, 358.352148]},
    {"name": "GS-T-2025-06", "month": 6, "members_blind": 16,
     "center": [-170.14138, -62.707035, 31.39664, 85.762324],
     "sigma": [2.3388563562, 0.8098257720, 1.2372000480, 0.6978279441],
     "orbit": [0.971625, 0.896915, 45.935661, 40.331984, 266.052752]},
    {"name": "GS-T-2025-08", "month": 8, "members_blind": 43,
     "center": [157.491643, 32.66859, 16.11293, 150.756813],
     "sigma": [1.4275777488, 1.4670920040, 0.8591667, 1.5032778222],
     "orbit": [0.679287, 0.87609, 13.479146, 227.926383, 150.771617]},
    {"name": "GS-T-2025-09", "month": 9, "members_blind": 36,
     "center": [137.7114745, 56.3895, 14.96874, 172.4388715],
     "sigma": [2.0552549913, 0.7381791270, 0.39844875, 1.1583739125],
     "orbit": [0.634714, 0.965206, 19.145025, 206.346265, 171.847455]},
]
N_TESTS = len(CANDIDATES)
ALPHA = 0.01 / N_TESTS


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


def station_tokens(value: Any) -> set[str]:
    return {token for token in re.split(r"[^A-Za-z0-9]+", str(value).upper()) if len(token) >= 4}


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
    return {"medoid": orbits[idx], "median_d": float(np.median(distances)),
            "q90_d": float(np.percentile(distances, 90))}


def ecliptic_to_equatorial(lam_deg: float, beta_deg: float) -> tuple[float, float]:
    lam, beta, eps = np.deg2rad([lam_deg, beta_deg, 23.43928])
    x = np.cos(beta) * np.cos(lam); y = np.cos(beta) * np.sin(lam); z = np.sin(beta)
    ye = y * np.cos(eps) - z * np.sin(eps); ze = y * np.sin(eps) + z * np.cos(eps)
    return float(np.rad2deg(np.arctan2(ye, x)) % 360.0), float(np.rad2deg(np.arcsin(np.clip(ze, -1, 1))))


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a1, d1, a2, d2 = np.deg2rad([ra1, dec1, ra2, dec2])
    cosine = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(a1 - a2)
    return float(np.rad2deg(np.arccos(np.clip(cosine, -1, 1))))


def active_at(sol: float, start: float | None, end: float | None, mean: float, pad: float = 3.0) -> bool:
    if start is None or end is None:
        return abs(float(circ_diff(sol, mean))) <= 12.0
    span = (end - start) % 360.0; phase = (sol - start) % 360.0
    return phase <= span or abs(float(circ_diff(sol, start))) <= pad or abs(float(circ_diff(sol, end))) <= pad


def parse_iau() -> list[dict[str, Any]]:
    text = requests.get(IAU_URL, timeout=60).text
    output = []
    for line in text.splitlines():
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
        output.append({"code": row[3].strip(' "'), "name": row[6].strip(' "'),
                       "status": int(number(row[4]) or 0), "sol": float(sol),
                       "sol_start": number(row[8]), "sol_end": number(row[9]),
                       "ra": float(ra), "dec": float(dec), "dra": number(row[13]), "ddec": number(row[14]),
                       "vg": float(vg), "orbit": orbit})
    if len(output) < 1500:
        raise RuntimeError(f"Only {len(output)} IAU solutions parsed")
    return output


def conservative_iau_veto(candidate: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    center = np.asarray(candidate["center"], dtype=float); orbit = np.asarray(candidate["orbit"], dtype=float)
    ra, dec = ecliptic_to_equatorial((center[3] + center[0]) % 360.0, center[1])
    matches = []
    for item in catalog:
        if not active_at(center[3], item["sol_start"], item["sol_end"], item["sol"]):
            continue
        delta = float(circ_diff(center[3], item["sol"]))
        pra = (item["ra"] + (item["dra"] or 0.0) * delta) % 360.0
        pdec = item["dec"] + (item["ddec"] or 0.0) * delta
        sky = angular_separation(ra, dec, pra, pdec); speed = abs(center[2] - item["vg"])
        od = None if item["orbit"] is None else float(orbit_distance_matrix(orbit[None, :], item["orbit"][None, :])[0, 0])
        matched = speed <= 6.0 and ((od is not None and od <= 0.12) or (sky <= 7.0 and (od is None or od <= 0.25)))
        if matched:
            matches.append({"code": item["code"], "name": item["name"], "status": item["status"],
                            "sky_deg": sky, "speed_delta": speed, "orbit_d": od})
    matches.sort(key=lambda x: ((x["orbit_d"] if x["orbit_d"] is not None else 1.0), x["sky_deg"]))
    return {"vetoed": bool(matches), "matches": matches[:10]}


def load(year: int, month: int, cache: dict[tuple[int, int], pd.DataFrame]) -> pd.DataFrame:
    key = (year, month)
    if key in cache:
        return cache[key]
    stamp = f"{year}-{month:02d}"; print(f"Downloading {stamp}...", flush=True)
    frame = reader.read_data(dd.get_monthly_file_content_by_date(stamp), output_camel_case=True).reset_index(drop=False)
    missing = [column for column in BASE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{stamp} missing {missing}")
    data = frame[BASE_COLUMNS].copy(); data["label"] = data["iau_code"].map(shower_label)
    for column in ["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s", *ORBIT_COLUMNS, *SIGMA_COLUMNS,
                   "medianfiterr_arcsec", "num_stat"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = np.isfinite(data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]).all(axis=1)
    valid &= data["sol_lon_deg"].between(0, 360) & data["lamgeo_deg"].between(0, 360)
    valid &= data["betgeo_deg"].between(-90, 90) & data["vgeo_km_s"].between(5, 75)
    valid &= data["num_stat"].fillna(0) >= 2
    valid &= data["medianfiterr_arcsec"].fillna(9999) <= 180
    data = data.loc[valid & (data["label"] == "SPORADIC")].reset_index(drop=True)
    cache[key] = data
    return data


def select(data: pd.DataFrame, candidate: dict[str, Any]) -> dict[str, Any]:
    center = np.asarray(candidate["center"], dtype=float); sigma = np.maximum(np.asarray(candidate["sigma"]), 0.25)
    slon = circ_diff(data["lamgeo_deg"].to_numpy(float), data["sol_lon_deg"].to_numpy(float))
    radiant_score = ((circ_diff(slon, center[0]) / sigma[0]) ** 2
                     + ((data["betgeo_deg"].to_numpy(float) - center[1]) / sigma[1]) ** 2
                     + ((data["vgeo_km_s"].to_numpy(float) - center[2]) / sigma[2]) ** 2)
    orbit_mask = valid_orbits(data); orbit_d = np.full(len(data), np.inf)
    orbit_d[orbit_mask] = orbit_distance_matrix(data.loc[orbit_mask, ORBIT_COLUMNS].to_numpy(float),
                                                np.asarray(candidate["orbit"])[None, :])[:, 0]
    local = (radiant_score <= 9.0) & (orbit_d <= 0.20)
    temporal = np.abs(circ_diff(data["sol_lon_deg"].to_numpy(float), center[3])) <= max(3 * sigma[3], 1.0)
    selected = local & temporal & (orbit_d <= 0.15)
    members = data.loc[selected].copy().reset_index(drop=True)
    dates = pd.to_datetime(members["beginning_utc_time"], errors="coerce", utc=True).dt.floor("D")
    night_counts = dates.value_counts(); station_sets = members["participating_stations"].fillna("").astype(str)
    station_counts: dict[str, int] = {}
    for value in station_sets:
        for station in station_tokens(value):
            station_counts[station] = station_counts.get(station, 0) + 1
    stations = set(station_counts)
    summary = orbit_summary(members.loc[valid_orbits(members), ORBIT_COLUMNS].to_numpy(float)) if valid_orbits(members).sum() >= 2 else None
    return {"members": members, "selected": int(selected.sum()), "local_pool": int(local.sum()),
            "nights": int(len(night_counts)), "stations": int(len(stations)),
            "top_night_fraction": float(night_counts.iloc[0] / len(members)) if len(members) else 1.0,
            "top_station_fraction": float(max(station_counts.values()) / len(members)) if station_counts else 1.0,
            "orbit": summary, "station_counts": station_counts, "dates": dates}


def robustness(selection: dict[str, Any]) -> dict[str, Any]:
    members = selection["members"]; total = len(members)
    if total == 0:
        return {"passed": False}
    dates = selection["dates"]
    night_min = total
    for night in dates.dropna().unique():
        remain = members.loc[dates != night]
        night_min = min(night_min, len(remain))
    station_min = total
    for station, _ in sorted(selection["station_counts"].items(), key=lambda kv: kv[1], reverse=True)[:10]:
        keep = ~members["participating_stations"].fillna("").astype(str).map(lambda value: station in station_tokens(value))
        station_min = min(station_min, int(keep.sum()))
    retained = min(night_min, station_min) / total
    passed = (selection["top_night_fraction"] <= MAX_TOP_NIGHT_FRACTION
              and selection["top_station_fraction"] <= MAX_TOP_STATION_FRACTION
              and retained >= MIN_JACKKNIFE_RETAINED)
    return {"night_min_members": night_min, "station_min_members": station_min,
            "minimum_retained_fraction": retained, "passed": bool(passed)}


def clone_stability(selection: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    members = selection["members"]; mask = valid_orbits(members)
    values = members.loc[mask, ORBIT_COLUMNS].to_numpy(float)
    sigmas = members.loc[mask, SIGMA_COLUMNS].to_numpy(float)
    if len(values) < MIN_2025_MEMBERS:
        return {"passed": False, "reason": "too_few_valid_orbits"}
    sigmas = np.nan_to_num(np.abs(sigmas), nan=0.0, posinf=0.0, neginf=0.0)
    sigmas = np.minimum(sigmas, np.asarray([0.10, 0.10, 10.0, 20.0, 5.0])[None, :])
    rng = np.random.default_rng(SEED + candidate["month"] * 100 + len(values))
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
            "median_clone_dispersion": float(np.median(medians)), "passed": fraction >= MIN_CLONE_PASS}


def evaluate(candidate: dict[str, Any], catalog: list[dict[str, Any]], cache: dict[tuple[int, int], pd.DataFrame]) -> dict[str, Any]:
    veto = conservative_iau_veto(candidate, catalog)
    yearly = {str(year): select(load(year, candidate["month"], cache), candidate) for year in YEARS}
    y25, y24, y23 = yearly["2025"], yearly["2024"], yearly["2023"]
    prior_success = y24["selected"] + y23["selected"]
    prior_failure = max(0, y24["local_pool"] - y24["selected"]) + max(0, y23["local_pool"] - y23["selected"])
    table = [[y25["selected"], max(0, y25["local_pool"] - y25["selected"])], [prior_success, prior_failure]]
    odds, p = fisher_exact(table, alternative="greater") if sum(sum(row) for row in table) else (0.0, 1.0)
    frac25 = y25["selected"] / y25["local_pool"] if y25["local_pool"] else 0.0
    fracprior = prior_success / (y24["local_pool"] + y23["local_pool"]) if (y24["local_pool"] + y23["local_pool"]) else 0.0
    ratio = frac25 / max(fracprior, 1e-9)
    robust = robustness(y25)
    clones = clone_stability(y25, candidate) if not veto["vetoed"] else {"passed": False, "not_run_catalog_veto": True}
    orbit = y25["orbit"] or {"median_d": 999, "q90_d": 999}
    gate = (not veto["vetoed"] and y25["selected"] >= MIN_2025_MEMBERS
            and y25["nights"] >= MIN_NIGHTS and y25["stations"] >= MIN_STATIONS
            and orbit["median_d"] <= MAX_ORBIT_MEDIAN_D and orbit["q90_d"] <= MAX_ORBIT_Q90_D
            and p <= ALPHA and ratio >= MIN_EXCESS_RATIO
            and max(y24["selected"], y23["selected"]) <= MAX_PRIOR_TO_2025_RATIO * y25["selected"]
            and robust["passed"] and clones.get("passed", False))
    def compact(selection: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in selection.items() if key not in {"members", "station_counts", "dates"}}
    return {"candidate": candidate, "catalog_veto": veto,
            "yearly": {year: compact(value) for year, value in yearly.items()},
            "fisher_odds_ratio": float(odds), "fisher_p": float(p), "bonferroni_alpha": ALPHA,
            "fraction_2025": frac25, "fraction_prior": fracprior, "excess_ratio": ratio,
            "robustness": robust, "clone_stability": clones, "transient_gate_passed": bool(gate),
            "member_ids_2025": y25["members"]["unique_trajectory_identifier"].astype(str).tolist()}


def main() -> int:
    OUT.mkdir(exist_ok=True); catalog = parse_iau(); cache: dict[tuple[int, int], pd.DataFrame] = {}
    print(f"IAU solutions parsed: {len(catalog)}", flush=True)
    results = []
    for candidate in CANDIDATES:
        print(f"\nEvaluating {candidate['name']}...", flush=True)
        result = evaluate(candidate, catalog, cache); results.append(result)
        print(f"  catalog_veto={result['catalog_veto']['vetoed']} 2025={result['yearly']['2025']['selected']} "
              f"2024={result['yearly']['2024']['selected']} 2023={result['yearly']['2023']['selected']} "
              f"p={result['fisher_p']:.6g} ratio={result['excess_ratio']:.3f} "
              f"robust={result['robustness']['passed']} clones={result['clone_stability'].get('passed')} "
              f"final={result['transient_gate_passed']}", flush=True)
    survivors = [result for result in results if result["transient_gate_passed"]]
    verdict = "TRANSIENT_OUTBURST_CANDIDATE_SURVIVES" if survivors else "NO_TRANSIENT_OUTBURST_CANDIDATE_SURVIVES"
    payload = {"stage": "confirmatory_transient_outburst_gate", "verdict": verdict,
               "candidates_tested": len(results), "survivors": len(survivors),
               "frozen_rules": {"familywise_alpha": 0.01, "bonferroni_alpha": ALPHA,
                                "minimum_excess_ratio": MIN_EXCESS_RATIO,
                                "minimum_2025_members": MIN_2025_MEMBERS,
                                "minimum_nights": MIN_NIGHTS, "minimum_stations": MIN_STATIONS,
                                "catalog_veto": "active IAU solution with D<=0.12, or sky<=7 deg and D<=0.25"},
               "results": results}
    (OUT / "ghoststream_transient_outbursts.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    rows = []
    for result in results:
        rows.append({"name": result["candidate"]["name"], "month": result["candidate"]["month"],
                     "catalog_veto": result["catalog_veto"]["vetoed"],
                     "n2025": result["yearly"]["2025"]["selected"],
                     "n2024": result["yearly"]["2024"]["selected"],
                     "n2023": result["yearly"]["2023"]["selected"],
                     "p": result["fisher_p"], "excess_ratio": result["excess_ratio"],
                     "robust": result["robustness"]["passed"],
                     "clone_fraction": result["clone_stability"].get("pass_fraction"),
                     "survives": result["transient_gate_passed"]})
    pd.DataFrame(rows).to_csv(OUT / "ghoststream_transient_outbursts.csv", index=False)
    lines = ["# GhostStream transient-outburst confirmation", "", f"**Verdict:** `{verdict}`", "",
             f"- Frozen 2025 templates tested: **{len(results)}**", f"- Full-gate survivors: **{len(survivors)}**", "",
             "This gate tests a discovery-year excess rather than annual recurrence. Every candidate must also avoid a conservative IAU catalog veto, remain robust after removing individual nights/stations, and pass 500 uncertainty-clone trials.", ""]
    for result in results:
        c = result["candidate"]; lines += [f"## {c['name']}", "",
            f"- Counts (2025 / 2024 / 2023): **{result['yearly']['2025']['selected']} / {result['yearly']['2024']['selected']} / {result['yearly']['2023']['selected']}**",
            f"- 2025 excess ratio: **{result['excess_ratio']:.3f}**; Fisher p = **{result['fisher_p']:.6g}**",
            f"- Catalog veto: **{result['catalog_veto']['vetoed']}** {result['catalog_veto']['matches'][:2]}",
            f"- Night/station robustness: **{result['robustness']['passed']}**",
            f"- Clone stability: **{result['clone_stability'].get('pass_fraction', 'not run')}**",
            f"- Final transient gate: **{result['transient_gate_passed']}**", ""]
    (OUT / "GHOSTSTREAM_TRANSIENT_OUTBURSTS.md").write_text("\n".join(lines))
    print(f"\nVerdict: {verdict}")
    print(f"Survivors: {len(survivors)}")
    print(f"Report: {OUT / 'GHOSTSTREAM_TRANSIENT_OUTBURSTS.md'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
