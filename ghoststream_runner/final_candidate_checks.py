#!/usr/bin/env python3
"""Official IAU catalog matching and uncertainty-clone stability for survivors."""
from __future__ import annotations

import csv
import io
import json
import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import requests
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader

from validate_candidates import (
    ORBIT_COLUMNS, TARGETS, orbit_distance_matrix, dispersion, orbit_valid,
    prepare, reconstruct_cluster,
)

IAU_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamfulldata2026.txt"
CLONE_ITERATIONS = 500
CLONE_PASS_FRACTION = 0.80
MAX_CLONE_MEDIAN_D = 0.10
MAX_CLONE_Q90_D = 0.20
IAU_MAX_SOLAR_DELTA = 7.0
IAU_MAX_RADIANT_SCALED = 2.5
IAU_MAX_ORBIT_D = 0.15
SIGMA_CAPS = np.asarray([0.10, 0.10, 10.0, 20.0, 5.0])
SURVIVORS = {
    "GS-2025-02-A": {
        "target_index": 1,
        "solar_longitude_deg": 331.926306,
        "sun_centered_longitude_deg": -149.359663,
        "ecliptic_latitude_deg": 6.47079,
        "vgeo_km_s": 41.14808,
        "replication_2024_members": 25,
        "replication_2024_p": 0.005,
    },
    "GS-2025-06-C": {
        "target_index": 3,
        "solar_longitude_deg": 77.2298535,
        "sun_centered_longitude_deg": -153.738435,
        "ecliptic_latitude_deg": -21.61014,
        "vgeo_km_s": 42.718025,
        "replication_2024_members": 23,
        "replication_2024_p": 0.005,
    },
}


def number(value: str) -> float | None:
    text = value.strip().replace("[", "").replace("]", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_iau(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith('"'):
            continue
        parsed = next(csv.reader(io.StringIO(line), delimiter="|", quotechar='"', skipinitialspace=True))
        values = [item.strip().strip('"').strip() for item in parsed]
        if len(values) < 29:
            continue
        record = {
            "lp": values[0], "iau_no": values[1], "solution": values[2],
            "code": values[3], "status": int(number(values[4]) or 0),
            "name": values[6], "activity": values[7],
            "solar_begin": number(values[8]), "solar_end": number(values[9]),
            "solar_longitude": number(values[10]), "vgeo": number(values[15]),
            "sun_centered_longitude": number(values[17]), "ecliptic_latitude": number(values[18]),
            "a": number(values[22]), "q": number(values[23]), "e": number(values[24]),
            "peri": number(values[25]), "node": number(values[26]), "inclination": number(values[27]),
            "members": number(values[28]),
            "origin": values[31] if len(values) > 31 else "",
            "remarks": values[32] if len(values) > 32 else "",
        }
        rows.append(record)
    if len(rows) < 100:
        raise RuntimeError(f"IAU parser returned only {len(rows)} records")
    return rows


def circular_delta(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def iau_matches(candidate: dict[str, Any], orbital_medoid: np.ndarray,
                catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for shower in catalog:
        needed = [shower["solar_longitude"], shower["vgeo"], shower["sun_centered_longitude"],
                  shower["ecliptic_latitude"], shower["q"], shower["e"], shower["peri"],
                  shower["node"], shower["inclination"]]
        if any(value is None for value in needed):
            continue
        solar_delta = circular_delta(candidate["solar_longitude_deg"], float(shower["solar_longitude"]))
        radiant_scaled = math.sqrt(
            (circular_delta(candidate["sun_centered_longitude_deg"], float(shower["sun_centered_longitude"])) / 4.0) ** 2
            + ((candidate["ecliptic_latitude_deg"] - float(shower["ecliptic_latitude"])) / 4.0) ** 2
            + ((candidate["vgeo_km_s"] - float(shower["vgeo"])) / 3.0) ** 2
        )
        orbit = np.asarray([[float(shower["e"]), float(shower["q"]), float(shower["inclination"]),
                             float(shower["peri"]), float(shower["node"])]])
        orbit_d = float(orbit_distance_matrix(orbital_medoid[None, :], orbit)[0, 0])
        match = solar_delta <= IAU_MAX_SOLAR_DELTA and radiant_scaled <= IAU_MAX_RADIANT_SCALED and orbit_d <= IAU_MAX_ORBIT_D
        score = solar_delta / IAU_MAX_SOLAR_DELTA + radiant_scaled / IAU_MAX_RADIANT_SCALED + orbit_d / IAU_MAX_ORBIT_D
        output.append({**shower, "solar_delta": solar_delta, "radiant_scaled": radiant_scaled,
                       "orbit_d": orbit_d, "match": match, "combined_score": score})
    return sorted(output, key=lambda item: item["combined_score"])


def clone_stability(members, rng: np.random.Generator) -> dict[str, Any]:
    base = members[ORBIT_COLUMNS].to_numpy(float)
    sigma = np.column_stack([
        members["sigma_9"].to_numpy(float), members["sigma_15"].to_numpy(float),
        members["sigma_10"].to_numpy(float), members["sigma_11"].to_numpy(float),
        members["sigma_12"].to_numpy(float),
    ])
    med = np.nanmedian(sigma, axis=0)
    for column in range(sigma.shape[1]):
        invalid = ~np.isfinite(sigma[:, column]) | (sigma[:, column] < 0)
        sigma[invalid, column] = med[column] if np.isfinite(med[column]) else 0.0
    sigma = np.minimum(sigma, SIGMA_CAPS[None, :])
    medians: list[float] = []
    q90s: list[float] = []
    passed = 0
    for _ in range(CLONE_ITERATIONS):
        cloned = base + rng.normal(0.0, sigma)
        cloned[:, 0] = np.clip(cloned[:, 0], 0.0, 1.49)
        cloned[:, 1] = np.clip(cloned[:, 1], 0.001, 1.999)
        cloned[:, 2] = np.clip(cloned[:, 2], 0.0, 180.0)
        cloned[:, 3] %= 360.0
        cloned[:, 4] %= 360.0
        metrics = dispersion(cloned)
        median_d, q90_d = float(metrics["median_d"]), float(metrics["q90_d"])
        medians.append(median_d)
        q90s.append(q90_d)
        passed += int(median_d <= MAX_CLONE_MEDIAN_D and q90_d <= MAX_CLONE_Q90_D)
    fraction = passed / CLONE_ITERATIONS
    return {
        "iterations": CLONE_ITERATIONS, "pass_fraction": fraction,
        "passed": fraction >= CLONE_PASS_FRACTION,
        "median_d_median": float(np.median(medians)), "median_d_q95": float(np.percentile(medians, 95)),
        "q90_d_median": float(np.median(q90s)), "q90_d_q95": float(np.percentile(q90s, 95)),
        "sigma_caps": SIGMA_CAPS.tolist(),
    }


def main() -> int:
    output = Path("ghoststream_final_checks")
    output.mkdir(exist_ok=True)
    response = requests.get(IAU_URL, timeout=60)
    response.raise_for_status()
    catalog = parse_iau(response.text)
    print(f"Official IAU solutions parsed: {len(catalog)}", flush=True)

    cache: dict[str, Any] = {}
    results = []
    for name, info in SURVIVORS.items():
        target = TARGETS[info["target_index"]]
        month = target["month"]
        if month not in cache:
            print(f"Downloading 2025-{month} for {name}...", flush=True)
            frame = reader.read_data(dd.get_monthly_file_content_by_date(f"2025-{month}"), output_camel_case=True).reset_index(drop=False)
            cache[month] = prepare(frame, 2025, target["month_index"])
        members, _, reconstruction = reconstruct_cluster(cache[month], target)
        good = members.loc[orbit_valid(members)].reset_index(drop=True)
        baseline = dispersion(good[ORBIT_COLUMNS].to_numpy(float))
        orbital_medoid = np.asarray(baseline.pop("medoid"), dtype=float)
        baseline.pop("distances", None)
        matches = iau_matches(info, orbital_medoid, catalog)
        close = [item for item in matches if item["match"]]
        official_established = [item for item in close if item["status"] >= 1]
        official_working = [item for item in close if item["status"] == 0]
        official_removed = [item for item in close if item["status"] < 0]
        clones = clone_stability(good, np.random.default_rng(SEED + target["cluster"] + 90000))
        if official_established:
            verdict = "MATCHES_ESTABLISHED_IAU_SHOWER"
        elif official_working:
            verdict = "MATCHES_IAU_WORKING_LIST_SHOWER"
        elif official_removed:
            verdict = "MATCHES_REMOVED_OR_UNRELIABLE_IAU_SHOWER"
        elif not clones["passed"]:
            verdict = "FAILS_UNCERTAINTY_CLONE_STABILITY"
        else:
            verdict = "SURVIVES_IAU_AND_UNCERTAINTY_CHECKS__DISCOVERY_CANDIDATE"
        result = {
            "name": name, "verdict": verdict, "member_count": int(len(good)),
            "reconstruction": reconstruction, "radiant": info,
            "orbital_medoid": orbital_medoid.tolist(), "baseline_orbit_dispersion": baseline,
            "uncertainty_clones": clones,
            "official_close_matches": close[:30], "nearest_official_top10": matches[:10],
            "established_match_count": len(official_established),
            "working_match_count": len(official_working), "removed_match_count": len(official_removed),
        }
        results.append(result)
        nearest = matches[0] if matches else None
        print(
            f"{name}: {verdict} | clones={clones['pass_fraction']:.3f} | "
            f"closeIAU={len(close)} | nearest={None if nearest is None else (nearest['code'], nearest['name'], nearest['status'], nearest['solar_delta'], nearest['radiant_scaled'], nearest['orbit_d'])}",
            flush=True,
        )

    survivors = [item for item in results if item["verdict"] == "SURVIVES_IAU_AND_UNCERTAINTY_CHECKS__DISCOVERY_CANDIDATE"]
    if survivors:
        overall = "GHOSTSTREAM_DISCOVERY_CANDIDATES_SURVIVE_FULL_PILOT"
    else:
        overall = "NO_NOVEL_CANDIDATE_SURVIVES_OFFICIAL_CATALOG_AND_UNCERTAINTY_CHECKS"
    summary = {
        "pilot": "GhostStream", "stage": "official_IAU_and_uncertainty_clone_checks",
        "iau_catalog_url": IAU_URL, "iau_solutions_parsed": len(catalog),
        "catalog_downloaded_during_run": True,
        "frozen_iau_match_rule": {"solar_delta_max_deg": IAU_MAX_SOLAR_DELTA,
                                  "radiant_scaled_max": IAU_MAX_RADIANT_SCALED,
                                  "orbit_d_max": IAU_MAX_ORBIT_D},
        "frozen_clone_rule": {"iterations": CLONE_ITERATIONS, "minimum_pass_fraction": CLONE_PASS_FRACTION,
                              "maximum_median_d": MAX_CLONE_MEDIAN_D, "maximum_q90_d": MAX_CLONE_Q90_D},
        "verdict": overall, "discovery_candidate_count": len(survivors), "results": results,
        "interpretation_limit": "A survivor is a discovery candidate, not an accepted new meteor shower. Full IAU submission requires more years, clone-level membership, literature review, and independent expert review.",
    }
    metrics = output / "ghoststream_final_checks.json"
    metrics.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rows = []
    for item in results:
        nearest = item["nearest_official_top10"][0] if item["nearest_official_top10"] else {}
        rows.append({
            "name": item["name"], "verdict": item["verdict"], "members": item["member_count"],
            "clone_pass_fraction": item["uncertainty_clones"]["pass_fraction"],
            "close_iau_matches": len(item["official_close_matches"]),
            "nearest_iau_code": nearest.get("code"), "nearest_iau_name": nearest.get("name"),
            "nearest_iau_status": nearest.get("status"), "nearest_solar_delta": nearest.get("solar_delta"),
            "nearest_radiant_scaled": nearest.get("radiant_scaled"), "nearest_orbit_d": nearest.get("orbit_d"),
        })
    import pandas as pd
    pd.DataFrame(rows).to_csv(output / "ghoststream_final_checks.csv", index=False)
    lines = ["# GhostStream final pilot checks", "", f"**Verdict:** `{overall}`", "",
             f"- Official IAU solutions checked: **{len(catalog)}**",
             f"- Discovery candidates surviving: **{len(survivors)}**", "", "## Results", ""]
    for item in results:
        nearest = item["nearest_official_top10"][0] if item["nearest_official_top10"] else {}
        lines.append(
            f"- **{item['name']}:** `{item['verdict']}`; clone stability={item['uncertainty_clones']['pass_fraction']:.1%}; "
            f"nearest IAU={nearest.get('code')} {nearest.get('name')} (status={nearest.get('status')}, "
            f"solar Δ={nearest.get('solar_delta')}, radiant distance={nearest.get('radiant_scaled')}, orbit D={nearest.get('orbit_d')})."
        )
    lines += ["", "Any survivor remains a discovery candidate rather than an accepted shower.", ""]
    report = output / "GHOSTSTREAM_FINAL_CHECKS.md"
    report.write_text("\n".join(lines))
    print(f"\nOverall verdict: {overall}")
    print(f"Discovery candidates surviving: {len(survivors)}")
    print(f"Report: {report}")
    print(f"Metrics: {metrics}")
    print(f"CSV: {output / 'ghoststream_final_checks.csv'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
