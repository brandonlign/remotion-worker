#!/usr/bin/env python3
"""Corrected independent-catalog validation.

Uses permanent original SonotaCo yearly archives, normalizes the 180-degree
ascending/descending-node convention, derives ecliptic radiants from RA/Dec in
both catalogs, and tests orbital coherence without using orbit to select the
radiant-time core.
"""
from __future__ import annotations

import io
import math
import zipfile
from typing import Any

import numpy as np
import pandas as pd
import requests

import validate_independent_catalogs as base

SONOTACO_ORIGINAL = "https://www.astro.sk/iaumdcDB/public/data/SNMv3/{yy:03d}a.zip"
EDMOND_CANDIDATES = {
    2022: ["https://meteornews.net/assets/2025-03-29-edmond-database/U2_2022_EDM.zip"],
    2023: ["https://meteornews.net/assets/2025-03-29-edmond-database/U2_2023_EDM.zip"],
    2024: [
        "https://meteornews.net/assets/2025-03-29-edmond-database/U2_2024_EDM.zip",
        "https://meteornews.net/assets/2025-05-29-edmond-database/U2_2024_EDM.zip",
        "https://meteornews.net/assets/2025-05-01-edmond-database/U2_2024_EDM.zip",
    ],
}


def read_zip_csv(url: str) -> tuple[pd.DataFrame, str, int]:
    response = requests.get(url, timeout=240)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = [name for name in archive.namelist()
                   if name.lower().endswith(".csv") and "__note" not in name.lower()
                   and not name.startswith("__MACOSX/")]
        if not members:
            raise RuntimeError(f"No data CSV in {url}")
        member = members[0]
        raw = archive.read(member)
    frame = pd.read_csv(io.BytesIO(raw), sep=",", low_memory=False)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame, member, len(response.content)


def normalize_node_peri(sol: np.ndarray, node: np.ndarray, peri: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    node = np.asarray(node, dtype=float).copy() % 360.0
    peri = np.asarray(peri, dtype=float).copy() % 360.0
    opposite = np.abs(base.circ_diff(node, sol)) > 90.0
    node[opposite] = (node[opposite] + 180.0) % 360.0
    peri[opposite] = (peri[opposite] + 180.0) % 360.0
    return node, peri, int(opposite.sum())


def corrected_sonotaco(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = SONOTACO_ORIGINAL.format(yy=year % 1000)
    print(f"Downloading permanent SonotaCo {year}...", flush=True)
    raw, member, archive_bytes = read_zip_csv(url)
    required = ["day(UT)", "time(UT)", "sol(deg)", "ra(deg)", "de(deg)",
                "vg(km/s)", "q(AU)", "e", "peri(deg)", "node(deg)", "incl(deg)"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise RuntimeError(f"SonotaCo {year} missing {missing}; columns={list(raw.columns)}")
    sol_all = pd.to_numeric(raw["sol(deg)"], errors="coerce").to_numpy(float)
    seasonal_mask = np.isfinite(sol_all) & (np.abs(base.circ_diff(sol_all, base.SOL0)) <= base.SEASON_HALF_WIDTH)
    seasonal = raw.loc[seasonal_mask].copy()
    sol = pd.to_numeric(seasonal["sol(deg)"], errors="coerce").to_numpy(float)
    ra = pd.to_numeric(seasonal["ra(deg)"], errors="coerce").to_numpy(float)
    dec = pd.to_numeric(seasonal["de(deg)"], errors="coerce").to_numpy(float)
    ecl_lon, ecl_lat = base.equatorial_to_ecliptic(ra, dec)
    node_raw = pd.to_numeric(seasonal["node(deg)"], errors="coerce").to_numpy(float)
    peri_raw = pd.to_numeric(seasonal["peri(deg)"], errors="coerce").to_numpy(float)
    node, peri, flipped = normalize_node_peri(sol, node_raw, peri_raw)
    identifiers = (seasonal["day(UT)"].astype(str).str.strip() + "T"
                   + seasonal["time(UT)"].astype(str).str.strip()).to_numpy()
    frame = base.canonical_frame(
        sol, ecl_lon, ecl_lat,
        pd.to_numeric(seasonal["vg(km/s)"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["e"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["q(AU)"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["incl(deg)"], errors="coerce").to_numpy(float),
        peri, node, identifiers, year, "SonotaCo",
    )
    return frame, {
        "url": url, "zip_member": member, "archive_bytes": archive_bytes,
        "raw_rows": int(len(raw)), "seasonal_rows": int(len(seasonal)),
        "valid_rows": int(len(frame)), "opposite_node_solutions_normalized": flipped,
        "schema": "SNMv3 original UFO-Orbit standardized CSV",
    }


def corrected_edmond(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    errors = []
    raw = member = url = None
    archive_bytes = 0
    for candidate in EDMOND_CANDIDATES[year]:
        try:
            raw, member, archive_bytes = read_zip_csv(candidate)
            url = candidate
            break
        except Exception as exc:
            errors.append(f"{candidate}: {type(exc).__name__}: {exc}")
    if raw is None or url is None:
        raise RuntimeError("; ".join(errors))
    print(f"Downloading EDMOND {year} from {url}...", flush=True)
    required = ["_#", "_sol", "_ra_t", "_dc_t", "_vg", "_q", "_e", "_peri", "_node", "_incl"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise RuntimeError(f"EDMOND {year} missing {missing}; columns={list(raw.columns)}")
    sol_all = pd.to_numeric(raw["_sol"], errors="coerce").to_numpy(float)
    seasonal_mask = np.isfinite(sol_all) & (np.abs(base.circ_diff(sol_all, base.SOL0)) <= base.SEASON_HALF_WIDTH)
    seasonal = raw.loc[seasonal_mask].copy()
    sol = pd.to_numeric(seasonal["_sol"], errors="coerce").to_numpy(float)
    ra = pd.to_numeric(seasonal["_ra_t"], errors="coerce").to_numpy(float)
    dec = pd.to_numeric(seasonal["_dc_t"], errors="coerce").to_numpy(float)
    ecl_lon, ecl_lat = base.equatorial_to_ecliptic(ra, dec)
    node_raw = pd.to_numeric(seasonal["_node"], errors="coerce").to_numpy(float)
    peri_raw = pd.to_numeric(seasonal["_peri"], errors="coerce").to_numpy(float)
    node, peri, flipped = normalize_node_peri(sol, node_raw, peri_raw)
    frame = base.canonical_frame(
        sol, ecl_lon, ecl_lat,
        pd.to_numeric(seasonal["_vg"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_e"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_q"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_incl"], errors="coerce").to_numpy(float),
        peri, node, seasonal["_#"].astype(str).to_numpy(), year, "EDMOND",
    )
    return frame, {
        "url": url, "attempt_errors": errors, "zip_member": member,
        "archive_bytes": archive_bytes, "raw_rows": int(len(raw)),
        "seasonal_rows": int(len(seasonal)), "valid_rows": int(len(frame)),
        "opposite_node_solutions_normalized": flipped,
        "schema": "EDMOND UFO-Orbit CSV; ecliptic radiant recomputed from RA/Dec",
    }


original_masks = base.masks


def node_independent_masks(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    result = original_masks(frame)
    # Independent members are defined by radiant, speed, activity interval, and
    # broad source only. Orbit is evaluated afterward, not used to select them.
    result["member"] = result["core"] & result["temporal"] & result["antihelion"]
    return result


base.load_sonotaco = corrected_sonotaco
base.load_edmond = corrected_edmond
base.masks = node_independent_masks
base.SONOTACO_YEARS = (2022, 2023, 2024, 2025)
base.EDMOND_YEARS = (2022, 2023, 2024)

if __name__ == "__main__":
    raise SystemExit(base.main())
