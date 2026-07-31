#!/usr/bin/env python3
"""Untouched multi-year confirmation of two IAU working-list showers.

The candidate templates were frozen from 2025 and already checked against 2024.
This script applies those fixed radiant-speed-orbit templates to the previously
untouched 2019-2023 GMN data, using only meteors labeled sporadic by GMN. A
source-preserving null permutes solar longitude while retaining radiant, speed,
and orbit correlations.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader

from run_gate import circ_diff, label
from validate_candidates import ORBIT_COLUMNS, orbit_distance_matrix, orbit_valid

YEARS = tuple(range(2019, 2026))
UNTOUCHED_YEARS = (2019, 2020, 2021, 2022, 2023)
PERMUTATIONS = 199
SEED = 20260731
MIN_COUNT = 8
MAX_P = 0.01
MAX_MEDIAN_D = 0.12
MIN_UNTOUCHED_SIGNIFICANT_YEARS = 3

TEMPLATES = {
    "NMV": {
        "name": "Northern March gamma-Virginids",
        "month": "02",
        "center": [-149.359663, 6.47079, 41.14808, 331.926306],
        "sigma": [1.0510551701999408, 1.2454433040000001, 1.9422356519999994, 1.010924153399962],
        "orbital_medoid": [0.974199, 0.059779, 24.491551, 334.684082, 331.84362],
        "iau_status": "working list",
    },
    "EOC": {
        "name": "eta1-Coronae Australids",
        "month": "06",
        "center": [-153.738435, -21.61014, 42.718025, 77.2298535],
        "sigma": [1.3433616210000276, 1.1352045809999992, 0.9469366200000014, 2.0873821919999846],
        "orbital_medoid": [0.96795, 0.222607, 54.100737, 125.96059, 256.991867],
        "iau_status": "working list",
    },
}

COLUMNS = [
    "unique_trajectory_identifier", "iau_code", "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
    "e", "q_au", "i_deg", "peri_deg", "node_deg",
]


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"Missing GMN columns: {missing}")
    data = frame[COLUMNS].copy()
    data["label"] = data["iau_code"].map(label)
    for column in ["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s", *ORBIT_COLUMNS]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = np.isfinite(data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]).all(axis=1)
    valid &= data["sol_lon_deg"].between(0, 360) & data["lamgeo_deg"].between(0, 360)
    valid &= data["betgeo_deg"].between(-90, 90) & data["vgeo_km_s"].between(5, 75)
    data = data.loc[valid & (data["label"] == "SPORADIC")].reset_index(drop=True)
    return data.loc[orbit_valid(data)].reset_index(drop=True)


def features(data: pd.DataFrame) -> np.ndarray:
    sol = data["sol_lon_deg"].to_numpy(float)
    return np.column_stack([
        circ_diff(data["lamgeo_deg"].to_numpy(float), sol),
        data["betgeo_deg"].to_numpy(float),
        data["vgeo_km_s"].to_numpy(float),
        sol,
    ])


def select(data: pd.DataFrame, template: dict[str, Any], permutation: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    values = features(data)
    center = np.asarray(template["center"], dtype=float)
    sigma = np.maximum(np.asarray(template["sigma"], dtype=float), np.asarray([0.5, 0.5, 0.5, 0.5]))
    if permutation is not None:
        values = values.copy()
        values[:, 3] = values[permutation, 3]
    delta = values - center[None, :]
    delta[:, 0] = circ_diff(values[:, 0], center[0])
    delta[:, 3] = circ_diff(values[:, 3], center[3])
    feature_score = np.sum((delta / sigma[None, :]) ** 2, axis=1)
    orbit = data[ORBIT_COLUMNS].to_numpy(float)
    orbit_d = orbit_distance_matrix(orbit, np.asarray(template["orbital_medoid"], dtype=float)[None, :])[:, 0]
    selected = (feature_score <= 9.0) & (orbit_d <= 0.15)
    return selected, orbit_d


def evaluate_year(data: pd.DataFrame, template: dict[str, Any], rng: np.random.Generator) -> dict[str, Any]:
    chosen, orbit_d = select(data, template)
    observed = int(chosen.sum())
    null_counts: list[int] = []
    for _ in range(PERMUTATIONS):
        permutation = rng.permutation(len(data))
        null_chosen, _ = select(data, template, permutation)
        null_counts.append(int(null_chosen.sum()))
    p = (1 + sum(value >= observed for value in null_counts)) / (PERMUTATIONS + 1)
    selected_d = orbit_d[chosen]
    median_d = float(np.median(selected_d)) if observed else None
    q90_d = float(np.percentile(selected_d, 90)) if observed else None
    passed = observed >= MIN_COUNT and p <= MAX_P and median_d is not None and median_d <= MAX_MEDIAN_D
    selected = data.loc[chosen]
    return {
        "sporadic_valid_orbit_background": int(len(data)),
        "members": observed,
        "permutation_p": float(p),
        "null_q95": float(np.percentile(null_counts, 95)),
        "null_max": int(max(null_counts)),
        "median_d": median_d,
        "q90_d": q90_d,
        "passed": bool(passed),
        "member_ids": list(map(str, selected["unique_trajectory_identifier"].tolist())),
    }


def main() -> int:
    output = Path("ghoststream_multiyear_confirmation")
    output.mkdir(exist_ok=True)
    results: dict[str, Any] = {}
    month_cache: dict[tuple[int, str], pd.DataFrame] = {}

    for code, template in TEMPLATES.items():
        yearly: dict[str, Any] = {}
        print(f"\n{code} {template['name']}:", flush=True)
        for year in YEARS:
            key = (year, template["month"])
            try:
                if key not in month_cache:
                    month = f"{year}-{template['month']}"
                    print(f"Downloading {month}...", flush=True)
                    frame = reader.read_data(dd.get_monthly_file_content_by_date(month), output_camel_case=True).reset_index(drop=False)
                    month_cache[key] = prepare(frame)
                value = evaluate_year(month_cache[key], template, np.random.default_rng(SEED + year * 100 + ord(code[0])))
            except Exception as exc:
                value = {"error": f"{type(exc).__name__}: {exc}", "members": 0, "passed": False}
            yearly[str(year)] = value
            print(f"  {year}: n={value.get('members')} p={value.get('permutation_p')} medianD={value.get('median_d')} pass={value.get('passed')}", flush=True)
        untouched_passes = sum(bool(yearly[str(year)].get("passed")) for year in UNTOUCHED_YEARS)
        total_passes = sum(bool(item.get("passed")) for item in yearly.values())
        total_members = sum(int(item.get("members", 0)) for item in yearly.values())
        passed = untouched_passes >= MIN_UNTOUCHED_SIGNIFICANT_YEARS
        results[code] = {
            "template": template, "yearly": yearly,
            "untouched_significant_years": untouched_passes,
            "total_significant_years": total_passes,
            "total_selected_members": total_members,
            "passed": passed,
            "verdict": "MULTIYEAR_CONFIRMATION_PASS" if passed else "MULTIYEAR_CONFIRMATION_FAIL",
        }

    confirmed = [code for code, item in results.items() if item["passed"]]
    overall = "WORKING_LIST_SHOWERS_INDEPENDENTLY_CONFIRMED_ACROSS_MULTIPLE_YEARS" if confirmed else "NO_WORKING_LIST_SHOWER_PASSES_MULTYEAR_CONFIRMATION"
    summary = {
        "pilot": "GhostStream", "stage": "untouched_multiyear_working_list_confirmation",
        "templates_frozen_from": "2025 blind residual scan and official IAU match",
        "untouched_years": list(UNTOUCHED_YEARS), "all_years": list(YEARS),
        "gm_n_labels_used": "only to retain meteors labeled sporadic; IAU working-list labels were not used as positive labels",
        "frozen_member_rule": {"feature_ellipsoid_radius": 3.0, "orbit_d_max": 0.15},
        "frozen_year_pass_rule": {"minimum_members": MIN_COUNT, "permutation_p_max": MAX_P,
                                  "maximum_median_d": MAX_MEDIAN_D},
        "frozen_candidate_pass_rule": {"minimum_significant_untouched_years": MIN_UNTOUCHED_SIGNIFICANT_YEARS},
        "verdict": overall, "confirmed_codes": confirmed, "results": results,
        "interpretation_limit": "This independently supports the existence and repeatability of IAU working-list showers; it does not by itself establish them officially.",
    }
    metrics = output / "ghoststream_multiyear_confirmation.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rows = []
    for code, item in results.items():
        for year, value in item["yearly"].items():
            rows.append({"code": code, "year": year, "members": value.get("members"),
                         "p": value.get("permutation_p"), "median_d": value.get("median_d"),
                         "q90_d": value.get("q90_d"), "passed": value.get("passed"),
                         "error": value.get("error")})
    pd.DataFrame(rows).to_csv(output / "ghoststream_multiyear_confirmation.csv", index=False)
    lines = ["# GhostStream multi-year confirmation", "", f"**Verdict:** `{overall}`", "",
             f"- Working-list showers passing: **{', '.join(confirmed) if confirmed else 'none'}**", ""]
    for code, item in results.items():
        lines += [f"## {code}: {item['template']['name']}", "",
                  f"- Untouched 2019-2023 significant years: **{item['untouched_significant_years']}/5**",
                  f"- Significant years overall: **{item['total_significant_years']}/7**",
                  f"- Selected members across years: **{item['total_selected_members']}**", ""]
    report = output / "GHOSTSTREAM_MULTIYEAR_CONFIRMATION.md"
    report.write_text("\n".join(lines))
    print(f"\nOverall verdict: {overall}")
    print(f"Confirmed working-list codes: {confirmed}")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    print(f"CSV: {output / 'ghoststream_multiyear_confirmation.csv'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
