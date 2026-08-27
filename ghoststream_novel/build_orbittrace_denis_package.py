#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from gmn_python_api import data_directory as dd
from gmn_python_api import meteor_trajectory_reader as reader

OUT = Path("orbittrace_denis_package")
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "gmn_official_unmarked").mkdir(exist_ok=True)

CANONICAL_URL = "https://raw.githubusercontent.com/brandonlign/orbittrace/main/data/derived/canonical_95.csv"
YEARS = [2022, 2023, 2024, 2025, 2026]
EXPECTED_COUNTS = {2022: 10, 2023: 8, 2024: 14, 2025: 34, 2026: 29}

# Current frozen/reference solution verified from orbittrace-raw/candidate/candidate_solution.json.
REF_SOL = 36.901963
REF_SCE_SIGNED = -149.3763247
REF_SCE_WRAPPED = REF_SCE_SIGNED % 360.0
REF_BETA = 7.3230377
REF_VG = 37.641692
DRIFT_SCE = -0.1029483
DRIFT_BETA = -0.0230546
SIGMA_SCE = 0.7369
SIGMA_BETA = 0.6250
SIGMA_VG = 1.1596

CORE_PREFERRED = [
    "unique_trajectory_identifier", "beginning_utc_time", "iau_no", "iau_code",
    "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s",
    "a_au", "e", "q_au", "i_deg", "peri_deg", "node_deg", "pi_deg",
    "q_aphelion_au", "Q_au", "tisserand_j", "TisserandJ",
    "qc_deg", "medianfiterr_arcsec", "num_stat", "participating_stations",
]


def event_key(value) -> str:
    digits = re.sub(r"\D", "", str(value))
    return digits[:14]


def circ_diff(a, b):
    return (np.asarray(a, dtype=float) - np.asarray(b, dtype=float) + 180.0) % 360.0 - 180.0


def circular_mean_deg(values):
    a = np.deg2rad(np.asarray(values, dtype=float))
    return float(np.rad2deg(np.arctan2(np.nanmean(np.sin(a)), np.nanmean(np.cos(a)))) % 360.0)


def get_col(frame, *names):
    for name in names:
        if name in frame.columns:
            return name
    return None


def download(url: str, path: Path):
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    path.write_bytes(r.content)


def mark_candidate_plot(ax, x, y, label=True):
    ax.scatter([x], [y], s=180, facecolors="none", edgecolors="red", linewidths=2.4, zorder=20)
    ax.scatter([x], [y], s=18, c="red", zorder=21)
    if label:
        ax.annotate(
            "OrbitTrace candidate",
            xy=(x, y), xytext=(x + 20, y + 13),
            color="red", fontsize=10, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="red", lw=1.7),
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="red", alpha=0.88),
            zorder=22,
        )


def plot_month(year, frame, members):
    x = (pd.to_numeric(frame["lamgeo_deg"], errors="coerce") - pd.to_numeric(frame["sol_lon_deg"], errors="coerce")) % 360.0
    y = pd.to_numeric(frame["betgeo_deg"], errors="coerce")
    v = pd.to_numeric(frame["vgeo_km_s"], errors="coerce")
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(v) & (y >= -90) & (y <= 90) & (v >= 5) & (v <= 75)
    x, y, v = np.asarray(x[ok]), np.asarray(y[ok]), np.asarray(v[ok])

    mx = (pd.to_numeric(members["lamgeo_deg"], errors="coerce") - pd.to_numeric(members["sol_lon_deg"], errors="coerce")) % 360.0
    my = pd.to_numeric(members["betgeo_deg"], errors="coerce")

    # Full-sky density view in the same SCE coordinate system as the GMN orbital/radiant plots.
    fig, ax = plt.subplots(figsize=(14, 7), dpi=180)
    hb = ax.hexbin(x, y, gridsize=(180, 90), bins="log", mincnt=1, cmap="viridis")
    ax.scatter(mx, my, s=24, facecolors="none", edgecolors="red", linewidths=1.0, zorder=15)
    mark_candidate_plot(ax, REF_SCE_WRAPPED, REF_BETA)
    ax.set(xlim=(0, 360), ylim=(-90, 90), xlabel=r"Sun-centered geocentric ecliptic longitude $\lambda_g-\lambda_\odot$ (deg)", ylabel=r"Geocentric ecliptic latitude $\beta_g$ (deg)")
    ax.set_title(f"GMN April {year} trajectories — OrbitTrace candidate marked ({len(members)} canonical members)")
    ax.grid(alpha=0.18)
    cb = fig.colorbar(hb, ax=ax, pad=0.01)
    cb.set_label("Trajectory density (log-scaled hexbin count)")
    fig.tight_layout()
    fig.savefig(OUT / f"GMN_April_{year}_SCE_density_OrbitTrace_marked.png", bbox_inches="tight")
    plt.close(fig)

    # Full-sky velocity view.
    fig, ax = plt.subplots(figsize=(14, 7), dpi=180)
    hb = ax.hexbin(x, y, C=v, reduce_C_function=np.mean, gridsize=(180, 90), mincnt=1, cmap="turbo", vmin=5, vmax=75)
    ax.scatter(mx, my, s=24, facecolors="none", edgecolors="red", linewidths=1.0, zorder=15)
    mark_candidate_plot(ax, REF_SCE_WRAPPED, REF_BETA)
    ax.set(xlim=(0, 360), ylim=(-90, 90), xlabel=r"Sun-centered geocentric ecliptic longitude $\lambda_g-\lambda_\odot$ (deg)", ylabel=r"Geocentric ecliptic latitude $\beta_g$ (deg)")
    ax.set_title(f"GMN April {year} trajectories — mean geocentric speed, OrbitTrace marked")
    ax.grid(alpha=0.18)
    cb = fig.colorbar(hb, ax=ax, pad=0.01)
    cb.set_label("Mean geocentric speed (km/s)")
    fig.tight_layout()
    fig.savefig(OUT / f"GMN_April_{year}_SCE_vg_OrbitTrace_marked.png", bbox_inches="tight")
    plt.close(fig)

    # Local zoom: easier for Denis to inspect the cluster against the local background.
    local = (np.abs(circ_diff(x, REF_SCE_WRAPPED)) <= 7.0) & (np.abs(y - REF_BETA) <= 7.0)
    fig, ax = plt.subplots(figsize=(9, 7), dpi=200)
    sc = ax.scatter(x[local], y[local], c=v[local], s=8, alpha=0.35, cmap="turbo", vmin=20, vmax=55, linewidths=0)
    ax.scatter(mx, my, s=52, facecolors="none", edgecolors="red", linewidths=1.4, label=f"Canonical members ({len(members)})", zorder=15)
    ax.scatter([REF_SCE_WRAPPED], [REF_BETA], marker="x", s=90, c="red", linewidths=2.0, label="Reference solution", zorder=20)
    ax.set(xlim=(REF_SCE_WRAPPED - 7, REF_SCE_WRAPPED + 7), ylim=(REF_BETA - 7, REF_BETA + 7), xlabel=r"$\lambda_g-\lambda_\odot$ (deg; wrapped 0–360)", ylabel=r"$\beta_g$ (deg)")
    ax.set_title(f"GMN April {year} — local SCE zoom around OrbitTrace")
    ax.grid(alpha=0.22)
    ax.legend(loc="best")
    cb = fig.colorbar(sc, ax=ax, pad=0.01)
    cb.set_label("Geocentric speed (km/s)")
    fig.tight_layout()
    fig.savefig(OUT / f"GMN_April_{year}_SCE_OrbitTrace_zoom.png", bbox_inches="tight")
    plt.close(fig)


def main():
    canonical = pd.read_csv(CANONICAL_URL)
    if len(canonical) != 95:
        raise RuntimeError(f"Expected canonical 95 rows, found {len(canonical)}")
    canonical["year"] = canonical["Tobs"].astype(str).map(lambda s: int(re.sub(r"\D", "", s)[:4]))
    got_counts = canonical["year"].value_counts().sort_index().to_dict()
    if got_counts != EXPECTED_COUNTS:
        raise RuntimeError(f"Canonical year counts changed: {got_counts}")

    selected_rows = []
    matching_audit = []
    all_member_frames = []

    for year in YEARS:
        print(f"Downloading/parsing GMN April {year}...", flush=True)
        raw = reader.read_data(dd.get_monthly_file_content_by_date(f"{year}-04"), output_camel_case=True).reset_index(drop=False)
        required = ["unique_trajectory_identifier", "beginning_utc_time", "sol_lon_deg", "lamgeo_deg", "betgeo_deg", "vgeo_km_s"]
        missing = [c for c in required if c not in raw.columns]
        if missing:
            raise RuntimeError(f"GMN {year}-04 missing parser columns {missing}; available={list(raw.columns)}")

        raw["_event_key"] = raw["unique_trajectory_identifier"].map(event_key)
        # Some historical parser versions expose a slightly different time string; keep a second key from it.
        raw["_utc_key"] = raw["beginning_utc_time"].map(event_key)
        cy = canonical.loc[canonical["year"] == year].copy()
        cy["_event_key"] = cy["Tobs"].map(event_key)
        year_rows = []

        for _, c in cy.iterrows():
            key = c["_event_key"]
            pool = raw.loc[(raw["_event_key"] == key) | (raw["_utc_key"] == key)].copy()
            if pool.empty:
                # Defensive nearest-time fallback, only inside the same April file.
                ct = pd.to_datetime(c["Tobs"], utc=True, errors="coerce")
                rt = pd.to_datetime(raw["beginning_utc_time"], utc=True, errors="coerce")
                if pd.notna(ct):
                    delta = (rt - ct).abs().dt.total_seconds()
                    pool = raw.loc[delta <= 1.0].copy()
            if pool.empty:
                raise RuntimeError(f"No GMN record matched canonical row {c['CurNum']} {c['Tobs']}")

            # Disambiguate duplicate/reprocessed trajectory solutions using the canonical radiant/speed.
            ra_col = get_col(pool, "ra_geo_deg", "rageo_deg")
            de_col = get_col(pool, "dec_geo_deg", "decgeo_deg")
            if ra_col and de_col:
                dra = circ_diff(pd.to_numeric(pool[ra_col], errors="coerce"), float(c["RA"]))
                dde = pd.to_numeric(pool[de_col], errors="coerce") - float(c["DE"])
                dvg = pd.to_numeric(pool["vgeo_km_s"], errors="coerce") - float(c["VG"])
                score = (dra / 0.02) ** 2 + (dde / 0.02) ** 2 + (dvg / 0.03) ** 2
            else:
                dvg = pd.to_numeric(pool["vgeo_km_s"], errors="coerce") - float(c["VG"])
                score = (dvg / 0.03) ** 2
            best_idx = score.astype(float).idxmin()
            best = raw.loc[best_idx].copy()

            # Cross-check canonical SCE values against the full GMN row.
            full_sce = (float(best["lamgeo_deg"]) - float(best["sol_lon_deg"])) % 360.0
            sce_err = abs(float(circ_diff(full_sce, float(c["SCLO"]))))
            beta_err = abs(float(best["betgeo_deg"]) - float(c["LA"]))
            vg_err = abs(float(best["vgeo_km_s"]) - float(c["VG"]))
            if sce_err > 0.02 or beta_err > 0.02 or vg_err > 0.05:
                raise RuntimeError(f"Match audit failed for {c['Tobs']}: sce={sce_err}, beta={beta_err}, vg={vg_err}")

            out = best.drop(labels=["_event_key", "_utc_key"], errors="ignore").to_dict()
            out = {
                "canonical_CurNum": int(c["CurNum"]),
                "canonical_Tobs": str(c["Tobs"]),
                "canonical_SCLO_deg_0_360": float(c["SCLO"]),
                "canonical_beta_deg": float(c["LA"]),
                "canonical_RA_deg": float(c["RA"]),
                "canonical_DEC_deg": float(c["DE"]),
                "canonical_Vg_km_s": float(c["VG"]),
                "computed_SCE_deg_0_360": full_sce,
                "computed_SCE_deg_signed": float(circ_diff(full_sce, 0.0)),
                "gmn_source_month": f"{year}-04",
                **out,
            }
            selected_rows.append(out)
            year_rows.append(out)
            matching_audit.append({
                "CurNum": int(c["CurNum"]), "Tobs": str(c["Tobs"]),
                "trajectory_id": str(best["unique_trajectory_identifier"]),
                "candidate_pool_size": int(len(pool)),
                "SCE_abs_error_deg": sce_err, "beta_abs_error_deg": beta_err, "Vg_abs_error_km_s": vg_err,
            })

        members = pd.DataFrame(year_rows)
        if len(members) != EXPECTED_COUNTS[year]:
            raise RuntimeError(f"{year} recovered {len(members)} rows, expected {EXPECTED_COUNTS[year]}")
        all_member_frames.append(members)
        plot_month(year, raw, members)

        for kind in ["density", "vg"]:
            url = f"https://globalmeteornetwork.org/data/plots/monthly/scecliptic_monthly_{year}04_{kind}.png"
            download(url, OUT / "gmn_official_unmarked" / f"scecliptic_monthly_{year}04_{kind}.png")

    full = pd.DataFrame(selected_rows).sort_values(["canonical_Tobs", "canonical_CurNum"]).reset_index(drop=True)
    if len(full) != 95 or full["unique_trajectory_identifier"].astype(str).nunique() != 95:
        raise RuntimeError("Recovered member table is not 95 unique GMN trajectories")

    full.to_csv(OUT / "OrbitTrace_April_95_GMN_full_entries.csv", index=False)

    core_cols = [
        "canonical_CurNum", "unique_trajectory_identifier", "beginning_utc_time",
        "sol_lon_deg", "computed_SCE_deg_0_360", "computed_SCE_deg_signed", "betgeo_deg",
    ]
    for name in CORE_PREFERRED:
        if name in full.columns and name not in core_cols:
            core_cols.append(name)
    for name in ["canonical_RA_deg", "canonical_DEC_deg", "canonical_Vg_km_s", "gmn_source_month"]:
        if name in full.columns and name not in core_cols:
            core_cols.append(name)
    full[core_cols].to_csv(OUT / "OrbitTrace_April_95_GMN_core_orbits.csv", index=False)

    sce_cols = [
        "canonical_CurNum", "unique_trajectory_identifier", "beginning_utc_time", "sol_lon_deg",
        "computed_SCE_deg_0_360", "computed_SCE_deg_signed", "betgeo_deg", "vgeo_km_s",
    ]
    full[sce_cols].to_csv(OUT / "OrbitTrace_April_95_Sun_centered_ecliptic_coordinates.csv", index=False)
    pd.DataFrame(matching_audit).to_csv(OUT / "matching_audit.csv", index=False)

    member_x = np.asarray(full["computed_SCE_deg_0_360"], dtype=float)
    member_y = np.asarray(full["betgeo_deg"], dtype=float)
    member_v = np.asarray(full["vgeo_km_s"], dtype=float)
    summary = {
        "candidate": "OrbitTrace April candidate (unofficial; no IAU designation claimed)",
        "canonical_gmn_members": 95,
        "per_year_counts": EXPECTED_COUNTS,
        "reference_solution_at_solar_longitude_deg": {
            "solar_longitude_deg": REF_SOL,
            "sun_centered_ecliptic_longitude_signed_deg": REF_SCE_SIGNED,
            "sun_centered_ecliptic_longitude_wrapped_0_360_deg": REF_SCE_WRAPPED,
            "geocentric_ecliptic_latitude_deg": REF_BETA,
            "geocentric_speed_km_s": REF_VG,
        },
        "fitted_radiant_drift_per_degree_solar_longitude": {
            "sun_centered_ecliptic_longitude_deg_per_deg": DRIFT_SCE,
            "ecliptic_latitude_deg_per_deg": DRIFT_BETA,
        },
        "member_residual_1sigma_about_drift_model": {
            "sun_centered_ecliptic_longitude_deg": SIGMA_SCE,
            "ecliptic_latitude_deg": SIGMA_BETA,
            "geocentric_speed_km_s": SIGMA_VG,
        },
        "raw_95_member_descriptives_not_drift_corrected": {
            "circular_mean_SCE_wrapped_deg": circular_mean_deg(member_x),
            "median_SCE_wrapped_deg": float(np.median(member_x)),
            "mean_beta_deg": float(np.mean(member_y)),
            "median_beta_deg": float(np.median(member_y)),
            "mean_Vg_km_s": float(np.mean(member_v)),
            "median_Vg_km_s": float(np.median(member_v)),
        },
        "gmn_coordinate_convention": "X = geocentric ecliptic longitude minus solar longitude; wrapped 0–360 on GMN plots. Signed equivalent of the reference X is -149.3763247 deg; wrapped plot coordinate is 210.6236753 deg.",
        "data_source": "Global Meteor Network monthly trajectory summaries, CC BY 4.0; matched back to the repository's frozen canonical_95.csv by trajectory time and radiant/speed.",
    }
    (OUT / "OrbitTrace_Sun_centered_ecliptic_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    readme = f"""OrbitTrace — package prepared for technical review\n\nContents\n========\n\n1. OrbitTrace_April_95_GMN_full_entries.csv\n   Full GMN parser rows for the 95 frozen canonical members, with canonical match fields prepended.\n\n2. OrbitTrace_April_95_GMN_core_orbits.csv\n   Compact review table containing trajectory IDs, times, Sun-centered radiant coordinates, speed, orbital elements, and quality/station fields available in the GMN files.\n\n3. OrbitTrace_April_95_Sun_centered_ecliptic_coordinates.csv\n   Per-meteor Sun-centered ecliptic coordinates.\n\n4. OrbitTrace_Sun_centered_ecliptic_summary.json\n   Reference solution, radiant drift, dispersion, and raw 95-member descriptives.\n\n5. GMN_April_YYYY_SCE_*_OrbitTrace_marked.png\n   Full-sky and zoomed plots reconstructed directly from the official GMN April monthly trajectory summaries, with the frozen candidate members/reference solution marked.\n\n6. gmn_official_unmarked/\n   Original official GMN monthly density and geocentric-speed PNGs for April 2022–2026, unmodified, for side-by-side checking.\n\n7. matching_audit.csv\n   Row-by-row audit showing the canonical-to-GMN match and residual agreement.\n\nReference Sun-centered ecliptic location\n=======================================\nSolar longitude (J2000): {REF_SOL:.6f} deg\n(lambda_g - lambda_sun), signed: {REF_SCE_SIGNED:.7f} deg\n(lambda_g - lambda_sun), wrapped 0–360 (GMN plot X): {REF_SCE_WRAPPED:.7f} deg\nbeta_g: {REF_BETA:.7f} deg\nVg: {REF_VG:.6f} km/s\n\nImportant: this is a tentative/unofficial shower candidate; the package does not claim an IAU designation.\n\nGMN source: https://globalmeteornetwork.org/data/\nGMN data license: CC BY 4.0\n"""
    (OUT / "README.txt").write_text(readme)

    # Machine-verifiable package manifest.
    manifest = {
        "row_count_full": int(len(full)),
        "unique_trajectory_ids": int(full["unique_trajectory_identifier"].astype(str).nunique()),
        "year_counts": full["gmn_source_month"].value_counts().sort_index().to_dict(),
        "max_matching_errors": {
            "SCE_deg": float(pd.DataFrame(matching_audit)["SCE_abs_error_deg"].max()),
            "beta_deg": float(pd.DataFrame(matching_audit)["beta_abs_error_deg"].max()),
            "Vg_km_s": float(pd.DataFrame(matching_audit)["Vg_abs_error_km_s"].max()),
        },
        "files": sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
