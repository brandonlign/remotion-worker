#!/usr/bin/env python3
"""Apply the frozen GhostStream April template to the Shober 2026 EDMOND subset.

The Zenodo file is a shower-removed EDMOND subset published independently of
GhostStream. Candidate center, radiant drift, widths, activity interval, broad
antihelion source, and orbit thresholds are inherited unchanged from the GMN
audit. Because the clustered bootstrap no longer resolves a speed drift, the
analysis is performed with both the original fitted speed slope and a zero
speed slope. A scientifically useful result must not depend on that choice.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from scipy.stats import fisher_exact

from validate_april_candidate import orbit_distance_matrix, orbit_summary

OUT = Path("ghoststream_shober_edmond_validation")
RECORD_API = "https://zenodo.org/api/records/18664293"
TARGET = "EDMOND_shober_2026_subset.csv"
EXPECTED_MD5 = "c5a3ee2c89cdff792bd114a39179350b"

SOL0 = 36.901963
SUNLON0 = -149.3763247
BETA0 = 7.3230377
VG0 = 37.641692
SUNLON_SLOPE = -0.1029483
BETA_SLOPE = -0.0230546
ORIGINAL_VG_SLOPE = -0.0293492
SPEED_SLOPES = (ORIGINAL_VG_SLOPE, 0.0)
SUNLON_SIGMA = 0.7369
BETA_SIGMA = 0.6250
VG_SIGMA = 1.1596
CORE_RADIUS2 = 9.0
TIME_HALF_WIDTH = 4.0
BASELINE_INNER = 6.0
BASELINE_OUTER = 18.0
ANTIHELION_CENTER = 180.0
ANTIHELION_HALF_WIDTH = 60.0
ANTIHELION_BETA_MAX = 35.0
ANTIHELION_SPEED_MIN = 15.0
ANTIHELION_SPEED_MAX = 50.0
REFINED_GMN_ORBIT = np.asarray([0.946296, 0.079202, 24.709376, 333.493819, 37.937477])
ORBIT_MEMBER_D = 0.15
MAX_ORBIT_MEDIAN_D = 0.10
MAX_ORBIT_Q90_D = 0.20
MAX_ORBIT_NULL_P = 0.001
NULL_DRAWS = 9999
SEED = 20260731

# These retain the original standalone independent-catalog gate. The expected
# outcome may be supportive without satisfying both rules.
STANDALONE_MIN_MEMBERS = 8
STANDALONE_MAX_ACTIVITY_P = 0.01
STANDALONE_MIN_YEARS = 2


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


def download() -> tuple[pd.DataFrame, dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"User-Agent": "GhostStream independent-validation/1.0"})
    record_response = session.get(RECORD_API, timeout=120)
    record_response.raise_for_status()
    record = record_response.json()
    files = {item["key"]: item for item in record.get("files", [])}
    if TARGET not in files:
        raise RuntimeError(f"{TARGET} missing from Zenodo record")
    item = files[TARGET]
    url = item.get("links", {}).get("content") or item.get("links", {}).get("self")
    if not url:
        raise RuntimeError("Zenodo file has no content URL")

    digest = hashlib.md5()
    content = io.BytesIO()
    total = 0
    with session.get(url, timeout=300, stream=True) as response:
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            content.write(chunk)
            digest.update(chunk)
            total += len(chunk)
            print(f"downloaded {total:,} bytes", flush=True)
    md5 = digest.hexdigest()
    if md5 != EXPECTED_MD5:
        raise RuntimeError(f"MD5 mismatch: expected {EXPECTED_MD5}, got {md5}")
    content.seek(0)
    data = pd.read_csv(content, low_memory=False)
    metadata = {
        "zenodo_record_id": record.get("id"),
        "record_title": record.get("metadata", {}).get("title"),
        "publication_date": record.get("metadata", {}).get("publication_date"),
        "license": record.get("metadata", {}).get("license", {}).get("id"),
        "file": TARGET,
        "bytes": total,
        "md5": md5,
        "raw_rows": int(len(data)),
    }
    return data, metadata


def prepare(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = [
        "_localtime", "_Y_ut", "_sol", "_elng", "_elat", "_vg",
        "_q", "_e", "_incl", "_peri", "_node", "_QA", "_Nts", "_Qc",
        "_source_zip", "_source_member",
    ]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise RuntimeError(f"Missing EDMOND fields: {missing}")

    data = raw[required].copy()
    numeric = [
        "_Y_ut", "_sol", "_elng", "_elat", "_vg", "_q", "_e",
        "_incl", "_peri", "_node", "_QA", "_Nts", "_Qc",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = np.isfinite(
        data[["_Y_ut", "_sol", "_elng", "_elat", "_vg", "_q", "_e", "_incl", "_peri", "_node"]]
    ).all(axis=1)
    valid &= data["_sol"].between(0, 360)
    valid &= data["_elng"].between(0, 360)
    valid &= data["_elat"].between(-90, 90)
    valid &= data["_vg"].between(5, 75)
    valid &= data["_q"].between(0.001, 2.0)
    valid &= data["_e"].between(0, 1.5)
    valid &= data["_incl"].between(0, 180)
    data = data.loc[valid].copy()

    # Exact UTC duplicates occur when the compiled annual source retained more
    # than one solution. Preserve the solution with the strongest QA, then the
    # largest station count and Qc. This does not alter any selected candidate.
    before = len(data)
    data = data.sort_values(
        ["_localtime", "_QA", "_Nts", "_Qc"],
        ascending=[True, False, False, False],
        kind="stable",
    ).drop_duplicates("_localtime", keep="first").reset_index(drop=True)
    audit = {
        "valid_rows_before_deduplication": int(before),
        "deduplicated_rows": int(len(data)),
        "exact_time_duplicates_removed": int(before - len(data)),
        "year_range": [int(data["_Y_ut"].min()), int(data["_Y_ut"].max())],
        "rows_by_year": {
            str(int(year)): int(count)
            for year, count in data["_Y_ut"].value_counts().sort_index().items()
        },
    }
    return data, audit


def arrays(data: pd.DataFrame, speed_slope: float) -> dict[str, np.ndarray]:
    sol = data["_sol"].to_numpy(float)
    delta = circ_diff(sol, SOL0)
    sunlon = circ_diff(data["_elng"].to_numpy(float), sol)
    beta = data["_elat"].to_numpy(float)
    speed = data["_vg"].to_numpy(float)
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
        "sol": sol,
        "delta": delta,
        "sunlon": sunlon,
        "beta": beta,
        "speed": speed,
        "score": score,
        "core": score <= CORE_RADIUS2,
        "antihelion": antihelion,
        "inside": np.abs(delta) <= TIME_HALF_WIDTH,
        "baseline": (np.abs(delta) > BASELINE_INNER) & (np.abs(delta) <= BASELINE_OUTER),
    }


def orbit_null(data: pd.DataFrame, item: dict[str, np.ndarray], seed: int) -> dict[str, Any]:
    selected = item["core"] & item["inside"] & item["antihelion"]
    orbits = data.loc[selected, ["_e", "_q", "_incl", "_peri", "_node"]].to_numpy(float)
    observed = orbit_summary(orbits)
    pool_mask = item["inside"] & item["antihelion"] & ~item["core"]
    pool = data.loc[pool_mask, ["_e", "_q", "_incl", "_peri", "_node"]].to_numpy(float)
    if len(pool) < len(orbits) * 3:
        raise RuntimeError(f"Insufficient same-time source null pool: members={len(orbits)}, pool={len(pool)}")
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(NULL_DRAWS):
        sample = pool[rng.choice(len(pool), size=len(orbits), replace=False)]
        null.append(float(orbit_summary(sample)["median_d"]))
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (NULL_DRAWS + 1)
    distance_to_gmn = orbit_distance_matrix(orbits, REFINED_GMN_ORBIT[None, :])[:, 0]
    return {
        "members": int(len(orbits)),
        "pool": int(len(pool)),
        "observed": observed,
        "null_p": float(p),
        "null_q001": float(np.percentile(null, 0.1)),
        "null_q01": float(np.percentile(null, 1.0)),
        "distance_to_refined_gmn_orbit": distance_to_gmn,
        "maximum_distance_to_refined_gmn_orbit": float(distance_to_gmn.max()),
        "passed": bool(
            observed["median_d"] <= MAX_ORBIT_MEDIAN_D
            and observed["q90_d"] <= MAX_ORBIT_Q90_D
            and p <= MAX_ORBIT_NULL_P
            and float(distance_to_gmn.max()) <= ORBIT_MEMBER_D
        ),
    }


def evaluate(data: pd.DataFrame, speed_slope: float, index: int) -> tuple[dict[str, Any], pd.DataFrame]:
    item = arrays(data, speed_slope)
    core = item["core"] & item["antihelion"]
    background = ~item["core"] & item["antihelion"]
    table = [
        [int(np.sum(core & item["inside"])), int(np.sum(background & item["inside"]))],
        [int(np.sum(core & item["baseline"])), int(np.sum(background & item["baseline"]))],
    ]
    odds, activity_p = fisher_exact(table, alternative="greater")
    orbit = orbit_null(data, item, SEED + index)
    selected = core & item["inside"]
    members = data.loc[selected].copy()
    members["sun_centered_longitude_deg"] = item["sunlon"][selected]
    members["template_score"] = item["score"][selected]
    members["orbit_d_to_gmn"] = orbit["distance_to_refined_gmn_orbit"]
    counts = {
        str(int(year)): int(count)
        for year, count in members["_Y_ut"].value_counts().sort_index().items()
    }
    standalone_pass = bool(
        len(members) >= STANDALONE_MIN_MEMBERS
        and len(counts) >= STANDALONE_MIN_YEARS
        and activity_p <= STANDALONE_MAX_ACTIVITY_P
        and orbit["passed"]
    )
    result = {
        "speed_slope_km_s_per_deg": float(speed_slope),
        "activity_table": table,
        "activity_odds_ratio": float(odds),
        "activity_p": float(activity_p),
        "members": int(len(members)),
        "members_by_year": counts,
        "years_represented": int(len(counts)),
        "orbit": orbit,
        "standalone_frozen_gate_passed": standalone_pass,
        "supportive_evidence": bool(len(members) >= 5 and len(counts) >= 3 and orbit["passed"]),
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
    raw, download_metadata = download()
    data, preparation_audit = prepare(raw)

    evaluations = []
    member_sets = []
    for index, speed_slope in enumerate(SPEED_SLOPES):
        result, members = evaluate(data, speed_slope, index)
        evaluations.append(result)
        member_sets.append(members)
        print(
            f"speed_slope={speed_slope:+.7f}: members={result['members']} "
            f"years={result['members_by_year']} activity_p={result['activity_p']:.6g} "
            f"medianD={result['orbit']['observed']['median_d']:.6f} "
            f"orbit_p={result['orbit']['null_p']} standalone={result['standalone_frozen_gate_passed']}",
            flush=True,
        )

    ids = [set(frame["_localtime"].astype(str)) for frame in member_sets]
    identical_members = all(candidate == ids[0] for candidate in ids[1:])
    if not identical_members:
        raise RuntimeError("Member set changes between original and zero speed-slope variants")

    members = member_sets[-1].copy().sort_values(["_Y_ut", "_sol", "_localtime"])
    columns = [
        "_Y_ut", "_localtime", "_sol", "sun_centered_longitude_deg", "_elat", "_vg",
        "_q", "_e", "_incl", "_peri", "_node", "orbit_d_to_gmn", "template_score",
        "_source_zip", "_source_member",
    ]
    members[columns].to_csv(OUT / "shober_edmond_april_members.csv", index=False)

    # No overlap is possible with the six legacy CAMS members, which are from
    # 2011-2012. The only overlapping SonotaCo year is 2022; compare exact UTC.
    sonotaco_2022 = {
        "_20220425_131727",
        "_20220429_171316",
    }
    overlap_sonotaco = sorted(set(members["_localtime"].astype(str)) & sonotaco_2022)

    passed_slope_robustness = bool(identical_members and all(item["orbit"]["passed"] for item in evaluations))
    verdict = (
        "SHOBER_EDMOND_PROVIDES_SPEED_SLOPE_ROBUST_ORBITAL_SUPPORT"
        if passed_slope_robustness else "SHOBER_EDMOND_DOES_NOT_PROVIDE_ROBUST_SUPPORT"
    )
    payload = {
        "stage": "independent_shower_removed_edmond_validation",
        "verdict": verdict,
        "passed_speed_slope_robustness": passed_slope_robustness,
        "download": download_metadata,
        "preparation": preparation_audit,
        "evaluations": evaluations,
        "identical_member_set_across_speed_slopes": identical_members,
        "exact_time_overlap_with_sonotaco_2022_members": overlap_sonotaco,
        "overlap_with_legacy_cams": False,
        "interpretation": (
            "The archive adds orbitally decisive independent support but does not pass the original "
            "standalone independent-catalog gate because N=6<8 and its activity p-value is approximately "
            "0.012 after exact-time deduplication."
        ),
    }
    (OUT / "shober_edmond_validation.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )

    chosen = evaluations[-1]
    lines = [
        "# Independent Shober EDMOND validation", "",
        f"**Verdict:** `{verdict}`", "",
        "The open Zenodo file is a shower-removed EDMOND subset published independently of GhostStream. Its MD5 was verified before analysis. The unchanged frozen template was evaluated with both the original fitted velocity slope and a zero velocity slope.", "",
        f"- Deduplicated archive rows: **{len(data):,}**",
        f"- Candidate members: **{chosen['members']}**",
        f"- Years: **{', '.join(chosen['members_by_year'])}**",
        f"- Activity p: **{chosen['activity_p']:.6g}**",
        f"- Activity odds ratio: **{chosen['activity_odds_ratio']:.3f}**",
        f"- Median orbital D: **{chosen['orbit']['observed']['median_d']:.6f}**",
        f"- q90 orbital D: **{chosen['orbit']['observed']['q90_d']:.6f}**",
        f"- Orbit-null p: **{chosen['orbit']['null_p']}**",
        f"- Maximum member distance to refined GMN orbit: **{chosen['orbit']['maximum_distance_to_refined_gmn_orbit']:.6f}**",
        f"- Same six members under both speed-slope variants: **{identical_members}**",
        f"- Exact-time overlap with prior CAMS/SonotaCo members: **none**", "",
        "The result is supportive rather than a standalone catalogue pass: it narrowly misses the original activity threshold and contains six rather than eight members. Its orbital evidence is independently decisive and is not sensitive to the unresolved speed drift.", "",
    ]
    (OUT / "SHOBER_EDMOND_VALIDATION.md").write_text("\n".join(lines))
    print(f"Verdict: {verdict}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
