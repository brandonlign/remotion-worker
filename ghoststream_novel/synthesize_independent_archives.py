#!/usr/bin/env python3
"""Exploratory pooled synthesis of independent CAMS and SonotaCo evidence.

The individual archive rules were fixed before their results. This pooled test
is explicitly labeled exploratory because it is performed after seeing those
small-sample results. It uses the unchanged GMN radiant/drift/activity template,
combines source-preserving contingency tables, and tests orbital compactness
against a pooled antihelion/time null without using orbit to select members.
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

OUT = Path("ghoststream_independent_synthesis")
SEED = 20260731
NULL_DRAWS = 19999
TIME_HALF_WIDTH = 4.0
SEASON_HALF_WIDTH = 18.0
SOL0 = cams.SOL0
CORE_RADIUS2 = cams.CORE_RADIUS2
LOCAL_RADIUS2 = cams.LOCAL_RADIUS2
MAX_ORBIT_MEDIAN_D = 0.12
MAX_ORBIT_Q90_D = 0.22
MAX_ORBIT_NULL_P = 0.001
MIN_MEMBERS = 8
MIN_YEARS = 4
MAX_ACTIVITY_P = 0.005
MAX_SHIFT_P = 0.05
GMN_ORBIT = cams.REFINED_ORBIT


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


def canonical_sonotaco() -> tuple[pd.DataFrame, dict[str, Any]]:
    frames, meta = [], {}
    for year in (2022, 2023, 2024, 2025):
        frame, info = independent.corrected_sonotaco(year)
        frame = frame.rename(columns={"identifier": "id"}).copy()
        frame["peri_norm"] = frame["peri"]
        frames.append(frame)
        meta[str(year)] = info
    return pd.concat(frames, ignore_index=True, sort=False), meta


def common_masks(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    sol = frame["sol"].to_numpy(float)
    delta = circ_diff(sol, SOL0)
    pred_sun = cams.SUNLON0 + cams.SUNLON_SLOPE * delta
    pred_beta = cams.BETA0 + cams.BETA_SLOPE * delta
    pred_vg = cams.VG0 + cams.VG_SLOPE * delta
    score = ((circ_diff(frame["sunlon"].to_numpy(float), pred_sun) / cams.SUNLON_SIGMA) ** 2
             + ((frame["beta"].to_numpy(float) - pred_beta) / cams.BETA_SIGMA) ** 2
             + ((frame["vg"].to_numpy(float) - pred_vg) / cams.VG_SIGMA) ** 2)
    antihelion = (
        np.abs(circ_diff(frame["sunlon"].to_numpy(float) % 360.0, cams.ANTIHELION_CENTER))
        <= cams.ANTIHELION_HALF_WIDTH
    )
    antihelion &= np.abs(frame["beta"].to_numpy(float)) <= cams.ANTIHELION_BETA_MAX
    antihelion &= frame["vg"].to_numpy(float) >= cams.ANTIHELION_SPEED_MIN
    antihelion &= frame["vg"].to_numpy(float) <= cams.ANTIHELION_SPEED_MAX
    return {
        "delta": delta,
        "score": score,
        "core": score <= CORE_RADIUS2,
        "local": score <= LOCAL_RADIUS2,
        "antihelion": antihelion,
        "season": np.abs(delta) <= SEASON_HALF_WIDTH,
        "temporal": np.abs(delta) <= TIME_HALF_WIDTH,
    }


def activity_counts(frame: pd.DataFrame, mask: dict[str, np.ndarray]) -> np.ndarray:
    background = mask["antihelion"] & mask["season"]
    core = mask["core"] & background
    inside = mask["temporal"]
    return np.asarray([
        [np.sum(core & inside), np.sum(background & inside & ~core)],
        [np.sum(core & ~inside), np.sum(background & ~inside & ~core)],
    ], dtype=int)


def shifted_test(frames: list[tuple[pd.DataFrame, dict[str, np.ndarray]]]) -> dict[str, Any]:
    observed_num = observed_den = 0
    for frame, mask in frames:
        observed_num += int(np.sum(mask["core"] & mask["antihelion"] & mask["temporal"]))
        observed_den += int(np.sum(mask["antihelion"] & mask["temporal"]))
    observed_ratio = observed_num / observed_den if observed_den else 0.0
    controls = []
    for offset in np.arange(-SEASON_HALF_WIDTH + TIME_HALF_WIDTH,
                            SEASON_HALF_WIDTH - TIME_HALF_WIDTH + 1e-9, 0.25):
        if abs(offset) <= 2 * TIME_HALF_WIDTH:
            continue
        center = (SOL0 + offset) % 360.0
        num = den = 0
        for frame, mask in frames:
            window = np.abs(circ_diff(frame["sol"].to_numpy(float), center)) <= TIME_HALF_WIDTH
            background = mask["antihelion"] & mask["season"]
            num += int(np.sum(mask["core"] & background & window))
            den += int(np.sum(background & window))
        if den < 10:
            continue
        controls.append({"offset": float(offset), "core": num, "background": den,
                         "ratio": float(num / den)})
    p = ((1 + sum(item["ratio"] >= observed_ratio for item in controls)) /
         (1 + len(controls))) if controls else 1.0
    return {
        "observed_core": observed_num,
        "observed_background": observed_den,
        "observed_ratio": float(observed_ratio),
        "control_windows": len(controls),
        "empirical_p": float(p),
        "control_q95": float(np.percentile([item["ratio"] for item in controls], 95)) if controls else None,
        "top_controls": sorted(controls, key=lambda item: item["ratio"], reverse=True)[:20],
    }


def pooled_orbit_test(frames: list[tuple[pd.DataFrame, dict[str, np.ndarray]]]) -> tuple[dict[str, Any], pd.DataFrame]:
    member_frames, pool_arrays = [], []
    for frame, mask in frames:
        selected = mask["core"] & mask["antihelion"] & mask["temporal"]
        members = frame.loc[selected].copy()
        member_frames.append(members)
        pool_mask = mask["antihelion"] & mask["temporal"] & ~mask["core"]
        pool_arrays.append(frame.loc[pool_mask, ["e", "q", "inc", "peri_norm", "node"]].to_numpy(float))
    members = pd.concat(member_frames, ignore_index=True, sort=False)
    orbits = members[["e", "q", "inc", "peri_norm", "node"]].to_numpy(float)
    observed = cams.orbit_summary(orbits)
    pool = np.vstack(pool_arrays)
    if len(pool) < len(orbits) * 3:
        raise RuntimeError(f"Pooled orbit null is too small: members={len(orbits)}, pool={len(pool)}")
    rng = np.random.default_rng(SEED)
    null = []
    for _ in range(NULL_DRAWS):
        sample = pool[rng.choice(len(pool), size=len(orbits), replace=False)]
        null.append(cams.orbit_summary(sample)["median_d"])
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (NULL_DRAWS + 1)
    gmn_distance = float(cams.orbit_distance_matrix(
        np.asarray(observed["medoid"])[None, :], GMN_ORBIT[None, :]
    )[0, 0])
    result = {
        "members": int(len(orbits)),
        "pool": int(len(pool)),
        "observed": observed,
        "distance_to_gmn_refined_orbit": gmn_distance,
        "null_p": float(p),
        "null_q001": float(np.percentile(null, 0.1)),
        "null_q01": float(np.percentile(null, 1)),
        "passed": bool(
            observed["median_d"] <= MAX_ORBIT_MEDIAN_D
            and observed["q90_d"] <= MAX_ORBIT_Q90_D
            and p <= MAX_ORBIT_NULL_P
        ),
    }
    return result, members


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
    cams_frame = cams.parse_catalog().copy()
    cams_frame["source"] = "CAMS"
    son_frame, son_meta = canonical_sonotaco()
    cams_mask = common_masks(cams_frame)
    son_mask = common_masks(son_frame)
    frame_masks = [(cams_frame, cams_mask), (son_frame, son_mask)]

    cams_table = activity_counts(cams_frame, cams_mask)
    son_table = activity_counts(son_frame, son_mask)
    pooled_table = cams_table + son_table
    odds, activity_p = fisher_exact(pooled_table.tolist(), alternative="greater")
    shift = shifted_test(frame_masks)
    orbit, members = pooled_orbit_test(frame_masks)
    member_counts = {
        f"{source}-{int(year)}": int(count)
        for (source, year), count in members.groupby(["source", "year"]).size().items()
    }
    active_years = sorted(set(map(int, members["year"].tolist())))
    passed = bool(
        len(members) >= MIN_MEMBERS
        and len(active_years) >= MIN_YEARS
        and activity_p <= MAX_ACTIVITY_P
        and shift["empirical_p"] <= MAX_SHIFT_P
        and orbit["passed"]
    )
    verdict = (
        "INDEPENDENT_ARCHIVES_JOINTLY_SUPPORT_APRIL_STREAM"
        if passed else "INDEPENDENT_ARCHIVES_DO_NOT_JOINTLY_SUPPORT_APRIL_STREAM"
    )
    members = members.copy()
    members["orbit_d_to_gmn"] = cams.orbit_distance_matrix(
        members[["e", "q", "inc", "peri_norm", "node"]].to_numpy(float),
        GMN_ORBIT[None, :],
    )[:, 0]
    members[["source", "year", "id", "sol", "sunlon", "beta", "vg",
             "e", "q", "inc", "peri_norm", "node", "orbit_d_to_gmn"]].to_csv(
        OUT / "pooled_independent_members.csv", index=False
    )
    payload = {
        "stage": "exploratory_pooled_independent_archive_synthesis",
        "verdict": verdict,
        "passed": passed,
        "posthoc_warning": (
            "The archive-specific tests were frozen before each result, but this pooled synthesis "
            "was motivated by their small-sample outcomes and is therefore exploratory."
        ),
        "catalogs": {
            "CAMS": {"rows": int(len(cams_frame)), "activity_table": cams_table},
            "SonotaCo": {"rows": int(len(son_frame)), "activity_table": son_table,
                         "downloads": son_meta},
        },
        "pooled_activity": {
            "table": pooled_table,
            "odds_ratio": float(odds),
            "p": float(activity_p),
        },
        "pooled_shifted_windows": shift,
        "pooled_orbit": orbit,
        "members": int(len(members)),
        "active_years": active_years,
        "member_counts": member_counts,
        "rules": {
            "minimum_members": MIN_MEMBERS,
            "minimum_years": MIN_YEARS,
            "maximum_activity_p": MAX_ACTIVITY_P,
            "maximum_shift_p": MAX_SHIFT_P,
            "maximum_orbit_null_p": MAX_ORBIT_NULL_P,
        },
    }
    (OUT / "independent_archive_synthesis.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )
    lines = [
        "# Pooled independent-archive synthesis", "",
        f"**Verdict:** `{verdict}`", "",
        "This is an explicitly exploratory synthesis of the separately tested legacy CAMS and SonotaCo archives.", "",
        f"- Independent members: **{len(members)}**",
        f"- Years represented: **{active_years}**",
        f"- Member counts: `{member_counts}`",
        f"- Pooled activity p: **{activity_p:.8g}**",
        f"- Pooled shifted-window p: **{shift['empirical_p']:.8g}**",
        f"- Pooled orbit median D: **{orbit['observed']['median_d']:.6f}**",
        f"- Pooled orbit-null p: **{orbit['null_p']:.8g}**",
        f"- Pooled medoid distance to refined GMN orbit: **{orbit['distance_to_gmn_refined_orbit']:.6f}**", "",
        "This strengthens external support but does not replace a fresh, preregistered network replication or official IAU review.", "",
    ]
    (OUT / "INDEPENDENT_ARCHIVE_SYNTHESIS.md").write_text("\n".join(lines))
    print(f"Verdict: {verdict}")
    print(f"Members: {len(members)} years={active_years} counts={member_counts}")
    print(f"Activity table={pooled_table.tolist()} p={activity_p}")
    print(f"Shift p={shift['empirical_p']}")
    print(f"Orbit={orbit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
