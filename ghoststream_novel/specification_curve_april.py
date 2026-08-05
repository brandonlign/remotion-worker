#!/usr/bin/env python3
"""Frozen 81-cell specification curve for the April stream.

The grid perturbs four plausible analysis choices without using orbit to select
members: fit-error threshold, minimum station count, radiant-core radius, and
activity-window half-width. Every cell uses the same expanded antihelion source
and post-selection orbital compactness test.

Nested cells are sensitivity analyses, not independent replications.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader
from scipy.stats import fisher_exact

from validate_april_candidate import (
    BASE_COLUMNS, CENTER, ORBIT_COLUMNS, SIGMA, circ_diff, deduplicate,
    orbit_distance_matrix, orbit_summary, shower_label, valid_orbits,
)

OUT = Path("ghoststream_april_specification_curve")
YEARS = (2022, 2023, 2024, 2025, 2026)
MONTHS = (3, 4, 5)
FIT_ERROR_THRESHOLDS = (120.0, 180.0, 240.0)
MIN_STATIONS = (2, 3, 4)
RADIANT_SIGMA_RADII = (2.5, 3.0, 3.5)
TIME_HALF_WIDTHS = (3.0, 4.0, 5.0)
BASELINE_INNER = 6.0
BASELINE_OUTER = 18.0

ANTIHELION_CENTER = 180.0
ANTIHELION_HALF_WIDTH = 60.0
ANTIHELION_BETA_MAX = 35.0
ANTIHELION_SPEED_MIN = 15.0
ANTIHELION_SPEED_MAX = 50.0

MIN_ELIGIBLE_MEMBERS = 10
MIN_ELIGIBLE_YEARS = 3
MAX_ACTIVITY_P = 0.01
MAX_MEDIAN_D = 0.10
MAX_Q90_D = 0.20
MIN_PASS_FRACTION = 0.75
MIN_ELIGIBLE_SPECS = 60
MIN_POSITIVE_ODDS_FRACTION = 0.95


def load_raw_season(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    audits = []
    for month in MONTHS:
        stamp = f"{year}-{month:02d}"
        print(f"Downloading {stamp}...", flush=True)
        raw = reader.read_data(
            dd.get_monthly_file_content_by_date(stamp), output_camel_case=True
        ).reset_index(drop=False)
        missing = [column for column in BASE_COLUMNS if column not in raw.columns]
        if missing:
            raise RuntimeError(f"{stamp} missing columns: {missing}")
        data = raw[BASE_COLUMNS].copy()
        data["label"] = data["iau_code"].map(shower_label)
        for column in [
            "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
            *ORBIT_COLUMNS, "medianfiterr_arcsec", "num_stat",
        ]:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        finite = np.isfinite(
            data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]
        ).all(axis=1)
        finite &= data["sol_lon_deg"].between(0, 360)
        finite &= data["lamgeo_deg"].between(0, 360)
        finite &= data["betgeo_deg"].between(-90, 90)
        finite &= data["vgeo_km_s"].between(5, 75)
        basic = data.loc[finite & (data["label"] == "SPORADIC")].copy()
        frames.append(basic)
        audits.append({
            "stamp": stamp,
            "raw_rows": int(len(raw)),
            "basic_sporadic_rows": int(len(basic)),
        })
    combined = pd.concat(frames, ignore_index=True, sort=False)
    delta = circ_diff(combined["sol_lon_deg"].to_numpy(float), CENTER[3])
    combined = combined.loc[np.abs(delta) <= BASELINE_OUTER + 1.0].reset_index(drop=True)
    return combined, {"months": audits, "profile_range_rows": int(len(combined))}


def prepare_quality_subset(
    raw: pd.DataFrame, fit_threshold: float, min_stations: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    mask = (
        (raw["medianfiterr_arcsec"].fillna(1e9) <= fit_threshold)
        & (raw["num_stat"].fillna(0) >= min_stations)
    )
    filtered = raw.loc[mask].reset_index(drop=True)
    deduped, audit = deduplicate(filtered)
    delta = circ_diff(deduped["sol_lon_deg"].to_numpy(float), CENTER[3])
    keep = np.abs(delta) <= BASELINE_OUTER
    return deduped.loc[keep].reset_index(drop=True), audit


def arrays(data: pd.DataFrame) -> dict[str, np.ndarray]:
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
        speed >= ANTIHELION_SPEED_MIN
    ) & (speed <= ANTIHELION_SPEED_MAX)
    return {
        "sol": sol,
        "delta": circ_diff(sol, CENTER[3]),
        "score": score,
        "antihelion": antihelion,
    }


def evaluate(
    prepared: dict[tuple[int, float, int], pd.DataFrame],
    fit_threshold: float,
    min_stations: int,
    radiant_sigma: float,
    time_half_width: float,
) -> dict[str, Any]:
    aggregate_table = np.zeros((2, 2), dtype=int)
    member_frames = []
    counts_by_year: dict[str, int] = {}
    medoids = []

    for year in YEARS:
        data = prepared[(year, fit_threshold, min_stations)]
        item = arrays(data)
        core = item["score"] <= radiant_sigma ** 2
        inside = np.abs(item["delta"]) <= time_half_width
        baseline = (
            (np.abs(item["delta"]) > BASELINE_INNER)
            & (np.abs(item["delta"]) <= BASELINE_OUTER)
        )
        source = item["antihelion"]
        stream = core & source
        background = (~core) & source
        table = np.asarray([
            [np.sum(stream & inside), np.sum(background & inside)],
            [np.sum(stream & baseline), np.sum(background & baseline)],
        ], dtype=int)
        aggregate_table += table

        selected = stream & inside & valid_orbits(data)
        members = data.loc[selected].copy()
        members["year"] = year
        member_frames.append(members)
        counts_by_year[str(year)] = int(len(members))
        if len(members) >= 3:
            medoids.append(
                orbit_summary(members[ORBIT_COLUMNS].to_numpy(float))["medoid"]
            )

    odds, activity_p = fisher_exact(aggregate_table.tolist(), alternative="greater")
    members = pd.concat(member_frames, ignore_index=True, sort=False)
    if len(members) >= 2:
        orbit = orbit_summary(members[ORBIT_COLUMNS].to_numpy(float))
    else:
        orbit = {"medoid": [float("nan")] * 5, "median_d": float("inf"), "q90_d": float("inf")}

    if len(medoids) >= 2:
        medoid_array = np.asarray(medoids, dtype=float)
        matrix = orbit_distance_matrix(medoid_array)
        max_cross_year = float(np.max(matrix))
    else:
        max_cross_year = float("inf")

    represented_years = sum(count >= 1 for count in counts_by_year.values())
    eligible = bool(
        len(members) >= MIN_ELIGIBLE_MEMBERS
        and represented_years >= MIN_ELIGIBLE_YEARS
    )
    passed = bool(
        eligible
        and activity_p <= MAX_ACTIVITY_P
        and float(odds) > 1.0
        and orbit["median_d"] <= MAX_MEDIAN_D
        and orbit["q90_d"] <= MAX_Q90_D
    )
    return {
        "fit_error_arcsec": fit_threshold,
        "minimum_stations": min_stations,
        "radiant_sigma_radius": radiant_sigma,
        "time_half_width_deg": time_half_width,
        "activity_table": aggregate_table.tolist(),
        "odds_ratio": float(odds),
        "activity_p": float(activity_p),
        "members": int(len(members)),
        "members_by_year": counts_by_year,
        "represented_years": int(represented_years),
        "orbit_median_d": float(orbit["median_d"]),
        "orbit_q90_d": float(orbit["q90_d"]),
        "maximum_cross_year_medoid_d": max_cross_year,
        "eligible": eligible,
        "passed": passed,
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
    raw_by_year = {}
    catalog_audits = {}
    for year in YEARS:
        raw, audit = load_raw_season(year)
        raw_by_year[year] = raw
        catalog_audits[str(year)] = audit
        print(f"{year}: profile-range basic sporadics={len(raw):,}", flush=True)

    prepared: dict[tuple[int, float, int], pd.DataFrame] = {}
    quality_audits: dict[str, Any] = {}
    for year, fit_threshold, min_stations in itertools.product(
        YEARS, FIT_ERROR_THRESHOLDS, MIN_STATIONS
    ):
        data, audit = prepare_quality_subset(
            raw_by_year[year], fit_threshold, min_stations
        )
        prepared[(year, fit_threshold, min_stations)] = data
        quality_audits[f"{year}|{fit_threshold}|{min_stations}"] = {
            "rows": int(len(data)), "deduplication": audit,
        }

    results = []
    for fit_threshold, min_stations, radiant_sigma, time_half_width in itertools.product(
        FIT_ERROR_THRESHOLDS, MIN_STATIONS, RADIANT_SIGMA_RADII, TIME_HALF_WIDTHS
    ):
        result = evaluate(
            prepared, fit_threshold, min_stations, radiant_sigma, time_half_width
        )
        results.append(result)
        print(
            f"fit={fit_threshold:.0f} stations={min_stations} radius={radiant_sigma:.1f} "
            f"time={time_half_width:.1f} N={result['members']} p={result['activity_p']:.3g} "
            f"medianD={result['orbit_median_d']:.4f} pass={result['passed']}",
            flush=True,
        )

    frame = pd.DataFrame(results)
    eligible = frame["eligible"]
    eligible_count = int(eligible.sum())
    pass_count = int(frame.loc[eligible, "passed"].sum())
    pass_fraction = float(pass_count / eligible_count) if eligible_count else 0.0
    positive_fraction = float((frame.loc[eligible, "odds_ratio"] > 1.0).mean()) if eligible_count else 0.0
    gate_passed = bool(
        eligible_count >= MIN_ELIGIBLE_SPECS
        and pass_fraction >= MIN_PASS_FRACTION
        and positive_fraction >= MIN_POSITIVE_ODDS_FRACTION
    )
    verdict = (
        "APRIL_STREAM_ROBUST_ACROSS_FROZEN_SPECIFICATION_GRID"
        if gate_passed else "APRIL_STREAM_SENSITIVE_TO_SPECIFICATION_GRID"
    )

    frame.to_csv(OUT / "specification_curve.csv", index=False)
    summary = {
        "stage": "frozen_81_cell_specification_curve",
        "verdict": verdict,
        "passed": gate_passed,
        "grid": {
            "fit_error_arcsec": list(FIT_ERROR_THRESHOLDS),
            "minimum_stations": list(MIN_STATIONS),
            "radiant_sigma_radius": list(RADIANT_SIGMA_RADII),
            "time_half_width_deg": list(TIME_HALF_WIDTHS),
            "total_cells": int(len(frame)),
        },
        "rules": {
            "eligible_minimum_members": MIN_ELIGIBLE_MEMBERS,
            "eligible_minimum_years": MIN_ELIGIBLE_YEARS,
            "maximum_activity_p": MAX_ACTIVITY_P,
            "maximum_orbit_median_d": MAX_MEDIAN_D,
            "maximum_orbit_q90_d": MAX_Q90_D,
            "minimum_eligible_cells": MIN_ELIGIBLE_SPECS,
            "minimum_pass_fraction": MIN_PASS_FRACTION,
            "minimum_positive_odds_fraction": MIN_POSITIVE_ODDS_FRACTION,
        },
        "eligible_cells": eligible_count,
        "passing_cells": pass_count,
        "pass_fraction": pass_fraction,
        "positive_odds_fraction": positive_fraction,
        "activity_p_quantiles_eligible": {
            str(q): float(frame.loc[eligible, "activity_p"].quantile(q))
            for q in (0.0, 0.25, 0.5, 0.75, 1.0)
        },
        "member_count_range_eligible": [
            int(frame.loc[eligible, "members"].min()) if eligible_count else 0,
            int(frame.loc[eligible, "members"].max()) if eligible_count else 0,
        ],
        "orbit_median_d_range_eligible": [
            float(frame.loc[eligible, "orbit_median_d"].min()) if eligible_count else None,
            float(frame.loc[eligible, "orbit_median_d"].max()) if eligible_count else None,
        ],
        "results": results,
        "catalog_audits": catalog_audits,
        "quality_audits": quality_audits,
        "interpretation": (
            "Cells are nested sensitivity analyses and must not be counted as independent confirmations. "
            "The gate asks whether the conclusion survives a broad, frozen neighborhood of reasonable choices."
        ),
    }
    (OUT / "specification_curve.json").write_text(
        json.dumps(jsonable(summary), indent=2) + "\n"
    )

    lines = [
        "# Frozen specification curve", "",
        f"**Verdict:** `{verdict}`", "",
        "The grid perturbs fit error, minimum station count, radiant-core radius, and activity-window width. Orbit is not used to select members in any cell; it is tested after radiant-speed-time selection.", "",
        f"- Total cells: **{len(frame)}**",
        f"- Eligible cells: **{eligible_count}**",
        f"- Passing eligible cells: **{pass_count}**",
        f"- Pass fraction: **{pass_fraction:.1%}**",
        f"- Positive-odds fraction: **{positive_fraction:.1%}**",
        f"- Eligible member-count range: **{summary['member_count_range_eligible']}**",
        f"- Eligible median-D range: **{summary['orbit_median_d_range_eligible']}**",
        f"- Worst eligible activity p: **{summary['activity_p_quantiles_eligible']['1.0']:.6g}**", "",
        "These cells are nested robustness checks, not 81 independent replications.", "",
    ]
    (OUT / "SPECIFICATION_CURVE.md").write_text("\n".join(lines))

    print(f"Verdict: {verdict}")
    print(f"Eligible={eligible_count} passing={pass_count} fraction={pass_fraction:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
