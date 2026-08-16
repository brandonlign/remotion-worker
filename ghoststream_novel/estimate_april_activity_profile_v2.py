#!/usr/bin/env python3
"""Exposure-normalized March--May activity profile for the April stream.

This corrects the first profile run, which loaded April only and therefore had
zero exposure after solar longitude ~41 deg. The candidate definition, 0.5-deg
binning, expanded antihelion background, and baseline region remain frozen.
Bins with inadequate exposure are reported as unavailable, never assigned a
posterior rate.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import beta, fisher_exact
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader

from validate_april_candidate import (
    BASE_COLUMNS, CENTER, ORBIT_COLUMNS, SIGMA_COLUMNS, circ_diff,
    deduplicate, shower_label,
)
from validate_april_source_null import features

OUT = Path("ghoststream_april_activity_v2")
YEARS = (2022, 2023, 2024, 2025, 2026)
MONTHS = (3, 4, 5)
BIN_WIDTH = 0.5
HALF_RANGE = 18.0
TEST_HALF_WIDTH = 4.0
BASELINE_INNER_EXCLUSION = 6.0
POSTERIOR_THRESHOLD = 0.95
MIN_BACKGROUND_PER_BIN = 40


def load_month(year: int, month: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    stamp = f"{year}-{month:02d}"
    print(f"Downloading {stamp}...", flush=True)
    frame = reader.read_data(dd.get_monthly_file_content_by_date(stamp), output_camel_case=True).reset_index(drop=False)
    missing = [column for column in BASE_COLUMNS if column not in frame.columns]
    if missing:
        raise RuntimeError(f"{stamp} missing columns: {missing}")
    data = frame[BASE_COLUMNS].copy()
    data["label"] = data["iau_code"].map(shower_label)
    for column in ["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s", *ORBIT_COLUMNS,
                   *SIGMA_COLUMNS, "medianfiterr_arcsec", "num_stat"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    valid = np.isfinite(data[["sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]]).all(axis=1)
    valid &= data["sol_lon_deg"].between(0, 360) & data["lamgeo_deg"].between(0, 360)
    valid &= data["betgeo_deg"].between(-90, 90) & data["vgeo_km_s"].between(5, 75)
    valid &= data["num_stat"].fillna(0) >= 2
    valid &= data["medianfiterr_arcsec"].fillna(9999) <= 180
    quality = data.loc[valid & (data["label"] == "SPORADIC")].reset_index(drop=True)
    deduped, audit = deduplicate(quality)
    audit.update({
        "stamp": stamp,
        "raw_month_rows": int(len(frame)),
        "quality_sporadic_rows": int(len(quality)),
    })
    return deduped, audit


def load_season(year: int) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    frames = []
    audits = []
    for month in MONTHS:
        frame, audit = load_month(year, month)
        frames.append(frame)
        audits.append(audit)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    deduped, cross_month_audit = deduplicate(combined)
    cross_month_audit["stamp"] = f"{year}-03_to_05"
    audits.append(cross_month_audit)
    delta = circ_diff(deduped["sol_lon_deg"].to_numpy(float), CENTER[3])
    keep = np.abs(delta) <= HALF_RANGE + BIN_WIDTH
    return deduped.loc[keep].reset_index(drop=True), audits


def posterior(stream: int, background: int) -> dict[str, float | None]:
    if background < MIN_BACKGROUND_PER_BIN:
        return {
            "fraction_mean": None,
            "rate_per_1000_background": None,
            "rate_low": None,
            "rate_high": None,
        }
    a = stream + 0.5
    b = background + 0.5
    p_mean = a / (a + b)
    p_lo, p_hi = beta.ppf([0.025, 0.975], a, b)

    def odds_per_thousand(p: float) -> float:
        return float(1000.0 * p / max(1.0 - p, 1e-12))

    return {
        "fraction_mean": float(p_mean),
        "rate_per_1000_background": odds_per_thousand(float(p_mean)),
        "rate_low": odds_per_thousand(float(p_lo)),
        "rate_high": odds_per_thousand(float(p_hi)),
    }


def profile_for_frames(frames: dict[int, pd.DataFrame], included_years: tuple[int, ...]) -> tuple[pd.DataFrame, dict[str, Any]]:
    edges = np.arange(-HALF_RANGE, HALF_RANGE + BIN_WIDTH + 1e-9, BIN_WIDTH)
    prepared: dict[int, tuple[dict[str, np.ndarray], np.ndarray]] = {}
    yearly: dict[str, Any] = {}

    for year in included_years:
        data = frames[year]
        f = features(data)
        delta = circ_diff(f["sol"], CENTER[3])
        prepared[year] = (f, delta)
        core = f["core"] & f["antihelion"]
        background = f["antihelion"] & ~f["core"]
        inside = np.abs(delta) <= TEST_HALF_WIDTH
        baseline = (np.abs(delta) > BASELINE_INNER_EXCLUSION) & (np.abs(delta) <= HALF_RANGE)
        table = [
            [int(np.sum(core & inside)), int(np.sum(background & inside))],
            [int(np.sum(core & baseline)), int(np.sum(background & baseline))],
        ]
        odds, p = fisher_exact(table, alternative="greater")
        yearly[str(year)] = {
            "table": table,
            "odds_ratio": float(odds),
            "p": float(p),
            "stream_inside": table[0][0],
            "background_inside": table[0][1],
            "stream_baseline": table[1][0],
            "background_baseline": table[1][1],
        }

    rows = []
    for left, right in zip(edges[:-1], edges[1:]):
        stream_total = 0
        background_total = 0
        by_year = {}
        for year in included_years:
            f, delta = prepared[year]
            in_bin = (delta >= left) & (delta < right)
            stream = int(np.sum(in_bin & f["antihelion"] & f["core"]))
            background = int(np.sum(in_bin & f["antihelion"] & ~f["core"]))
            stream_total += stream
            background_total += background
            by_year[str(year)] = {"stream": stream, "background": background}
        post = posterior(stream_total, background_total)
        rows.append({
            "delta_left_deg": float(left),
            "delta_right_deg": float(right),
            "delta_center_deg": float((left + right) / 2.0),
            "solar_longitude_center_deg": float((CENTER[3] + (left + right) / 2.0) % 360.0),
            "stream_count": stream_total,
            "background_count": background_total,
            "exposure_sufficient": bool(background_total >= MIN_BACKGROUND_PER_BIN),
            **post,
            "by_year": json.dumps(by_year, sort_keys=True),
        })

    profile = pd.DataFrame(rows)
    valid = profile["exposure_sufficient"].to_numpy(bool)
    centers = profile["delta_center_deg"].to_numpy(float)
    baseline_bins = valid & (np.abs(centers) > BASELINE_INNER_EXCLUSION)
    baseline_stream = int(profile.loc[baseline_bins, "stream_count"].sum())
    baseline_background = int(profile.loc[baseline_bins, "background_count"].sum())
    baseline_p = (baseline_stream + 0.5) / (baseline_stream + baseline_background + 1.0)
    baseline_rate = float(1000.0 * baseline_p / (1.0 - baseline_p))

    probabilities = np.full(len(profile), np.nan)
    rates = profile["rate_per_1000_background"].to_numpy(float)
    for index, row in enumerate(profile.itertuples(index=False)):
        if not bool(row.exposure_sufficient):
            continue
        probabilities[index] = float(beta.sf(
            baseline_p, int(row.stream_count) + 0.5, int(row.background_count) + 0.5
        ))
    profile["posterior_probability_above_baseline"] = probabilities
    excess = np.where(valid, np.maximum(rates - baseline_rate, 0.0), np.nan)
    profile["excess_rate_per_1000_background"] = excess

    valid_indices = np.where(valid & np.isfinite(rates))[0]
    if len(valid_indices) == 0:
        raise RuntimeError("No bins met the minimum exposure requirement")
    peak_index = int(valid_indices[np.nanargmax(rates[valid_indices])])
    weights = np.nan_to_num(excess, nan=0.0)
    weighted_center = float(np.average(centers, weights=weights)) if weights.sum() > 0 else float("nan")

    half_max = float(excess[peak_index] / 2.0)
    left_index = peak_index
    right_index = peak_index
    while left_index > 0 and valid[left_index - 1] and excess[left_index - 1] >= half_max:
        left_index -= 1
    while right_index < len(profile) - 1 and valid[right_index + 1] and excess[right_index + 1] >= half_max:
        right_index += 1
    fwhm_left = float(profile.loc[left_index, "delta_left_deg"])
    fwhm_right = float(profile.loc[right_index, "delta_right_deg"])

    supported = valid & (probabilities >= POSTERIOR_THRESHOLD)
    support_left = support_right = None
    if supported[peak_index]:
        li = ri = peak_index
        while li > 0 and supported[li - 1]:
            li -= 1
        while ri < len(profile) - 1 and supported[ri + 1]:
            ri += 1
        support_left = float(profile.loc[li, "delta_left_deg"])
        support_right = float(profile.loc[ri, "delta_right_deg"])

    aggregate_table = np.sum(
        [np.asarray(yearly[str(year)]["table"], dtype=int) for year in included_years], axis=0
    )
    aggregate_odds, aggregate_p = fisher_exact(aggregate_table.tolist(), alternative="greater")
    peak = profile.loc[peak_index]

    summary = {
        "years": list(included_years),
        "months_loaded": list(MONTHS),
        "exposure_proxy": "simultaneous expanded-antihelion non-core meteor count",
        "minimum_background_per_bin": MIN_BACKGROUND_PER_BIN,
        "bin_width_deg": BIN_WIDTH,
        "center_solar_longitude_deg": CENTER[3],
        "baseline_region_abs_delta_deg": [BASELINE_INNER_EXCLUSION, HALF_RANGE],
        "baseline_stream": baseline_stream,
        "baseline_background": baseline_background,
        "baseline_rate_per_1000_background": baseline_rate,
        "peak_delta_deg": float(peak["delta_center_deg"]),
        "peak_solar_longitude_deg": float(peak["solar_longitude_center_deg"]),
        "peak_stream_count": int(peak["stream_count"]),
        "peak_background_count": int(peak["background_count"]),
        "peak_rate_per_1000_background": float(peak["rate_per_1000_background"]),
        "peak_95pct_interval": [float(peak["rate_low"]), float(peak["rate_high"])],
        "excess_weighted_center_delta_deg": weighted_center,
        "excess_weighted_center_solar_longitude_deg": float((CENTER[3] + weighted_center) % 360.0),
        "fwhm_delta_interval_deg": [fwhm_left, fwhm_right],
        "fwhm_solar_longitude_interval_deg": [
            float((CENTER[3] + fwhm_left) % 360.0),
            float((CENTER[3] + fwhm_right) % 360.0),
        ],
        "fwhm_width_deg": float(fwhm_right - fwhm_left),
        "posterior_supported_interval_delta_deg": [support_left, support_right],
        "posterior_threshold": POSTERIOR_THRESHOLD,
        "aggregate_inside_vs_baseline_table": aggregate_table.tolist(),
        "aggregate_odds_ratio": float(aggregate_odds),
        "aggregate_p": float(aggregate_p),
        "yearly": yearly,
    }
    return profile, summary


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def main() -> int:
    OUT.mkdir(exist_ok=True)
    frames: dict[int, pd.DataFrame] = {}
    audits: dict[str, Any] = {}
    for year in YEARS:
        data, audit = load_season(year)
        frames[year] = data
        audits[str(year)] = audit
        delta = circ_diff(data["sol_lon_deg"].to_numpy(float), CENTER[3])
        print(
            f"{year}: {len(data):,} quality sporadics in profile range; "
            f"delta=[{delta.min():.2f},{delta.max():.2f}]", flush=True
        )

    profile, summary = profile_for_frames(frames, YEARS)
    loo = {}
    for omitted in YEARS:
        years = tuple(year for year in YEARS if year != omitted)
        _, item = profile_for_frames(frames, years)
        loo[str(omitted)] = {
            "included_years": list(years),
            "peak_delta_deg": item["peak_delta_deg"],
            "weighted_center_delta_deg": item["excess_weighted_center_delta_deg"],
            "fwhm_width_deg": item["fwhm_width_deg"],
            "aggregate_p": item["aggregate_p"],
        }
    summary["leave_one_year_out"] = loo
    summary["catalog_audits"] = audits

    profile.to_csv(OUT / "exposure_normalized_activity_profile.csv", index=False)
    (OUT / "activity_profile.json").write_text(json.dumps(jsonable(summary), indent=2) + "\n")

    lines = [
        "# Corrected exposure-normalized activity profile", "",
        "March, April, and May catalogues were loaded for every year, removing the April-month boundary artifact in the first run. Bins with fewer than 40 simultaneous non-core antihelion meteors are unavailable rather than assigned a rate.", "",
        "This is a relative source-normalized activity profile, not an absolute flux or ZHR estimate.", "",
        f"- Years: **{', '.join(map(str, YEARS))}**",
        f"- Bin width: **{BIN_WIDTH:.2f}°**",
        f"- Baseline rate: **{summary['baseline_rate_per_1000_background']:.3f} per 1000 antihelion-background meteors**",
        f"- Peak solar longitude: **{summary['peak_solar_longitude_deg']:.3f}°**",
        f"- Peak counts: **{summary['peak_stream_count']} stream / {summary['peak_background_count']} background**",
        f"- Peak relative rate: **{summary['peak_rate_per_1000_background']:.2f} per 1000 background**",
        f"- Background-subtracted weighted center: **{summary['excess_weighted_center_solar_longitude_deg']:.3f}°**",
        f"- FWHM interval: **{summary['fwhm_solar_longitude_interval_deg']}°**",
        f"- FWHM width: **{summary['fwhm_width_deg']:.2f}°**",
        f"- Aggregate inside-versus-baseline p: **{summary['aggregate_p']:.6g}**", "",
        "## Year-level tests", "",
        "| Year | Stream inside | Background inside | Stream baseline | Background baseline | p |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = summary["yearly"][str(year)]
        lines.append(
            f"| {year} | {item['stream_inside']} | {item['background_inside']} | "
            f"{item['stream_baseline']} | {item['background_baseline']} | {item['p']:.5g} |"
        )
    lines += ["", "## Leave-one-year-out stability", "",
              "| Omitted | Peak delta | Weighted center delta | FWHM | Aggregate p |",
              "|---:|---:|---:|---:|---:|"]
    for omitted in YEARS:
        item = loo[str(omitted)]
        lines.append(
            f"| {omitted} | {item['peak_delta_deg']:.2f}° | {item['weighted_center_delta_deg']:.2f}° | "
            f"{item['fwhm_width_deg']:.2f}° | {item['aggregate_p']:.5g} |"
        )
    lines += ["", "The profile remains conditional on catalogue-level detection and the expanded antihelion denominator. Weather, limiting magnitude, radiant elevation, and collecting area are not modeled explicitly.", ""]
    (OUT / "ACTIVITY_PROFILE.md").write_text("\n".join(lines))

    print(json.dumps({
        "peak_solar_longitude_deg": summary["peak_solar_longitude_deg"],
        "peak_counts": [summary["peak_stream_count"], summary["peak_background_count"]],
        "weighted_center_solar_longitude_deg": summary["excess_weighted_center_solar_longitude_deg"],
        "fwhm_solar_longitude_interval_deg": summary["fwhm_solar_longitude_interval_deg"],
        "fwhm_width_deg": summary["fwhm_width_deg"],
        "supported_interval_delta_deg": summary["posterior_supported_interval_delta_deg"],
        "aggregate_p": summary["aggregate_p"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
