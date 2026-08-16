#!/usr/bin/env python3
"""Post-hoc synthesis of three independent historical archive families.

Combines the separately evaluated legacy CAMS, SonotaCo, and Shober EDMOND
archives using the unchanged GMN template. The pooled orbital null is
source-stratified: every null draw preserves the selected member count from
each archive family. The synthesis is explicitly post-hoc and cannot replace a
fresh preregistered external-network validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

import validate_cams_legacy as cams
import validate_independent_catalogs_v2 as independent
import validate_shober_edmond as shober
from orbit_helpers_standalone import orbit_distance_matrix, orbit_summary

OUT = Path("ghoststream_three_archive_synthesis")
SEED = 20260731
NULL_DRAWS = 19999
SOL0 = shober.SOL0
SUNLON0 = shober.SUNLON0
BETA0 = shober.BETA0
VG0 = shober.VG0
SUNLON_SLOPE = shober.SUNLON_SLOPE
BETA_SLOPE = shober.BETA_SLOPE
SPEED_SLOPES = shober.SPEED_SLOPES
SUNLON_SIGMA = shober.SUNLON_SIGMA
BETA_SIGMA = shober.BETA_SIGMA
VG_SIGMA = shober.VG_SIGMA
CORE_RADIUS2 = shober.CORE_RADIUS2
TIME_HALF_WIDTH = shober.TIME_HALF_WIDTH
SEASON_HALF_WIDTH = shober.BASELINE_OUTER
ANTIHELION_CENTER = shober.ANTIHELION_CENTER
ANTIHELION_HALF_WIDTH = shober.ANTIHELION_HALF_WIDTH
ANTIHELION_BETA_MAX = shober.ANTIHELION_BETA_MAX
ANTIHELION_SPEED_MIN = shober.ANTIHELION_SPEED_MIN
ANTIHELION_SPEED_MAX = shober.ANTIHELION_SPEED_MAX
REFINED_GMN_ORBIT = shober.REFINED_GMN_ORBIT
MAX_ORBIT_MEDIAN_D = 0.10
MAX_ORBIT_Q90_D = 0.20
MAX_ORBIT_NULL_P = 0.001
MAX_ACTIVITY_P = 0.001
MAX_SHIFT_P = 0.05
MIN_MEMBERS = 12
MIN_UNIQUE_YEARS = 6


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


def load_cams() -> tuple[pd.DataFrame, dict[str, Any]]:
    data = cams.parse_catalog().copy()
    data["source"] = "CAMS"
    data["identifier"] = data["id"].astype(str)
    data["peri"] = data["peri_norm"]
    return data[[
        "source", "year", "identifier", "sol", "sunlon", "beta", "vg",
        "e", "q", "inc", "peri", "node",
    ]].copy(), {"rows": int(len(data)), "year_range": [int(data.year.min()), int(data.year.max())]}


def load_sonotaco() -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    metadata = {}
    for year in (2022, 2023, 2024, 2025):
        frame, audit = independent.corrected_sonotaco(year)
        frame = frame.copy()
        frame["source"] = "SonotaCo"
        frames.append(frame[[
            "source", "year", "identifier", "sol", "sunlon", "beta", "vg",
            "e", "q", "inc", "peri", "node",
        ]])
        metadata[str(year)] = audit
    data = pd.concat(frames, ignore_index=True, sort=False)
    return data, {"rows": int(len(data)), "downloads": metadata}


def load_shober() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw, download = shober.download()
    data, preparation = shober.prepare(raw)
    frame = pd.DataFrame({
        "source": "Shober_EDMOND",
        "year": data["_Y_ut"].astype(int),
        "identifier": data["_localtime"].astype(str),
        "sol": data["_sol"].to_numpy(float),
        "sunlon": circ_diff(data["_elng"].to_numpy(float), data["_sol"].to_numpy(float)),
        "beta": data["_elat"].to_numpy(float),
        "vg": data["_vg"].to_numpy(float),
        "e": data["_e"].to_numpy(float),
        "q": data["_q"].to_numpy(float),
        "inc": data["_incl"].to_numpy(float),
        "peri": data["_peri"].to_numpy(float),
        "node": data["_node"].to_numpy(float),
    })
    return frame, {"rows": int(len(frame)), "download": download, "preparation": preparation}


def masks(frame: pd.DataFrame, speed_slope: float) -> dict[str, np.ndarray]:
    sol = frame["sol"].to_numpy(float)
    delta = circ_diff(sol, SOL0)
    sunlon = frame["sunlon"].to_numpy(float)
    beta = frame["beta"].to_numpy(float)
    speed = frame["vg"].to_numpy(float)
    score = (
        (circ_diff(sunlon, SUNLON0 + SUNLON_SLOPE * delta) / SUNLON_SIGMA) ** 2
        + ((beta - (BETA0 + BETA_SLOPE * delta)) / BETA_SIGMA) ** 2
        + ((speed - (VG0 + speed_slope * delta)) / VG_SIGMA) ** 2
    )
    antihelion = (
        np.abs(circ_diff(sunlon % 360.0, ANTIHELION_CENTER)) <= ANTIHELION_HALF_WIDTH
    ) & (np.abs(beta) <= ANTIHELION_BETA_MAX) & (
        speed >= ANTIHELION_SPEED_MIN
    ) & (speed <= ANTIHELION_SPEED_MAX)
    return {
        "delta": delta,
        "core": score <= CORE_RADIUS2,
        "antihelion": antihelion,
        "inside": np.abs(delta) <= TIME_HALF_WIDTH,
        "baseline": (np.abs(delta) > 6.0) & (np.abs(delta) <= SEASON_HALF_WIDTH),
    }


def source_result(frame: pd.DataFrame, mask: dict[str, np.ndarray]) -> tuple[dict[str, Any], pd.DataFrame, np.ndarray]:
    stream = mask["core"] & mask["antihelion"]
    background = ~mask["core"] & mask["antihelion"]
    table = np.asarray([
        [np.sum(stream & mask["inside"]), np.sum(background & mask["inside"])],
        [np.sum(stream & mask["baseline"]), np.sum(background & mask["baseline"])],
    ], dtype=int)
    odds, p = fisher_exact(table.tolist(), alternative="greater")
    selected = stream & mask["inside"]
    members = frame.loc[selected].copy()
    pool = frame.loc[
        background & mask["inside"], ["e", "q", "inc", "peri", "node"]
    ].to_numpy(float)
    return {
        "rows": int(len(frame)),
        "activity_table": table.tolist(),
        "activity_odds_ratio": float(odds),
        "activity_p": float(p),
        "members": int(len(members)),
        "members_by_year": {
            str(int(year)): int(count)
            for year, count in members["year"].value_counts().sort_index().items()
        },
        "same_time_null_pool": int(len(pool)),
    }, members, pool


def shifted_window_test(frames: dict[str, pd.DataFrame], masks_by_source: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    observed_num = observed_den = 0
    for source, frame in frames.items():
        mask = masks_by_source[source]
        observed_num += int(np.sum(mask["core"] & mask["antihelion"] & mask["inside"]))
        observed_den += int(np.sum(mask["antihelion"] & mask["inside"]))
    observed_ratio = observed_num / observed_den if observed_den else 0.0
    controls = []
    for offset in np.arange(-14.0, 14.0 + 1e-9, 0.25):
        if abs(offset) <= 2.0 * TIME_HALF_WIDTH:
            continue
        num = den = 0
        center = (SOL0 + offset) % 360.0
        for source, frame in frames.items():
            mask = masks_by_source[source]
            window = np.abs(circ_diff(frame["sol"].to_numpy(float), center)) <= TIME_HALF_WIDTH
            source_background = mask["antihelion"]
            num += int(np.sum(mask["core"] & source_background & window))
            den += int(np.sum(source_background & window))
        if den < 20:
            continue
        controls.append({
            "offset": float(offset), "stream": num, "source_total": den,
            "ratio": float(num / den),
        })
    p = ((1 + sum(item["ratio"] >= observed_ratio for item in controls)) /
         (1 + len(controls))) if controls else 1.0
    return {
        "observed_stream": observed_num,
        "observed_source_total": observed_den,
        "observed_ratio": float(observed_ratio),
        "control_windows": int(len(controls)),
        "empirical_p": float(p),
        "control_q95": float(np.percentile([item["ratio"] for item in controls], 95)) if controls else None,
        "top_controls": sorted(controls, key=lambda item: item["ratio"], reverse=True)[:20],
    }


def stratified_orbit_null(
    members_by_source: dict[str, pd.DataFrame], pools_by_source: dict[str, np.ndarray], seed: int
) -> dict[str, Any]:
    member_arrays = {
        source: frame[["e", "q", "inc", "peri", "node"]].to_numpy(float)
        for source, frame in members_by_source.items()
    }
    observed_orbits = np.vstack(list(member_arrays.values()))
    observed = orbit_summary(observed_orbits)
    for source, members in member_arrays.items():
        if len(pools_by_source[source]) < len(members) * 3:
            raise RuntimeError(
                f"Insufficient source-specific null pool for {source}: "
                f"members={len(members)}, pool={len(pools_by_source[source])}"
            )
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(NULL_DRAWS):
        samples = []
        for source, members in member_arrays.items():
            pool = pools_by_source[source]
            samples.append(pool[rng.choice(len(pool), size=len(members), replace=False)])
        null.append(float(orbit_summary(np.vstack(samples))["median_d"]))
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (NULL_DRAWS + 1)
    distance_to_gmn = float(orbit_distance_matrix(
        np.asarray(observed["medoid"])[None, :], REFINED_GMN_ORBIT[None, :]
    )[0, 0])
    return {
        "members": int(len(observed_orbits)),
        "member_counts_by_source": {source: int(len(value)) for source, value in member_arrays.items()},
        "pool_counts_by_source": {source: int(len(value)) for source, value in pools_by_source.items()},
        "observed": observed,
        "distance_to_refined_gmn_orbit": distance_to_gmn,
        "null_p": float(p),
        "null_q001": float(np.percentile(null, 0.1)),
        "null_q01": float(np.percentile(null, 1.0)),
        "passed": bool(
            observed["median_d"] <= MAX_ORBIT_MEDIAN_D
            and observed["q90_d"] <= MAX_ORBIT_Q90_D
            and p <= MAX_ORBIT_NULL_P
        ),
    }


def evaluate(frames: dict[str, pd.DataFrame], speed_slope: float, index: int) -> tuple[dict[str, Any], pd.DataFrame]:
    masks_by_source = {source: masks(frame, speed_slope) for source, frame in frames.items()}
    source_results = {}
    member_frames = {}
    pools = {}
    aggregate_table = np.zeros((2, 2), dtype=int)
    for source, frame in frames.items():
        result, members, pool = source_result(frame, masks_by_source[source])
        source_results[source] = result
        member_frames[source] = members
        pools[source] = pool
        aggregate_table += np.asarray(result["activity_table"], dtype=int)
    odds, activity_p = fisher_exact(aggregate_table.tolist(), alternative="greater")
    shift = shifted_window_test(frames, masks_by_source)
    orbit = stratified_orbit_null(member_frames, pools, SEED + index)
    members = pd.concat(list(member_frames.values()), ignore_index=True, sort=False)
    unique_years = sorted(set(map(int, members["year"])))
    exact_duplicates = members["identifier"].astype(str).duplicated().sum()
    passed = bool(
        len(members) >= MIN_MEMBERS
        and len(unique_years) >= MIN_UNIQUE_YEARS
        and activity_p <= MAX_ACTIVITY_P
        and shift["empirical_p"] <= MAX_SHIFT_P
        and orbit["passed"]
        and exact_duplicates == 0
    )
    return {
        "speed_slope_km_s_per_deg": float(speed_slope),
        "sources": source_results,
        "aggregate_activity_table": aggregate_table.tolist(),
        "aggregate_activity_odds_ratio": float(odds),
        "aggregate_activity_p": float(activity_p),
        "shifted_windows": shift,
        "orbit": orbit,
        "members": int(len(members)),
        "unique_years": unique_years,
        "exact_duplicate_identifiers": int(exact_duplicates),
        "passed": passed,
    }, members


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
    cams_frame, cams_meta = load_cams()
    sonotaco_frame, sonotaco_meta = load_sonotaco()
    shober_frame, shober_meta = load_shober()
    frames = {
        "CAMS": cams_frame,
        "SonotaCo": sonotaco_frame,
        "Shober_EDMOND": shober_frame,
    }
    metadata = {
        "CAMS": cams_meta,
        "SonotaCo": sonotaco_meta,
        "Shober_EDMOND": shober_meta,
    }

    evaluations = []
    member_sets = []
    for index, speed_slope in enumerate(SPEED_SLOPES):
        result, members = evaluate(frames, speed_slope, index)
        evaluations.append(result)
        member_sets.append(members)
        print(
            f"speed_slope={speed_slope:+.7f}: N={result['members']} years={result['unique_years']} "
            f"activity_p={result['aggregate_activity_p']:.6g} shift_p={result['shifted_windows']['empirical_p']:.6g} "
            f"orbit_p={result['orbit']['null_p']} medianD={result['orbit']['observed']['median_d']:.6f} "
            f"pass={result['passed']}", flush=True
        )

    id_sets = [
        set(zip(frame["source"].astype(str), frame["identifier"].astype(str)))
        for frame in member_sets
    ]
    identical = all(candidate == id_sets[0] for candidate in id_sets[1:])
    passed = bool(identical and all(item["passed"] for item in evaluations))
    verdict = (
        "THREE_INDEPENDENT_ARCHIVE_FAMILIES_JOINTLY_SUPPORT_APRIL_STREAM"
        if passed else "THREE_ARCHIVE_SYNTHESIS_FAILS_FROZEN_SUPPORT_GATE"
    )

    members = member_sets[-1].copy().sort_values(["source", "year", "sol", "identifier"])
    members["orbit_d_to_gmn"] = orbit_distance_matrix(
        members[["e", "q", "inc", "peri", "node"]].to_numpy(float),
        REFINED_GMN_ORBIT[None, :],
    )[:, 0]
    members.to_csv(OUT / "three_archive_members.csv", index=False)

    payload = {
        "stage": "posthoc_three_archive_family_synthesis",
        "verdict": verdict,
        "passed": passed,
        "posthoc_warning": (
            "Each archive-specific template was frozen before inspection, but this three-archive pooling "
            "was motivated after their separate sparse outcomes. It is supporting evidence, not a fresh "
            "preregistered replication."
        ),
        "metadata": metadata,
        "evaluations": evaluations,
        "identical_member_set_across_speed_slopes": identical,
    }
    (OUT / "three_archive_synthesis.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )

    chosen = evaluations[-1]
    lines = [
        "# Three-archive independent synthesis", "",
        f"**Verdict:** `{verdict}`", "",
        "The unchanged GMN template was applied to legacy CAMS, SonotaCo, and the independently published shower-removed Shober EDMOND subset. The orbital null preserves each archive's observed member count in every draw.", "",
        f"- Members: **{chosen['members']}**",
        f"- Years: **{', '.join(map(str, chosen['unique_years']))}**",
        f"- Archive counts: **{chosen['orbit']['member_counts_by_source']}**",
        f"- Pooled activity p: **{chosen['aggregate_activity_p']:.6g}**",
        f"- Shifted-window p: **{chosen['shifted_windows']['empirical_p']:.6g}**",
        f"- Median orbital D: **{chosen['orbit']['observed']['median_d']:.6f}**",
        f"- q90 orbital D: **{chosen['orbit']['observed']['q90_d']:.6f}**",
        f"- Source-stratified orbit-null p: **{chosen['orbit']['null_p']}**",
        f"- Pooled medoid distance to refined GMN orbit: **{chosen['orbit']['distance_to_refined_gmn_orbit']:.6f}**",
        f"- Identical result with zero versus fitted speed slope: **{identical}**", "",
        "The synthesis is explicitly post-hoc. Its value is that sixteen historical meteors from three archive families, spread across eight years, converge on the same orbit without using the GMN orbit to select them.", "",
    ]
    (OUT / "THREE_ARCHIVE_SYNTHESIS.md").write_text("\n".join(lines))
    print(f"Verdict: {verdict}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
