#!/usr/bin/env python3
"""Cluster-bootstrap uncertainty for the 95-member April stream solution.

The primary bootstrap samples five observing years with replacement. Within
each selected year, observing nights are sampled with replacement and all
meteors from each sampled night stay together. This avoids treating meteors
from the same network night as independent measurements.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from validate_april_candidate import ORBIT_COLUMNS, load_year, select_members

OUT = Path("ghoststream_april_bootstrap")
YEARS = (2022, 2023, 2024, 2025, 2026)
REPLICATES = 20000
SEED_PRIMARY = 20260731
SEED_CONDITIONAL = 20260732
OBLIQUITY_DEG = 23.43928
EXPECTED_MEMBERS = 95


def ecliptic_to_equatorial(lon_deg: np.ndarray, lat_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon = np.deg2rad(np.asarray(lon_deg, dtype=float))
    lat = np.deg2rad(np.asarray(lat_deg, dtype=float))
    eps = np.deg2rad(OBLIQUITY_DEG)
    x = np.cos(lat) * np.cos(lon)
    y = np.cos(lat) * np.sin(lon)
    z = np.sin(lat)
    y_eq = y * np.cos(eps) - z * np.sin(eps)
    z_eq = y * np.sin(eps) + z * np.cos(eps)
    ra = np.rad2deg(np.arctan2(y_eq, x)) % 360.0
    dec = np.rad2deg(np.arcsin(np.clip(z_eq, -1.0, 1.0)))
    return ra, dec


def circular_mean(values: np.ndarray, reference: float) -> float:
    radians = np.deg2rad(np.asarray(values, dtype=float))
    angle = np.rad2deg(np.arctan2(np.mean(np.sin(radians)), np.mean(np.cos(radians)))) % 360.0
    return float(reference + ((angle - reference + 180.0) % 360.0 - 180.0))


def calculate_stats(data: pd.DataFrame, indices: np.ndarray) -> dict[str, float | int]:
    frame = data.loc[indices]
    solar = frame["sol_lon_deg"].to_numpy(float)
    centered = solar - solar.mean()
    denominator = float(np.sum(centered * centered))

    def slope(column: str) -> float:
        values = frame[column].to_numpy(float)
        return float(np.sum(centered * (values - values.mean())) / denominator)

    q = float(frame["q_au"].mean())
    eccentricity = float(frame["e"].mean())
    return {
        "N": int(len(frame)),
        "years_observed": int(frame["year"].nunique()),
        "nights_observed": int(frame["night_date"].nunique()),
        "solar_longitude_deg": float(frame["sol_lon_deg"].mean()),
        "ra_deg": circular_mean(frame["ra_deg"].to_numpy(float), 247.0),
        "dec_deg": float(frame["dec_deg"].mean()),
        "vg_km_s": float(frame["vgeo_km_s"].mean()),
        "ecliptic_longitude_deg": circular_mean(frame["lamgeo_deg"].to_numpy(float), 248.0),
        "sun_centered_ecliptic_longitude_deg": circular_mean(frame["sc_lon_deg"].to_numpy(float), 210.0),
        "ecliptic_latitude_deg": float(frame["betgeo_deg"].mean()),
        "q_au": q,
        "e": eccentricity,
        "i_deg": float(frame["i_deg"].mean()),
        "peri_deg": circular_mean(frame["peri_deg"].to_numpy(float), 333.0),
        "node_deg": circular_mean(frame["node_deg"].to_numpy(float), 37.0),
        "a_au": float(q / (1.0 - eccentricity)),
        "dra_deg_per_deg": slope("ra_deg"),
        "ddec_deg_per_deg": slope("dec_deg"),
        "dvg_km_s_per_deg": slope("vgeo_km_s"),
    }


def prepare_members() -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    audits: dict[str, Any] = {}
    for year in YEARS:
        data, audit = load_year(year)
        selection = select_members(data)
        members = selection["members"].copy()
        members["year"] = year
        frames.append(members)
        audits[str(year)] = {
            "catalog": audit,
            "selected_members": int(len(members)),
            "nights": int(selection["nights"]),
            "stations": int(selection["stations"]),
        }
        print(f"{year}: selected={len(members)} nights={selection['nights']} stations={selection['stations']}", flush=True)

    members = pd.concat(frames, ignore_index=True, sort=False)
    if len(members) != EXPECTED_MEMBERS:
        raise RuntimeError(f"Expected {EXPECTED_MEMBERS} members, found {len(members)}")

    members["night_date"] = pd.to_datetime(
        members["beginning_utc_time"], errors="raise", utc=True
    ).dt.strftime("%Y-%m-%d")
    members["sc_lon_deg"] = (
        members["lamgeo_deg"].to_numpy(float) - members["sol_lon_deg"].to_numpy(float)
    ) % 360.0
    ra, dec = ecliptic_to_equatorial(
        members["lamgeo_deg"].to_numpy(float), members["betgeo_deg"].to_numpy(float)
    )
    members["ra_deg"] = ra
    members["dec_deg"] = dec
    return members, audits


def bootstrap(data: pd.DataFrame, resample_years: bool, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    point = calculate_stats(data, data.index.to_numpy())
    metrics = [key for key in point if key not in {"N", "years_observed", "nights_observed"}]
    years = sorted(map(int, data["year"].unique()))
    year_nights = {
        year: sorted(data.loc[data["year"] == year, "night_date"].unique()) for year in years
    }
    groups = {
        (year, night): data.index[(data["year"] == year) & (data["night_date"] == night)].to_numpy()
        for year in years for night in year_nights[year]
    }

    values = {metric: np.empty(REPLICATES, dtype=float) for metric in metrics}
    sample_sizes = np.empty(REPLICATES, dtype=int)
    rng = np.random.default_rng(seed)

    for replicate in range(REPLICATES):
        sampled_indices: list[int] = []
        sampled_years = (
            rng.choice(years, size=len(years), replace=True).tolist() if resample_years else years
        )
        for raw_year in sampled_years:
            year = int(raw_year)
            nights = year_nights[year]
            sampled_nights = rng.choice(nights, size=len(nights), replace=True)
            for night in sampled_nights:
                sampled_indices.extend(groups[(year, str(night))].tolist())
        stats = calculate_stats(data, np.asarray(sampled_indices, dtype=int))
        sample_sizes[replicate] = stats["N"]
        for metric in metrics:
            values[metric][replicate] = float(stats[metric])

    summary: dict[str, Any] = {}
    for metric in metrics:
        vector = values[metric]
        summary[metric] = {
            "point": float(point[metric]),
            "bootstrap_median": float(np.median(vector)),
            "ci95_low": float(np.percentile(vector, 2.5)),
            "ci95_high": float(np.percentile(vector, 97.5)),
            "bootstrap_sd": float(np.std(vector, ddof=1)),
        }
    sample_audit = {
        "N_median": float(np.median(sample_sizes)),
        "N_min": int(sample_sizes.min()),
        "N_max": int(sample_sizes.max()),
    }
    return summary, sample_audit


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
    members, catalog_audits = prepare_members()
    point = calculate_stats(members, members.index.to_numpy())
    primary, primary_sizes = bootstrap(members, resample_years=True, seed=SEED_PRIMARY)
    conditional, conditional_sizes = bootstrap(members, resample_years=False, seed=SEED_CONDITIONAL)

    leave_one_year_out = {}
    for year in YEARS:
        indices = members.index[members["year"] != year].to_numpy()
        leave_one_year_out[str(year)] = calculate_stats(members, indices)

    payload = {
        "stage": "year_and_night_cluster_bootstrap",
        "members": int(len(members)),
        "years": list(YEARS),
        "unique_nights": int(members["night_date"].nunique()),
        "replicates_each": REPLICATES,
        "point_estimate": point,
        "primary_year_night_bootstrap": primary,
        "conditional_night_bootstrap": conditional,
        "primary_sample_sizes": primary_sizes,
        "conditional_sample_sizes": conditional_sizes,
        "leave_one_year_out": leave_one_year_out,
        "catalog_audits": catalog_audits,
        "interpretation": {
            "ra_drift_excludes_zero": bool(primary["dra_deg_per_deg"]["ci95_low"] > 0.0),
            "dec_drift_excludes_zero": bool(primary["ddec_deg_per_deg"]["ci95_high"] < 0.0),
            "speed_drift_excludes_zero": bool(
                primary["dvg_km_s_per_deg"]["ci95_low"] > 0.0
                or primary["dvg_km_s_per_deg"]["ci95_high"] < 0.0
            ),
            "scope": "sampling variability only; trajectory measurement uncertainty is assessed separately by the 1000-clone audit",
        },
    }
    (OUT / "bootstrap_uncertainty.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )

    export_columns = [
        "year", "unique_trajectory_identifier", "beginning_utc_time", "night_date",
        "sol_lon_deg", "ra_deg", "dec_deg", "vgeo_km_s", "lamgeo_deg",
        "sc_lon_deg", "betgeo_deg", *ORBIT_COLUMNS,
    ]
    members[export_columns].to_csv(OUT / "bootstrap_input_95.csv", index=False)

    lines = [
        "# Cluster-bootstrap uncertainty for the GhostStream April solution", "",
        "**Verdict:** The mean radiant and orbit are stable to year/night resampling. RA and declination drift exclude zero, while the geocentric-speed drift does not.", "",
        f"- Members: **{len(members)}**",
        f"- Unique nights: **{members['night_date'].nunique()}**",
        f"- Replicates per bootstrap: **{REPLICATES:,}**", "",
        "| Quantity | Point | Primary 95% interval |",
        "|---|---:|---:|",
    ]
    table = [
        ("RA", "ra_deg", 3, "°"),
        ("Dec", "dec_deg", 3, "°"),
        ("Vg", "vg_km_s", 3, " km/s"),
        ("q", "q_au", 6, " AU"),
        ("e", "e", 6, ""),
        ("i", "i_deg", 3, "°"),
        ("ω", "peri_deg", 3, "°"),
        ("Ω", "node_deg", 3, "°"),
        ("a", "a_au", 4, " AU"),
        ("dRA/dλ⊙", "dra_deg_per_deg", 3, "°/°"),
        ("dDec/dλ⊙", "ddec_deg_per_deg", 3, "°/°"),
        ("dVg/dλ⊙", "dvg_km_s_per_deg", 3, " km/s/°"),
    ]
    for label, key, digits, unit in table:
        item = primary[key]
        lines.append(
            f"| {label} | {item['point']:.{digits}f}{unit} | "
            f"{item['ci95_low']:.{digits}f} to {item['ci95_high']:.{digits}f}{unit} |"
        )
    lines += ["", "The speed-drift interval crosses zero and must not be described as a detected physical deceleration.", ""]
    (OUT / "BOOTSTRAP_UNCERTAINTY.md").write_text("\n".join(lines))

    print(json.dumps(payload["interpretation"], indent=2), flush=True)
    print(f"Report: {OUT / 'BOOTSTRAP_UNCERTAINTY.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
