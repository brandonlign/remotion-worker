#!/usr/bin/env python3
"""Source-preserving confirmatory audit for the frozen April stream candidate.

This audit addresses the main remaining statistical concern: orbital node is
coupled to encounter date. Therefore neither orbital node nor any orbit element
is used to define the activity enhancement. The candidate is tested as a narrow
radiant-speed/time overdensity inside an expanded antihelion background. Orbit
coherence is tested separately after selection using only radiant, speed, and
time.

The candidate center and widths were frozen by the blind 2026 scan. Untouched
2022 and 2023 data provide the primary confirmation. The pooled untouched-year
activity p-value is Bonferroni corrected for the 12 discovery months searched.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

from validate_april_candidate import (
    CENTER, SIGMA, YEARS, ORBIT_COLUMNS, MAX_YEAR_MEDIAN_D,
    circ_diff, load_year, orbit_summary, valid_orbits,
)

OUT = Path("ghoststream_april_source_null")
SEED = 20260731
UNTOUCHED_YEARS = (2022, 2023)
CONFIRMATION_YEARS = (2022, 2023, 2024, 2025, 2026)
MONTHS_SEARCHED = 12
FAMILYWISE_ALPHA = 0.01
POOLED_ALPHA = FAMILYWISE_ALPHA / MONTHS_SEARCHED
INDIVIDUAL_ALPHA = 0.01
TIME_HALF_WIDTH = float(max(3.0 * SIGMA[3], 1.0))
CORE_RADIUS2 = 9.0
LOCAL_RADIUS2 = 36.0
# Deliberately wider than the old +/-30 degree antihelion veto. Candidate is
# ~30.7 degrees from the nominal antihelion center and therefore lies inside.
ANTIHELION_CENTER = 180.0
ANTIHELION_HALF_WIDTH = 60.0
ANTIHELION_BETA_MAX = 35.0
ANTIHELION_SPEED_MIN = 15.0
ANTIHELION_SPEED_MAX = 50.0
NULL_DRAWS = 9999
MIN_YEAR_CORE = 8
MIN_UNTOUCHED_SIGNIFICANT = 2
MAX_CORE_ORBIT_MEDIAN_D = 0.10
MAX_CORE_ORBIT_Q90_D = 0.20
MAX_ORBIT_NULL_P = 0.001
MIN_ORBIT_POOL_MULTIPLIER = 3
SHIFT_STEP_DEG = 0.25
SHIFT_EXCLUSION_DEG = 2.0 * TIME_HALF_WIDTH
MAX_SHIFT_P = 0.05


def features(data: pd.DataFrame) -> dict[str, np.ndarray]:
    sol = data["sol_lon_deg"].to_numpy(float)
    sunlon = circ_diff(data["lamgeo_deg"].to_numpy(float), sol)
    beta = data["betgeo_deg"].to_numpy(float)
    speed = data["vgeo_km_s"].to_numpy(float)
    score = (
        (circ_diff(sunlon, CENTER[0]) / SIGMA[0]) ** 2
        + ((beta - CENTER[1]) / SIGMA[1]) ** 2
        + ((speed - CENTER[2]) / SIGMA[2]) ** 2
    )
    antihelion = (
        np.abs(circ_diff(sunlon % 360.0, ANTIHELION_CENTER)) <= ANTIHELION_HALF_WIDTH
    ) & (np.abs(beta) <= ANTIHELION_BETA_MAX) & (
        (speed >= ANTIHELION_SPEED_MIN) & (speed <= ANTIHELION_SPEED_MAX)
    )
    temporal = np.abs(circ_diff(sol, CENTER[3])) <= TIME_HALF_WIDTH
    return {
        "sol": sol, "sunlon": sunlon, "beta": beta, "speed": speed,
        "score": score, "antihelion": antihelion, "temporal": temporal,
        "core": score <= CORE_RADIUS2,
        "local": score <= LOCAL_RADIUS2,
    }


def contingency(data: pd.DataFrame, f: dict[str, np.ndarray]) -> dict[str, Any]:
    background = f["antihelion"]
    core = f["core"] & background
    inside = f["temporal"]
    a = int(np.sum(core & inside))
    b = int(np.sum(background & inside & ~core))
    c = int(np.sum(core & ~inside))
    d = int(np.sum(background & ~inside & ~core))
    odds, p = fisher_exact([[a, b], [c, d]], alternative="greater")
    return {
        "table": [[a, b], [c, d]],
        "core_inside": a,
        "background_other_inside": b,
        "core_outside": c,
        "background_other_outside": d,
        "odds_ratio": float(odds),
        "p": float(p),
        "core_fraction_inside": float(a / (a + b)) if a + b else 0.0,
        "core_fraction_outside": float(c / (c + d)) if c + d else 0.0,
    }


def shifted_window_test(data: pd.DataFrame, f: dict[str, np.ndarray]) -> dict[str, Any]:
    sol = f["sol"]
    background = f["antihelion"]
    core = f["core"] & background
    observed_inside = np.abs(circ_diff(sol, CENTER[3])) <= TIME_HALF_WIDTH
    observed_den = int(np.sum(background & observed_inside))
    observed_num = int(np.sum(core & observed_inside))
    observed_ratio = observed_num / observed_den if observed_den else 0.0
    lo = float(np.nanpercentile(sol, 1.0)) + TIME_HALF_WIDTH
    hi = float(np.nanpercentile(sol, 99.0)) - TIME_HALF_WIDTH
    centers = np.arange(lo, hi + 1e-9, SHIFT_STEP_DEG)
    controls = []
    for center in centers:
        if abs(float(circ_diff(center, CENTER[3]))) <= SHIFT_EXCLUSION_DEG:
            continue
        mask = np.abs(circ_diff(sol, center)) <= TIME_HALF_WIDTH
        den = int(np.sum(background & mask))
        if den < 10:
            continue
        num = int(np.sum(core & mask))
        controls.append({"center": float(center), "core": num, "background": den,
                         "ratio": float(num / den)})
    p = ((1 + sum(item["ratio"] >= observed_ratio for item in controls)) /
         (1 + len(controls))) if controls else 1.0
    return {
        "observed_core": observed_num,
        "observed_background": observed_den,
        "observed_ratio": float(observed_ratio),
        "control_windows": int(len(controls)),
        "empirical_p": float(p),
        "control_ratio_q95": float(np.percentile([item["ratio"] for item in controls], 95)) if controls else None,
        "control_ratio_max": float(max(item["ratio"] for item in controls)) if controls else None,
        "top_controls": sorted(controls, key=lambda item: item["ratio"], reverse=True)[:20],
    }


def core_orbit_test(data: pd.DataFrame, f: dict[str, np.ndarray], year: int) -> dict[str, Any]:
    # Orbit is not used in this selection.
    selected = f["core"] & f["temporal"] & f["antihelion"] & valid_orbits(data)
    core_orbits = data.loc[selected, ORBIT_COLUMNS].to_numpy(float)
    if len(core_orbits) < MIN_YEAR_CORE:
        return {"members": int(len(core_orbits)), "passed": False, "reason": "too_few_core_orbits"}
    observed = orbit_summary(core_orbits)

    # Primary null: same date and expanded antihelion source, but outside the
    # fine core. This preserves network exposure, source activity, and date.
    pool_mask = f["temporal"] & f["antihelion"] & ~f["core"] & valid_orbits(data)
    pool = data.loc[pool_mask, ORBIT_COLUMNS].to_numpy(float)
    pool_kind = "same_time_expanded_antihelion_outside_core"
    # If a sparse early year lacks enough events, use the larger nearby radiant
    # shell across the same month. This fallback is reported, never hidden.
    if len(pool) < len(core_orbits) * MIN_ORBIT_POOL_MULTIPLIER:
        pool_mask = f["local"] & ~f["core"] & f["antihelion"] & valid_orbits(data)
        pool = data.loc[pool_mask, ORBIT_COLUMNS].to_numpy(float)
        pool_kind = "monthwide_local_radiant_shell"
    if len(pool) < len(core_orbits) * MIN_ORBIT_POOL_MULTIPLIER:
        return {
            "members": int(len(core_orbits)), "pool": int(len(pool)),
            "observed": observed, "passed": False, "reason": "insufficient_local_null_pool",
            "pool_kind": pool_kind,
        }
    rng = np.random.default_rng(SEED + year * 100)
    null = []
    for _ in range(NULL_DRAWS):
        sample = pool[rng.choice(len(pool), size=len(core_orbits), replace=False)]
        null.append(float(orbit_summary(sample)["median_d"]))
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (NULL_DRAWS + 1)
    passed = (
        observed["median_d"] <= MAX_CORE_ORBIT_MEDIAN_D
        and observed["q90_d"] <= MAX_CORE_ORBIT_Q90_D
        and p <= MAX_ORBIT_NULL_P
    )
    return {
        "members": int(len(core_orbits)), "pool": int(len(pool)),
        "pool_kind": pool_kind,
        "observed": observed,
        "null_p": float(p),
        "null_q01": float(np.percentile(null, 1)),
        "null_q05": float(np.percentile(null, 5)),
        "passed": bool(passed),
    }


def pooled_contingency(year_results: dict[str, Any], years: tuple[int, ...]) -> dict[str, Any]:
    tables = [np.asarray(year_results[str(year)]["activity"]["table"], dtype=int) for year in years]
    table = np.sum(tables, axis=0)
    odds, p = fisher_exact(table.tolist(), alternative="greater")
    return {
        "years": list(years), "table": table.tolist(),
        "odds_ratio": float(odds), "p": float(p),
        "bonferroni_alpha": float(POOLED_ALPHA),
        "passed": bool(p <= POOLED_ALPHA),
    }


def pooled_orbit_test(frames: dict[int, pd.DataFrame], years: tuple[int, ...]) -> dict[str, Any]:
    selected_orbits = []
    null_pool = []
    for year in years:
        data = frames[year]
        f = features(data)
        selected = f["core"] & f["temporal"] & f["antihelion"] & valid_orbits(data)
        selected_orbits.append(data.loc[selected, ORBIT_COLUMNS].to_numpy(float))
        pool = f["temporal"] & f["antihelion"] & ~f["core"] & valid_orbits(data)
        null_pool.append(data.loc[pool, ORBIT_COLUMNS].to_numpy(float))
    core = np.vstack(selected_orbits)
    pool = np.vstack(null_pool)
    observed = orbit_summary(core)
    if len(pool) < len(core) * MIN_ORBIT_POOL_MULTIPLIER:
        return {"members": int(len(core)), "pool": int(len(pool)), "observed": observed,
                "passed": False, "reason": "insufficient_pooled_null_pool"}
    rng = np.random.default_rng(SEED + 4242)
    null = []
    for _ in range(NULL_DRAWS):
        sample = pool[rng.choice(len(pool), size=len(core), replace=False)]
        null.append(float(orbit_summary(sample)["median_d"]))
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (NULL_DRAWS + 1)
    return {
        "years": list(years), "members": int(len(core)), "pool": int(len(pool)),
        "observed": observed, "null_p": float(p),
        "null_q01": float(np.percentile(null, 1)),
        "passed": bool(
            observed["median_d"] <= MAX_CORE_ORBIT_MEDIAN_D
            and observed["q90_d"] <= MAX_CORE_ORBIT_Q90_D
            and p <= MAX_ORBIT_NULL_P
        ),
    }


def pooled_shift_test(frames: dict[int, pd.DataFrame], years: tuple[int, ...]) -> dict[str, Any]:
    prepared = []
    for year in years:
        data = frames[year]
        f = features(data)
        prepared.append((data, f))
    observed_num = sum(int(np.sum(f["core"] & f["antihelion"] & f["temporal"])) for _, f in prepared)
    observed_den = sum(int(np.sum(f["antihelion"] & f["temporal"])) for _, f in prepared)
    observed_ratio = observed_num / observed_den if observed_den else 0.0
    # Use centers valid in every selected year.
    lower = max(float(np.nanpercentile(f["sol"], 1)) + TIME_HALF_WIDTH for _, f in prepared)
    upper = min(float(np.nanpercentile(f["sol"], 99)) - TIME_HALF_WIDTH for _, f in prepared)
    controls = []
    for center in np.arange(lower, upper + 1e-9, SHIFT_STEP_DEG):
        if abs(float(circ_diff(center, CENTER[3]))) <= SHIFT_EXCLUSION_DEG:
            continue
        num = den = 0
        for _, f in prepared:
            mask = np.abs(circ_diff(f["sol"], center)) <= TIME_HALF_WIDTH
            num += int(np.sum(f["core"] & f["antihelion"] & mask))
            den += int(np.sum(f["antihelion"] & mask))
        if den < 20:
            continue
        controls.append({"center": float(center), "core": num, "background": den,
                         "ratio": float(num / den)})
    p = ((1 + sum(item["ratio"] >= observed_ratio for item in controls)) /
         (1 + len(controls))) if controls else 1.0
    return {
        "years": list(years), "observed_core": observed_num,
        "observed_background": observed_den, "observed_ratio": float(observed_ratio),
        "control_windows": int(len(controls)), "empirical_p": float(p),
        "passed": bool(p <= MAX_SHIFT_P),
        "control_ratio_q95": float(np.percentile([item["ratio"] for item in controls], 95)) if controls else None,
        "top_controls": sorted(controls, key=lambda item: item["ratio"], reverse=True)[:20],
    }


def jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def main() -> int:
    OUT.mkdir(exist_ok=True)
    frames: dict[int, pd.DataFrame] = {}
    results: dict[str, Any] = {}
    for year in YEARS:
        data, audit = load_year(year)
        frames[year] = data
        f = features(data)
        activity = contingency(data, f)
        shift = shifted_window_test(data, f)
        orbit = core_orbit_test(data, f, year)
        individually_confirmed = bool(
            year in CONFIRMATION_YEARS
            and activity["core_inside"] >= MIN_YEAR_CORE
            and activity["p"] <= INDIVIDUAL_ALPHA
            and orbit.get("passed", False)
        )
        results[str(year)] = {
            "deduplication": audit,
            "quality_sporadics": int(len(data)),
            "expanded_antihelion_events": int(np.sum(f["antihelion"])),
            "core_events_monthwide": int(np.sum(f["core"] & f["antihelion"])),
            "activity": activity,
            "shifted_windows": shift,
            "orbit_without_orbit_selection": orbit,
            "individually_confirmed": individually_confirmed,
        }
        print(
            f"{year}: core/time={activity['core_inside']} antihelion/time={sum(activity['table'][0])} "
            f"activity_p={activity['p']:.4g} shift_p={shift['empirical_p']:.4g} "
            f"orbit_n={orbit.get('members')} orbit_p={orbit.get('null_p')} "
            f"confirmed={individually_confirmed}", flush=True
        )

    untouched_activity = pooled_contingency(results, UNTOUCHED_YEARS)
    untouched_orbit = pooled_orbit_test(frames, UNTOUCHED_YEARS)
    untouched_shift = pooled_shift_test(frames, UNTOUCHED_YEARS)
    recent_activity = pooled_contingency(results, CONFIRMATION_YEARS)
    recent_orbit = pooled_orbit_test(frames, CONFIRMATION_YEARS)
    untouched_confirmed_years = [
        year for year in UNTOUCHED_YEARS if results[str(year)]["individually_confirmed"]
    ]
    passed = bool(
        len(untouched_confirmed_years) >= MIN_UNTOUCHED_SIGNIFICANT
        and untouched_activity["passed"]
        and untouched_orbit["passed"]
        and untouched_shift["passed"]
        and recent_activity["passed"]
        and recent_orbit["passed"]
    )
    verdict = (
        "APRIL_STREAM_SURVIVES_SOURCE_PRESERVING_NULL"
        if passed else "APRIL_STREAM_FAILS_SOURCE_PRESERVING_NULL"
    )
    payload = {
        "stage": "source_preserving_antihelion_and_node_independent_audit",
        "verdict": verdict,
        "passed": passed,
        "frozen_rules": {
            "candidate_center": CENTER, "candidate_sigma": SIGMA,
            "core_radius_squared": CORE_RADIUS2,
            "time_half_width_deg": TIME_HALF_WIDTH,
            "expanded_antihelion": {
                "sun_centered_longitude_center_deg": ANTIHELION_CENTER,
                "half_width_deg": ANTIHELION_HALF_WIDTH,
                "absolute_beta_max_deg": ANTIHELION_BETA_MAX,
                "speed_range_km_s": [ANTIHELION_SPEED_MIN, ANTIHELION_SPEED_MAX],
            },
            "activity_test_uses_orbit": False,
            "orbit_test_selection_uses_orbit": False,
            "months_searched": MONTHS_SEARCHED,
            "pooled_bonferroni_alpha": POOLED_ALPHA,
            "individual_year_alpha": INDIVIDUAL_ALPHA,
            "orbit_null_alpha": MAX_ORBIT_NULL_P,
        },
        "yearly": results,
        "untouched_years": {
            "years": list(UNTOUCHED_YEARS),
            "individually_confirmed": untouched_confirmed_years,
            "activity": untouched_activity,
            "shifted_windows": untouched_shift,
            "orbit": untouched_orbit,
        },
        "confirmation_years": {
            "years": list(CONFIRMATION_YEARS),
            "activity": recent_activity,
            "orbit": recent_orbit,
        },
        "gate_components": {
            "two_untouched_years_individually_confirmed": len(untouched_confirmed_years) >= 2,
            "untouched_activity_familywise_pass": untouched_activity["passed"],
            "untouched_orbit_null_pass": untouched_orbit["passed"],
            "untouched_shifted_window_pass": untouched_shift["passed"],
            "all_confirmation_year_activity_pass": recent_activity["passed"],
            "all_confirmation_year_orbit_pass": recent_orbit["passed"],
        },
    }
    (OUT / "april_source_preserving_null.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )
    lines = [
        "# April stream source-preserving null audit", "",
        f"**Verdict:** `{verdict}`", "",
        "The activity test uses only Sun-centered radiant, ecliptic latitude, geocentric speed, and solar longitude. No orbit element or node is used to select the activity enhancement. Orbit coherence is tested separately afterward.", "",
        f"- Untouched years individually confirmed: **{untouched_confirmed_years}**",
        f"- Pooled untouched activity p: **{untouched_activity['p']:.6g}** (12-month threshold {POOLED_ALPHA:.6g})",
        f"- Pooled untouched shifted-window p: **{untouched_shift['empirical_p']:.6g}**",
        f"- Pooled untouched orbit-null p: **{untouched_orbit.get('null_p')}**",
        f"- Expanded antihelion longitude range: **{ANTIHELION_CENTER-ANTIHELION_HALF_WIDTH:.0f}° to {ANTIHELION_CENTER+ANTIHELION_HALF_WIDTH:.0f}°**", "",
        "| Year | Core in window | Antihelion in window | Activity p | Shift p | Core orbit n | Orbit p | Confirmed |",
        "|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for year in YEARS:
        item = results[str(year)]
        activity = item["activity"]; orbit = item["orbit_without_orbit_selection"]
        lines.append(
            f"| {year} | {activity['core_inside']} | {sum(activity['table'][0])} | {activity['p']:.4g} | "
            f"{item['shifted_windows']['empirical_p']:.4g} | {orbit.get('members')} | "
            f"{orbit.get('null_p', '—')} | {item['individually_confirmed']} |"
        )
    lines += ["", "A passing result removes the orbital-node circularity and broad antihelion-boundary objection. It still requires external network/catalog and literature validation before a discovery claim.", ""]
    (OUT / "APRIL_SOURCE_PRESERVING_NULL.md").write_text("\n".join(lines))
    print(f"\nVerdict: {verdict}")
    print(f"Untouched confirmed years: {untouched_confirmed_years}")
    print(f"Untouched pooled activity p: {untouched_activity['p']}")
    print(f"Untouched pooled shift p: {untouched_shift['empirical_p']}")
    print(f"Untouched pooled orbit p: {untouched_orbit.get('null_p')}")
    print(f"Report: {OUT / 'APRIL_SOURCE_PRESERVING_NULL.md'}")
    return 0


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=FutureWarning)
    raise SystemExit(main())
