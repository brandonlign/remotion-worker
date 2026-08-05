#!/usr/bin/env python3
"""Estimate an exposure-normalized activity profile for the April candidate.

Absolute GMN collecting area is not available in the public trajectory tables.
We therefore use the simultaneous expanded antihelion population as an internal
exposure proxy. In each solar-longitude bin, stream-core counts are normalized
by non-core antihelion counts. The candidate template and background definition
are unchanged from the source-preserving null audit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import beta, fisher_exact

from validate_april_candidate import CENTER, load_year, circ_diff
from validate_april_source_null import features

OUT = Path("ghoststream_april_activity")
YEARS = (2022, 2023, 2024, 2025, 2026)
BIN_WIDTH = 0.5
HALF_RANGE = 18.0
CORE_RADIUS2 = 9.0
TEST_HALF_WIDTH = 4.0
BASELINE_INNER_EXCLUSION = 6.0
POSTERIOR_THRESHOLD = 0.95


def interval_from_posterior(stream: int, background: int) -> dict[str, float]:
    # Jeffreys posterior for stream fraction among stream+background events.
    a = stream + 0.5
    b = background + 0.5
    p_mean = a / (a + b)
    p_lo, p_hi = beta.ppf([0.025, 0.975], a, b)

    def odds_per_thousand(p: float) -> float:
        return float(1000.0 * p / max(1.0 - p, 1e-12))

    return {
        "fraction_mean": float(p_mean),
        "rate_per_1000_background": odds_per_thousand(p_mean),
        "rate_low": odds_per_thousand(float(p_lo)),
        "rate_high": odds_per_thousand(float(p_hi)),
    }


def profile_for_frames(frames: dict[int, pd.DataFrame], included_years: tuple[int, ...]) -> tuple[pd.DataFrame, dict[str, Any]]:
    edges = np.arange(-HALF_RANGE, HALF_RANGE + BIN_WIDTH + 1e-9, BIN_WIDTH)
    rows: list[dict[str, Any]] = []
    yearly_tables: dict[str, Any] = {}

    prepared: dict[int, tuple[pd.DataFrame, dict[str, np.ndarray], np.ndarray]] = {}
    for year in included_years:
        data = frames[year]
        f = features(data)
        delta = circ_diff(f["sol"], CENTER[3])
        prepared[year] = (data, f, delta)

        inside = np.abs(delta) <= TEST_HALF_WIDTH
        outside = (np.abs(delta) > BASELINE_INNER_EXCLUSION) & (np.abs(delta) <= HALF_RANGE)
        core = f["core"] & f["antihelion"]
        bg = f["antihelion"] & ~f["core"]
        table = [
            [int(np.sum(core & inside)), int(np.sum(bg & inside))],
            [int(np.sum(core & outside)), int(np.sum(bg & outside))],
        ]
        odds, p = fisher_exact(table, alternative="greater")
        yearly_tables[str(year)] = {
            "table": table,
            "odds_ratio": float(odds),
            "p": float(p),
            "stream_inside": table[0][0],
            "background_inside": table[0][1],
            "stream_outside": table[1][0],
            "background_outside": table[1][1],
        }

    for left, right in zip(edges[:-1], edges[1:]):
        stream_total = background_total = 0
        by_year: dict[str, dict[str, int]] = {}
        for year in included_years:
            _, f, delta = prepared[year]
            in_bin = (delta >= left) & (delta < right)
            stream = int(np.sum(in_bin & f["antihelion"] & f["core"]))
            background = int(np.sum(in_bin & f["antihelion"] & ~f["core"]))
            stream_total += stream
            background_total += background
            by_year[str(year)] = {"stream": stream, "background": background}
        posterior = interval_from_posterior(stream_total, background_total)
        rows.append({
            "delta_left_deg": float(left),
            "delta_right_deg": float(right),
            "delta_center_deg": float((left + right) / 2.0),
            "solar_longitude_center_deg": float((CENTER[3] + (left + right) / 2.0) % 360.0),
            "stream_count": stream_total,
            "background_count": background_total,
            **posterior,
            "by_year": json.dumps(by_year, sort_keys=True),
        })

    profile = pd.DataFrame(rows)
    outside_bins = np.abs(profile["delta_center_deg"].to_numpy(float)) > BASELINE_INNER_EXCLUSION
    baseline_stream = int(profile.loc[outside_bins, "stream_count"].sum())
    baseline_background = int(profile.loc[outside_bins, "background_count"].sum())
    baseline_p = (baseline_stream + 0.5) / (baseline_stream + baseline_background + 1.0)
    profile["posterior_probability_above_baseline"] = [
        float(beta.sf(baseline_p, int(row.stream_count) + 0.5, int(row.background_count) + 0.5))
        for row in profile.itertuples(index=False)
    ]
    baseline_rate = float(1000.0 * baseline_p / (1.0 - baseline_p))
    profile["excess_rate_per_1000_background"] = np.maximum(
        profile["rate_per_1000_background"].to_numpy(float) - baseline_rate, 0.0
    )

    peak_index = int(profile["rate_per_1000_background"].idxmax())
    peak = profile.loc[peak_index]
    weights = profile["excess_rate_per_1000_background"].to_numpy(float)
    centers = profile["delta_center_deg"].to_numpy(float)
    weighted_center = float(np.average(centers, weights=weights)) if weights.sum() > 0 else float("nan")

    # FWHM of the background-subtracted, exposure-normalized profile, using
    # contiguous bins around the global peak.
    excess = weights
    half_max = float(excess[peak_index] / 2.0)
    left_index = peak_index
    right_index = peak_index
    while left_index > 0 and excess[left_index - 1] >= half_max:
        left_index -= 1
    while right_index < len(excess) - 1 and excess[right_index + 1] >= half_max:
        right_index += 1
    fwhm_left = float(profile.loc[left_index, "delta_left_deg"])
    fwhm_right = float(profile.loc[right_index, "delta_right_deg"])

    supported = profile["posterior_probability_above_baseline"].to_numpy(float) >= POSTERIOR_THRESHOLD
    support_indices = np.where(supported)[0]
    # Report the supported component containing the peak; isolated side bins do
    # not expand the activity interval.
    support_left = support_right = None
    if supported[peak_index]:
        li = ri = peak_index
        while li > 0 and supported[li - 1]:
            li -= 1
        while ri < len(supported) - 1 and supported[ri + 1]:
            ri += 1
        support_left = float(profile.loc[li, "delta_left_deg"])
        support_right = float(profile.loc[ri, "delta_right_deg"])

    aggregate_table = np.sum(
        [np.asarray(yearly_tables[str(year)]["table"], dtype=int) for year in included_years], axis=0
    )
    aggregate_odds, aggregate_p = fisher_exact(aggregate_table.tolist(), alternative="greater")

    summary = {
        "years": list(included_years),
        "exposure_proxy": "simultaneous expanded-antihelion non-core meteor count",
        "bin_width_deg": BIN_WIDTH,
        "center_solar_longitude_deg": CENTER[3],
        "baseline_region_abs_delta_deg": [BASELINE_INNER_EXCLUSION, HALF_RANGE],
        "baseline_stream": baseline_stream,
        "baseline_background": baseline_background,
        "baseline_rate_per_1000_background": baseline_rate,
        "peak_delta_deg": float(peak["delta_center_deg"]),
        "peak_solar_longitude_deg": float(peak["solar_longitude_center_deg"]),
        "peak_rate_per_1000_background": float(peak["rate_per_1000_background"]),
        "peak_95pct_interval": [float(peak["rate_low"]), float(peak["rate_high"])],
        "excess_weighted_center_delta_deg": weighted_center,
        "excess_weighted_center_solar_longitude_deg": float((CENTER[3] + weighted_center) % 360.0),
        "fwhm_delta_interval_deg": [fwhm_left, fwhm_right],
        "fwhm_width_deg": float(fwhm_right - fwhm_left),
        "posterior_supported_interval_delta_deg": [support_left, support_right],
        "posterior_threshold": POSTERIOR_THRESHOLD,
        "aggregate_inside_vs_baseline_table": aggregate_table.tolist(),
        "aggregate_odds_ratio": float(aggregate_odds),
        "aggregate_p": float(aggregate_p),
        "yearly": yearly_tables,
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
        data, audit = load_year(year)
        frames[year] = data
        audits[str(year)] = audit
        print(f"{year}: {len(data):,} quality sporadics", flush=True)

    profile, summary = profile_for_frames(frames, YEARS)
    loo: dict[str, Any] = {}
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
        "# Exposure-normalized activity profile", "",
        "Absolute collecting-area exposure is unavailable in the public trajectory catalogues. This analysis therefore normalizes frozen stream-core counts by simultaneous non-core counts inside the same expanded antihelion source. It is a relative activity profile, not an absolute flux or ZHR estimate.", "",
        f"- Years: **{', '.join(map(str, YEARS))}**",
        f"- Bin width: **{BIN_WIDTH:.2f}° solar longitude**",
        f"- Baseline rate: **{summary['baseline_rate_per_1000_background']:.3f} stream meteors per 1000 antihelion-background meteors**",
        f"- Peak solar longitude: **{summary['peak_solar_longitude_deg']:.3f}°**",
        f"- Peak relative rate: **{summary['peak_rate_per_1000_background']:.2f} per 1000 background**",
        f"- Background-subtracted weighted center: **{summary['excess_weighted_center_solar_longitude_deg']:.3f}°**",
        f"- Profile FWHM: **{summary['fwhm_width_deg']:.2f}°** (delta {summary['fwhm_delta_interval_deg']})",
        f"- Aggregate inside-versus-baseline Fisher p: **{summary['aggregate_p']:.6g}**", "",
        "## Year-level inside-versus-baseline tests", "",
        "| Year | Stream inside | Background inside | Stream baseline | Background baseline | p |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = summary["yearly"][str(year)]
        lines.append(
            f"| {year} | {item['stream_inside']} | {item['background_inside']} | "
            f"{item['stream_outside']} | {item['background_outside']} | {item['p']:.5g} |"
        )
    lines += ["", "## Leave-one-year-out stability", "",
              "| Omitted year | Peak delta | Weighted-center delta | FWHM | Aggregate p |",
              "|---:|---:|---:|---:|---:|"]
    for omitted in YEARS:
        item = loo[str(omitted)]
        lines.append(
            f"| {omitted} | {item['peak_delta_deg']:.2f}° | {item['weighted_center_delta_deg']:.2f}° | "
            f"{item['fwhm_width_deg']:.2f}° | {item['aggregate_p']:.5g} |"
        )
    lines += ["", "The profile should be used to replace the raw selection-window bounds in the manuscript. It still does not constitute an absolute flux measurement because station weather, limiting magnitude, and effective collecting area are not explicitly modeled.", ""]
    (OUT / "ACTIVITY_PROFILE.md").write_text("\n".join(lines))

    print(json.dumps({
        "peak_solar_longitude_deg": summary["peak_solar_longitude_deg"],
        "weighted_center_solar_longitude_deg": summary["excess_weighted_center_solar_longitude_deg"],
        "fwhm_width_deg": summary["fwhm_width_deg"],
        "supported_interval": summary["posterior_supported_interval_delta_deg"],
        "aggregate_p": summary["aggregate_p"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
