#!/usr/bin/env python3
"""Validate the April stream in disjoint GMN geographic station groups.

Each trajectory is assigned to exactly one region by the majority of parsed
station-country prefixes. Ties and unclassified events are excluded. The frozen
radiant-speed-time definition is tested separately in the Americas, Europe/
West Asia, and Oceania/East Asia/Africa. Orbit is evaluated only after
radiant-speed-time selection.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

from estimate_april_activity_profile_v2 import load_season
from validate_april_candidate import (
    ORBIT_COLUMNS, circ_diff, orbit_distance_matrix, orbit_summary,
    station_ids, valid_orbits,
)
from validate_april_source_null import CENTER, features

OUT = Path("ghoststream_geographic_splits")
YEARS = (2022, 2023, 2024, 2025, 2026)
TIME_HALF_WIDTH = 4.0
BASELINE_INNER = 6.0
BASELINE_OUTER = 18.0
NULL_DRAWS = 9999
SEED = 20260731
MIN_MEMBERS = 8
MAX_ACTIVITY_P = 0.01
MAX_ORBIT_NULL_P = 0.001
MAX_MEDIAN_D = 0.10
MAX_Q90_D = 0.20
MAX_CROSS_REGION_MEDOID_D = 0.12

REGION_COUNTRIES = {
    "Americas": {"US", "CA", "MX", "BR"},
    "Europe_WestAsia": {
        "UK", "IE", "FR", "BE", "NL", "DE", "ES", "PT", "IT", "CH", "AT",
        "CZ", "SK", "HU", "RO", "HR", "SI", "RS", "BA", "ME", "PL", "RU",
        "UA", "IL", "GR", "BG", "TR",
    },
    "Oceania_EastAsia_Africa": {
        "AU", "NZ", "KR", "JP", "CN", "TW", "MY", "SG", "TH", "ID", "PH",
        "IN", "ZA", "NA", "BW", "KE", "MA",
    },
}
COUNTRY_TO_REGION = {
    country: region for region, countries in REGION_COUNTRIES.items() for country in countries
}


def classify_station_group(value: Any) -> tuple[str | None, list[str], dict[str, int]]:
    stations = station_ids(value)
    countries = sorted({station[:2] for station in stations if len(station) >= 2})
    counts = {region: 0 for region in REGION_COUNTRIES}
    for station in stations:
        region = COUNTRY_TO_REGION.get(station[:2])
        if region is not None:
            counts[region] += 1
    maximum = max(counts.values()) if counts else 0
    winners = [region for region, count in counts.items() if count == maximum and count > 0]
    return (winners[0] if len(winners) == 1 else None), countries, counts


def orbit_null(data: pd.DataFrame, f: dict[str, np.ndarray], region_mask: np.ndarray,
               selected: np.ndarray, seed: int) -> dict[str, Any]:
    member_orbits = data.loc[selected, ORBIT_COLUMNS].to_numpy(float)
    if len(member_orbits) < MIN_MEMBERS:
        return {"members": int(len(member_orbits)), "passed": False, "reason": "too_few_members"}
    observed = orbit_summary(member_orbits)
    temporal = np.abs(circ_diff(f["sol"], CENTER[3])) <= TIME_HALF_WIDTH
    pool_mask = region_mask & temporal & f["antihelion"] & ~f["core"] & valid_orbits(data)
    pool = data.loc[pool_mask, ORBIT_COLUMNS].to_numpy(float)
    pool_kind = "same_time_same_region_antihelion_outside_core"
    if len(pool) < len(member_orbits) * 3:
        delta = np.abs(circ_diff(f["sol"], CENTER[3]))
        pool_mask = (
            region_mask & (delta <= BASELINE_OUTER) & f["antihelion"]
            & ~f["core"] & valid_orbits(data)
        )
        pool = data.loc[pool_mask, ORBIT_COLUMNS].to_numpy(float)
        pool_kind = "season_same_region_antihelion_outside_core"
    if len(pool) < len(member_orbits) * 3:
        return {
            "members": int(len(member_orbits)), "pool": int(len(pool)),
            "observed": observed, "pool_kind": pool_kind,
            "passed": False, "reason": "insufficient_null_pool",
        }
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(NULL_DRAWS):
        sample = pool[rng.choice(len(pool), size=len(member_orbits), replace=False)]
        null.append(float(orbit_summary(sample)["median_d"]))
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (NULL_DRAWS + 1)
    return {
        "members": int(len(member_orbits)),
        "pool": int(len(pool)),
        "pool_kind": pool_kind,
        "observed": observed,
        "null_p": float(p),
        "null_q001": float(np.percentile(null, 0.1)),
        "null_q01": float(np.percentile(null, 1.0)),
        "passed": bool(
            observed["median_d"] <= MAX_MEDIAN_D
            and observed["q90_d"] <= MAX_Q90_D
            and p <= MAX_ORBIT_NULL_P
        ),
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
    frames = []
    audits = {}
    for year in YEARS:
        data, audit = load_season(year)
        data = data.copy()
        data["year"] = year
        frames.append(data)
        audits[str(year)] = audit
        print(f"{year}: {len(data):,} seasonal quality sporadics", flush=True)
    data = pd.concat(frames, ignore_index=True, sort=False)

    classifications = data["participating_stations"].map(classify_station_group)
    data["geo_region"] = [item[0] for item in classifications]
    data["station_countries"] = [";".join(item[1]) for item in classifications]
    data["region_station_counts"] = [json.dumps(item[2], sort_keys=True) for item in classifications]
    classified = data["geo_region"].notna().to_numpy()
    f = features(data)
    delta = circ_diff(f["sol"], CENTER[3])
    inside = np.abs(delta) <= TIME_HALF_WIDTH
    baseline = (np.abs(delta) > BASELINE_INNER) & (np.abs(delta) <= BASELINE_OUTER)

    results = {}
    member_rows = []
    medoids = {}
    for index, region in enumerate(REGION_COUNTRIES):
        region_mask = data["geo_region"].eq(region).to_numpy()
        core = region_mask & f["antihelion"] & f["core"]
        background = region_mask & f["antihelion"] & ~f["core"]
        selected = core & inside & valid_orbits(data)
        table = [
            [int(np.sum(core & inside)), int(np.sum(background & inside))],
            [int(np.sum(core & baseline)), int(np.sum(background & baseline))],
        ]
        odds, activity_p = fisher_exact(table, alternative="greater")
        orbit = orbit_null(data, f, region_mask, selected, SEED + 1000 * index)
        members = data.loc[selected].copy()
        members["sun_centered_lon"] = circ_diff(
            members["lamgeo_deg"].to_numpy(float), members["sol_lon_deg"].to_numpy(float)
        )
        member_rows.append(members)
        if orbit.get("observed"):
            medoids[region] = np.asarray(orbit["observed"]["medoid"], dtype=float)
        by_year = {
            str(int(year)): int(count)
            for year, count in members["year"].value_counts().sort_index().items()
        }
        countries = sorted({
            country for text in members["station_countries"].astype(str)
            for country in text.split(";") if country
        })
        passed = bool(
            len(members) >= MIN_MEMBERS
            and activity_p <= MAX_ACTIVITY_P
            and orbit.get("passed", False)
            and len(by_year) >= 3
        )
        results[region] = {
            "classified_quality_events": int(np.sum(region_mask)),
            "activity_table": table,
            "activity_odds_ratio": float(odds),
            "activity_p": float(activity_p),
            "members": int(len(members)),
            "members_by_year": by_year,
            "member_country_codes": countries,
            "orbit": orbit,
            "passed": passed,
        }
        print(
            f"{region}: members={len(members)} years={by_year} activity_p={activity_p:.4g} "
            f"orbit_p={orbit.get('null_p')} passed={passed}", flush=True
        )

    cross = []
    region_names = sorted(medoids)
    for i, first in enumerate(region_names):
        for second in region_names[i + 1:]:
            distance = float(orbit_distance_matrix(
                medoids[first][None, :], medoids[second][None, :]
            )[0, 0])
            cross.append({"first": first, "second": second, "d": distance})
    max_cross = max((item["d"] for item in cross), default=float("inf"))
    passed = bool(
        all(results[region]["passed"] for region in REGION_COUNTRIES)
        and max_cross <= MAX_CROSS_REGION_MEDOID_D
    )
    verdict = (
        "APRIL_STREAM_REPLICATES_ACROSS_THREE_DISJOINT_GMN_GEOGRAPHIC_GROUPS"
        if passed else "APRIL_STREAM_FAILS_THREE_WAY_GEOGRAPHIC_REPLICATION"
    )

    all_members = pd.concat(member_rows, ignore_index=True, sort=False)
    columns = [
        "geo_region", "year", "unique_trajectory_identifier", "beginning_utc_time",
        "sol_lon_deg", "sun_centered_lon", "betgeo_deg", "vgeo_km_s",
        *ORBIT_COLUMNS, "participating_stations", "station_countries",
    ]
    all_members[columns].to_csv(OUT / "geographic_split_members.csv", index=False)

    payload = {
        "stage": "disjoint_geographic_station_network_replication",
        "verdict": verdict,
        "passed": passed,
        "classification_rule": (
            "Each trajectory is assigned to the unique region containing the majority of its parsed participating stations; ties and unknown prefixes are excluded."
        ),
        "region_country_sets": {key: sorted(value) for key, value in REGION_COUNTRIES.items()},
        "total_quality_events": int(len(data)),
        "classified_quality_events": int(np.sum(classified)),
        "unclassified_or_tied_events": int(len(data) - np.sum(classified)),
        "regions": results,
        "cross_region_medoid_distances": cross,
        "maximum_cross_region_medoid_d": float(max_cross),
        "rules": {
            "minimum_members": MIN_MEMBERS,
            "minimum_years": 3,
            "maximum_activity_p": MAX_ACTIVITY_P,
            "maximum_orbit_null_p": MAX_ORBIT_NULL_P,
            "maximum_median_d": MAX_MEDIAN_D,
            "maximum_q90_d": MAX_Q90_D,
            "maximum_cross_region_medoid_d": MAX_CROSS_REGION_MEDOID_D,
        },
        "catalog_audits": audits,
    }
    (OUT / "geographic_split_validation.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )

    lines = [
        "# Disjoint geographic GMN replication", "",
        f"**Verdict:** `{verdict}`", "",
        "Trajectories were assigned to exactly one geographic station group by majority station-country prefix. Ties and unknown prefixes were excluded. Thus no trajectory contributes to more than one regional test.", "",
        "| Region | Members | Years | Activity p | Median D | Orbit-null p | Pass |",
        "|---|---:|---|---:|---:|---:|:---:|",
    ]
    for region in REGION_COUNTRIES:
        item = results[region]
        lines.append(
            f"| {region} | {item['members']} | {','.join(item['members_by_year'])} | "
            f"{item['activity_p']:.6g} | {item['orbit'].get('observed', {}).get('median_d', float('nan')):.5f} | "
            f"{item['orbit'].get('null_p')} | {item['passed']} |"
        )
    lines += ["", f"Maximum cross-region medoid distance: **{max_cross:.5f}**", "",
              "This is a geographically disjoint robustness test within the GMN processing system, not a fully independent reduction pipeline.", ""]
    (OUT / "GEOGRAPHIC_SPLIT_VALIDATION.md").write_text("\n".join(lines))

    print(f"Verdict: {verdict}")
    print(f"Maximum cross-region medoid D: {max_cross}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
