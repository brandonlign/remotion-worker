#!/usr/bin/env python3
"""Independent-catalog validation of the frozen GhostStream April candidate.

The candidate location, drift, activity interval, radiant-speed widths, and
refined orbit are imported unchanged from the GMN discovery/audit stage. This
script applies them to two independently reduced public video-meteor archives:

- SonotaCo annual orbit catalogs (Japan), 2022--2025
- EDMOND annual orbit catalogs (European networks), 2022--2024

No parameter is fitted to either independent archive. A catalog family passes
only if it shows a source-preserving activity enhancement and an independently
compact orbit distribution across multiple years.
"""
from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from scipy.stats import fisher_exact

OUT = Path("ghoststream_independent_validation")
SEED = 20260731

# Frozen from the GMN audit, evaluated at solar longitude 36.901963 deg.
SOL0 = 36.901963
SUNLON0 = -149.3763247
BETA0 = 7.3230377
VG0 = 37.641692
SUNLON_SLOPE = -0.1029483
BETA_SLOPE = -0.0230546
VG_SLOPE = -0.0293492
# Frozen residual dispersions from the deduplicated GMN multi-year fit.
SUNLON_SIGMA = 0.7369
BETA_SIGMA = 0.6250
VG_SIGMA = 1.1596
TIME_HALF_WIDTH = 4.0
SEASON_HALF_WIDTH = 18.0
CORE_RADIUS2 = 9.0
LOCAL_RADIUS2 = 36.0
REFINED_ORBIT = np.asarray([0.946296, 0.079202, 24.709376, 333.493819, 37.937477], dtype=float)
ORBIT_MEMBER_D = 0.15
ORBIT_NULL_DRAWS = 9999
MAX_ORBIT_MEDIAN_D = 0.12
MAX_ORBIT_Q90_D = 0.22
MAX_ORBIT_NULL_P = 0.01
MIN_FAMILY_MEMBERS = 8
MIN_ACTIVE_YEARS = 2
MIN_MEMBERS_PER_ACTIVE_YEAR = 2
MAX_ACTIVITY_P = 0.01
SHIFT_STEP = 0.25
MAX_SHIFT_P = 0.05

ANTIHELION_CENTER = 180.0
ANTIHELION_HALF_WIDTH = 60.0
ANTIHELION_BETA_MAX = 35.0
ANTIHELION_SPEED_MIN = 15.0
ANTIHELION_SPEED_MAX = 50.0

SONOTACO_URL = "https://ceres.ta3.sk/iaumdcdb/dataDBs/video_offline/iaumdcSNMv3_S{yy:02d}.csv.zip"
EDMOND_URL = "https://meteornews.net/assets/2025-03-29-edmond-database/U2_{year}_EDM.zip"
SONOTACO_YEARS = (2022, 2023, 2024, 2025)
EDMOND_YEARS = (2022, 2023, 2024)


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


def solar_longitude_approx(dt: datetime) -> float:
    """Approximate apparent geocentric solar ecliptic longitude (degrees)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    unix_days = dt.timestamp() / 86400.0
    jd = 2440587.5 + unix_days
    n = jd - 2451545.0
    mean_long = (280.460 + 0.9856474 * n) % 360.0
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360.0)
    return float((mean_long + 1.915 * math.sin(mean_anom) + 0.020 * math.sin(2.0 * mean_anom)) % 360.0)


def equatorial_to_ecliptic(ra_deg: np.ndarray, dec_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ra = np.deg2rad(ra_deg)
    dec = np.deg2rad(dec_deg)
    eps = math.radians(23.43928)
    x = np.cos(dec) * np.cos(ra)
    y = np.cos(dec) * np.sin(ra)
    z = np.sin(dec)
    xe = x
    ye = y * math.cos(eps) + z * math.sin(eps)
    ze = -y * math.sin(eps) + z * math.cos(eps)
    lon = np.rad2deg(np.arctan2(ye, xe)) % 360.0
    lat = np.rad2deg(np.arcsin(np.clip(ze, -1.0, 1.0)))
    return lon, lat


def perihelion_vector(orbits: np.ndarray) -> np.ndarray:
    inc = np.deg2rad(orbits[:, 2])
    arg = np.deg2rad(orbits[:, 3])
    node = np.deg2rad(orbits[:, 4])
    return np.column_stack([
        np.cos(node) * np.cos(arg) - np.sin(node) * np.sin(arg) * np.cos(inc),
        np.sin(node) * np.cos(arg) + np.cos(node) * np.sin(arg) * np.cos(inc),
        np.sin(arg) * np.sin(inc),
    ])


def orbit_distance_matrix(a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    b = a if b is None else b
    e1, q1 = a[:, 0][:, None], a[:, 1][:, None]
    e2, q2 = b[:, 0][None, :], b[:, 1][None, :]
    i1, n1 = np.deg2rad(a[:, 2])[:, None], np.deg2rad(a[:, 4])[:, None]
    i2, n2 = np.deg2rad(b[:, 2])[None, :], np.deg2rad(b[:, 4])[None, :]
    plane = np.arccos(np.clip(np.cos(i1) * np.cos(i2) + np.sin(i1) * np.sin(i2) * np.cos(n1 - n2), -1.0, 1.0))
    p1, p2 = perihelion_vector(a), perihelion_vector(b)
    peri = np.arccos(np.clip(p1 @ p2.T, -1.0, 1.0))
    d2 = ((e1 - e2) ** 2 + (q1 - q2) ** 2 + (2.0 * np.sin(plane / 2.0)) ** 2
          + (((e1 + e2) / 2.0) * 2.0 * np.sin(peri / 2.0)) ** 2)
    return np.sqrt(np.maximum(d2, 0.0))


def orbit_summary(orbits: np.ndarray) -> dict[str, Any]:
    matrix = orbit_distance_matrix(orbits)
    index = int(np.argmin(np.median(matrix, axis=1)))
    distances = matrix[index]
    return {
        "medoid": orbits[index],
        "median_d": float(np.median(distances)),
        "q90_d": float(np.percentile(distances, 90)),
    }


def valid_orbits(orbits: np.ndarray) -> np.ndarray:
    valid = np.isfinite(orbits).all(axis=1)
    valid &= (orbits[:, 0] >= 0.0) & (orbits[:, 0] < 1.5)
    valid &= (orbits[:, 1] > 0.0) & (orbits[:, 1] < 2.0)
    valid &= (orbits[:, 2] >= 0.0) & (orbits[:, 2] <= 180.0)
    return valid


def download_zip_csv(url: str, delimiter: str) -> pd.DataFrame:
    response = requests.get(url, timeout=240)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv") and not name.startswith("__MACOSX/")]
        if not members:
            raise RuntimeError(f"No CSV in {url}")
        raw = archive.read(members[0])
    return pd.read_csv(io.BytesIO(raw), sep=delimiter, low_memory=False)


def canonical_frame(sol: np.ndarray, ecl_lon: np.ndarray, ecl_lat: np.ndarray, vg: np.ndarray,
                    e: np.ndarray, q: np.ndarray, inc: np.ndarray, peri: np.ndarray,
                    node: np.ndarray, identifiers: np.ndarray, year: int,
                    source: str) -> pd.DataFrame:
    frame = pd.DataFrame({
        "sol": pd.to_numeric(pd.Series(sol), errors="coerce"),
        "ecl_lon": pd.to_numeric(pd.Series(ecl_lon), errors="coerce"),
        "beta": pd.to_numeric(pd.Series(ecl_lat), errors="coerce"),
        "vg": pd.to_numeric(pd.Series(vg), errors="coerce"),
        "e": pd.to_numeric(pd.Series(e), errors="coerce"),
        "q": pd.to_numeric(pd.Series(q), errors="coerce"),
        "inc": pd.to_numeric(pd.Series(inc), errors="coerce"),
        "peri": pd.to_numeric(pd.Series(peri), errors="coerce"),
        "node": pd.to_numeric(pd.Series(node), errors="coerce"),
        "identifier": pd.Series(identifiers).astype(str),
    })
    frame["year"] = year
    frame["source"] = source
    frame["sunlon"] = circ_diff(frame["ecl_lon"].to_numpy(float), frame["sol"].to_numpy(float))
    values = frame[["e", "q", "inc", "peri", "node"]].to_numpy(float)
    valid = np.isfinite(frame[["sol", "ecl_lon", "beta", "vg"]]).all(axis=1)
    valid &= frame["sol"].between(0, 360)
    valid &= frame["ecl_lon"].between(0, 360)
    valid &= frame["beta"].between(-90, 90)
    valid &= frame["vg"].between(5, 75)
    valid &= valid_orbits(values)
    return frame.loc[valid].reset_index(drop=True)


def load_sonotaco(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = SONOTACO_URL.format(yy=year % 100)
    print(f"Downloading SonotaCo {year}...", flush=True)
    raw = download_zip_csv(url, ";")
    required = ["IID", "Yr", "Mn", "Dayy", "RA", "DECL", "Vg", "q", "e", "i", "arg", "nod"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise RuntimeError(f"SonotaCo {year} missing {missing}")
    yr = pd.to_numeric(raw["Yr"], errors="coerce")
    month = pd.to_numeric(raw["Mn"], errors="coerce")
    dayy = pd.to_numeric(raw["Dayy"], errors="coerce")
    # Restrict to the candidate season before the date-to-solar conversion.
    seasonal = raw.loc[(yr == year) & month.isin([3, 4, 5]) & dayy.notna()].copy()
    dayy = pd.to_numeric(seasonal["Dayy"], errors="coerce").to_numpy(float)
    month_values = pd.to_numeric(seasonal["Mn"], errors="coerce").to_numpy(int)
    datetimes = []
    for month_value, day_value in zip(month_values, dayy):
        day_integer = max(1, int(math.floor(day_value)))
        fraction = day_value - math.floor(day_value)
        base = datetime(year, int(month_value), 1, tzinfo=timezone.utc) + timedelta(days=day_integer - 1 + fraction)
        datetimes.append(base)
    sol_date = np.asarray([solar_longitude_approx(value) for value in datetimes], dtype=float)
    # Use published LS where populated, but report agreement with date-derived values.
    if "LS" in seasonal.columns:
        ls = pd.to_numeric(seasonal["LS"], errors="coerce").to_numpy(float)
        use_ls = np.isfinite(ls)
        sol = sol_date.copy()
        sol[use_ls] = ls[use_ls] % 360.0
        ls_agreement = float(np.nanmedian(np.abs(circ_diff(ls[use_ls], sol_date[use_ls])))) if use_ls.any() else None
    else:
        use_ls = np.zeros(len(seasonal), dtype=bool)
        sol = sol_date
        ls_agreement = None
    ra = pd.to_numeric(seasonal["RA"], errors="coerce").to_numpy(float)
    dec = pd.to_numeric(seasonal["DECL"], errors="coerce").to_numpy(float)
    ecl_lon, ecl_lat = equatorial_to_ecliptic(ra, dec)
    frame = canonical_frame(
        sol, ecl_lon, ecl_lat,
        pd.to_numeric(seasonal["Vg"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["e"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["q"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["i"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["arg"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["nod"], errors="coerce").to_numpy(float),
        seasonal["IID"].astype(str).to_numpy(), year, "SonotaCo",
    )
    return frame, {
        "url": url, "raw_rows": int(len(raw)), "seasonal_rows": int(len(seasonal)),
        "valid_rows": int(len(frame)), "ls_populated": int(use_ls.sum()),
        "median_ls_vs_date_solar_difference_deg": ls_agreement,
    }


def load_edmond(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = EDMOND_URL.format(year=year)
    print(f"Downloading EDMOND {year}...", flush=True)
    raw = download_zip_csv(url, ",")
    required = ["_#", "_sol", "_elng", "_elat", "_vg", "_e", "_q", "_incl", "_peri", "_node"]
    missing = [column for column in required if column not in raw.columns]
    if missing:
        raise RuntimeError(f"EDMOND {year} missing {missing}")
    sol = pd.to_numeric(raw["_sol"], errors="coerce")
    seasonal = raw.loc[np.abs(circ_diff(sol.to_numpy(float), SOL0)) <= SEASON_HALF_WIDTH].copy()
    frame = canonical_frame(
        pd.to_numeric(seasonal["_sol"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_elng"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_elat"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_vg"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_e"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_q"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_incl"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_peri"], errors="coerce").to_numpy(float),
        pd.to_numeric(seasonal["_node"], errors="coerce").to_numpy(float),
        seasonal["_#"].astype(str).to_numpy(), year, "EDMOND",
    )
    return frame, {
        "url": url, "raw_rows": int(len(raw)), "seasonal_rows": int(len(seasonal)),
        "valid_rows": int(len(frame)),
    }


def masks(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    sol = frame["sol"].to_numpy(float)
    delta = circ_diff(sol, SOL0)
    pred_sun = SUNLON0 + SUNLON_SLOPE * delta
    pred_beta = BETA0 + BETA_SLOPE * delta
    pred_vg = VG0 + VG_SLOPE * delta
    score = ((circ_diff(frame["sunlon"].to_numpy(float), pred_sun) / SUNLON_SIGMA) ** 2
             + ((frame["beta"].to_numpy(float) - pred_beta) / BETA_SIGMA) ** 2
             + ((frame["vg"].to_numpy(float) - pred_vg) / VG_SIGMA) ** 2)
    antihelion = (
        np.abs(circ_diff(frame["sunlon"].to_numpy(float) % 360.0, ANTIHELION_CENTER)) <= ANTIHELION_HALF_WIDTH
    ) & (np.abs(frame["beta"].to_numpy(float)) <= ANTIHELION_BETA_MAX) & (
        frame["vg"].to_numpy(float) >= ANTIHELION_SPEED_MIN
    ) & (frame["vg"].to_numpy(float) <= ANTIHELION_SPEED_MAX)
    season = np.abs(delta) <= SEASON_HALF_WIDTH
    temporal = np.abs(delta) <= TIME_HALF_WIDTH
    core = score <= CORE_RADIUS2
    local = score <= LOCAL_RADIUS2
    orbits = frame[["e", "q", "inc", "peri", "node"]].to_numpy(float)
    orbit_d = orbit_distance_matrix(orbits, REFINED_ORBIT[None, :])[:, 0]
    return {
        "delta": delta, "score": score, "antihelion": antihelion,
        "season": season, "temporal": temporal, "core": core,
        "local": local, "orbit_d": orbit_d,
        "member": core & temporal & antihelion & (orbit_d <= ORBIT_MEMBER_D),
    }


def activity_test(frame: pd.DataFrame, m: dict[str, np.ndarray]) -> dict[str, Any]:
    background = m["antihelion"] & m["season"]
    core = m["core"] & background
    inside = m["temporal"]
    a = int(np.sum(core & inside))
    b = int(np.sum(background & inside & ~core))
    c = int(np.sum(core & ~inside))
    d = int(np.sum(background & ~inside & ~core))
    odds, p = fisher_exact([[a, b], [c, d]], alternative="greater")
    return {
        "table": [[a, b], [c, d]], "core_inside": a,
        "antihelion_inside": a + b, "core_outside": c,
        "antihelion_outside": c + d, "odds_ratio": float(odds), "p": float(p),
    }


def shifted_window_test(frame: pd.DataFrame, m: dict[str, np.ndarray]) -> dict[str, Any]:
    sol = frame["sol"].to_numpy(float)
    antihelion = m["antihelion"] & m["season"]
    core = m["core"] & antihelion
    observed = m["temporal"]
    observed_num = int(np.sum(core & observed))
    observed_den = int(np.sum(antihelion & observed))
    observed_ratio = observed_num / observed_den if observed_den else 0.0
    controls = []
    for offset in np.arange(-SEASON_HALF_WIDTH + TIME_HALF_WIDTH,
                            SEASON_HALF_WIDTH - TIME_HALF_WIDTH + 1e-9, SHIFT_STEP):
        if abs(offset) <= 2.0 * TIME_HALF_WIDTH:
            continue
        center = (SOL0 + offset) % 360.0
        window = np.abs(circ_diff(sol, center)) <= TIME_HALF_WIDTH
        den = int(np.sum(antihelion & window))
        if den < 5:
            continue
        num = int(np.sum(core & window))
        controls.append({"offset": float(offset), "core": num, "background": den,
                         "ratio": float(num / den)})
    p = ((1 + sum(item["ratio"] >= observed_ratio for item in controls)) /
         (1 + len(controls))) if controls else 1.0
    return {
        "observed_core": observed_num, "observed_background": observed_den,
        "observed_ratio": float(observed_ratio), "control_windows": int(len(controls)),
        "empirical_p": float(p),
        "control_q95": float(np.percentile([item["ratio"] for item in controls], 95)) if controls else None,
        "top_controls": sorted(controls, key=lambda item: item["ratio"], reverse=True)[:10],
    }


def orbit_test(frame: pd.DataFrame, m: dict[str, np.ndarray], seed: int) -> dict[str, Any]:
    selected = m["member"]
    orbits = frame.loc[selected, ["e", "q", "inc", "peri", "node"]].to_numpy(float)
    if len(orbits) < 2:
        return {"members": int(len(orbits)), "passed": False, "reason": "too_few_members"}
    observed = orbit_summary(orbits)
    # Source- and time-matched null outside the fine radiant-speed core.
    pool_mask = m["antihelion"] & m["temporal"] & ~m["core"]
    pool = frame.loc[pool_mask, ["e", "q", "inc", "peri", "node"]].to_numpy(float)
    if len(pool) < len(orbits) * 3:
        pool_mask = m["antihelion"] & m["season"] & m["local"] & ~m["core"]
        pool = frame.loc[pool_mask, ["e", "q", "inc", "peri", "node"]].to_numpy(float)
        pool_kind = "seasonal_local_shell"
    else:
        pool_kind = "same_time_antihelion_outside_core"
    if len(pool) < len(orbits) * 3:
        return {"members": int(len(orbits)), "pool": int(len(pool)), "observed": observed,
                "passed": False, "reason": "insufficient_null_pool", "pool_kind": pool_kind}
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(ORBIT_NULL_DRAWS):
        sample = pool[rng.choice(len(pool), size=len(orbits), replace=False)]
        null.append(float(orbit_summary(sample)["median_d"]))
    p = (1 + sum(value <= observed["median_d"] for value in null)) / (ORBIT_NULL_DRAWS + 1)
    return {
        "members": int(len(orbits)), "pool": int(len(pool)), "pool_kind": pool_kind,
        "observed": observed, "null_p": float(p),
        "null_q01": float(np.percentile(null, 1)),
        "passed": bool(observed["median_d"] <= MAX_ORBIT_MEDIAN_D
                       and observed["q90_d"] <= MAX_ORBIT_Q90_D
                       and p <= MAX_ORBIT_NULL_P),
    }


def combine_years(frames: list[pd.DataFrame], source: str) -> dict[str, Any]:
    combined = pd.concat(frames, ignore_index=True, sort=False)
    m = masks(combined)
    activity = activity_test(combined, m)
    shift = shifted_window_test(combined, m)
    orbit = orbit_test(combined, m, SEED + (1 if source == "SonotaCo" else 2))
    members = combined.loc[m["member"]].copy()
    member_counts = {str(int(year)): int(count) for year, count in members["year"].value_counts().sort_index().items()}
    active_years = [int(year) for year, count in members["year"].value_counts().items()
                    if int(count) >= MIN_MEMBERS_PER_ACTIVE_YEAR]
    passed = bool(
        len(members) >= MIN_FAMILY_MEMBERS
        and len(active_years) >= MIN_ACTIVE_YEARS
        and activity["p"] <= MAX_ACTIVITY_P
        and shift["empirical_p"] <= MAX_SHIFT_P
        and orbit.get("passed", False)
    )
    member_columns = ["source", "year", "identifier", "sol", "sunlon", "beta", "vg",
                      "e", "q", "inc", "peri", "node"]
    members[member_columns].to_csv(OUT / f"{source.lower()}_members.csv", index=False)
    return {
        "source": source, "rows": int(len(combined)), "members": int(len(members)),
        "member_counts_by_year": member_counts, "active_years": sorted(active_years),
        "activity": activity, "shifted_windows": shift, "orbit": orbit,
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
    sonotaco_frames, sonotaco_meta = [], {}
    for year in SONOTACO_YEARS:
        try:
            frame, meta = load_sonotaco(year)
            sonotaco_frames.append(frame)
            sonotaco_meta[str(year)] = meta
            print(f"SonotaCo {year}: valid seasonal rows={len(frame):,}", flush=True)
        except Exception as exc:
            sonotaco_meta[str(year)] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"SonotaCo {year}: ERROR {exc}", flush=True)
    edmond_frames, edmond_meta = [], {}
    for year in EDMOND_YEARS:
        try:
            frame, meta = load_edmond(year)
            edmond_frames.append(frame)
            edmond_meta[str(year)] = meta
            print(f"EDMOND {year}: valid seasonal rows={len(frame):,}", flush=True)
        except Exception as exc:
            edmond_meta[str(year)] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"EDMOND {year}: ERROR {exc}", flush=True)
    sonotaco = combine_years(sonotaco_frames, "SonotaCo") if sonotaco_frames else {"passed": False, "reason": "no_data"}
    edmond = combine_years(edmond_frames, "EDMOND") if edmond_frames else {"passed": False, "reason": "no_data"}
    passed = bool(sonotaco.get("passed") and edmond.get("passed"))
    verdict = ("APRIL_STREAM_INDEPENDENTLY_REPLICATED_IN_SONOTACO_AND_EDMOND"
               if passed else "APRIL_STREAM_FAILS_TWO_CATALOG_INDEPENDENT_REPLICATION")
    payload = {
        "stage": "independent_catalog_replication",
        "verdict": verdict, "passed": passed,
        "candidate_frozen_from_gmn": True,
        "frozen_template": {
            "solar_longitude_center_deg": SOL0,
            "time_half_width_deg": TIME_HALF_WIDTH,
            "sun_centered_longitude": {"center": SUNLON0, "slope": SUNLON_SLOPE, "sigma": SUNLON_SIGMA},
            "ecliptic_latitude": {"center": BETA0, "slope": BETA_SLOPE, "sigma": BETA_SIGMA},
            "geocentric_speed": {"center": VG0, "slope": VG_SLOPE, "sigma": VG_SIGMA},
            "refined_orbit": REFINED_ORBIT,
            "radiant_speed_core_radius_squared": CORE_RADIUS2,
            "orbit_member_d": ORBIT_MEMBER_D,
        },
        "rules": {
            "minimum_members_per_family": MIN_FAMILY_MEMBERS,
            "minimum_active_years": MIN_ACTIVE_YEARS,
            "minimum_members_per_active_year": MIN_MEMBERS_PER_ACTIVE_YEAR,
            "maximum_activity_p": MAX_ACTIVITY_P,
            "maximum_shifted_window_p": MAX_SHIFT_P,
            "maximum_orbit_null_p": MAX_ORBIT_NULL_P,
            "maximum_orbit_median_d": MAX_ORBIT_MEDIAN_D,
        },
        "sonotaco": sonotaco, "sonotaco_downloads": sonotaco_meta,
        "edmond": edmond, "edmond_downloads": edmond_meta,
        "independence_note": (
            "SonotaCo is a Japanese video-meteor catalog independently reduced from GMN. "
            "EDMOND aggregates European video networks and may share some upstream observations "
            "with other historical databases, so the strongest network-independent contrast is GMN versus SonotaCo."
        ),
    }
    (OUT / "independent_catalog_validation.json").write_text(json.dumps(jsonable(payload), indent=2) + "\n")
    lines = [
        "# Independent catalog validation of the GhostStream April candidate", "",
        f"**Verdict:** `{verdict}`", "",
        "The candidate template was frozen from GMN before either independent archive was inspected. No center, drift, width, activity interval, or orbit threshold was refit.", "",
    ]
    for result in [sonotaco, edmond]:
        source = result.get("source", "Unknown")
        lines += [f"## {source}", "",
                  f"- Members: **{result.get('members')}**",
                  f"- Members by year: `{result.get('member_counts_by_year')}`",
                  f"- Activity p: **{result.get('activity', {}).get('p')}**",
                  f"- Shifted-window p: **{result.get('shifted_windows', {}).get('empirical_p')}**",
                  f"- Orbit median D: **{result.get('orbit', {}).get('observed', {}).get('median_d')}**",
                  f"- Orbit-null p: **{result.get('orbit', {}).get('null_p')}**",
                  f"- Family gate: **{result.get('passed')}**", ""]
    lines += ["A pass establishes independent catalog replication, not official IAU recognition. Network provenance, literature novelty, and parent-body dynamics still require review.", ""]
    (OUT / "INDEPENDENT_CATALOG_VALIDATION.md").write_text("\n".join(lines))
    print(f"\nVerdict: {verdict}")
    print(f"SonotaCo: {sonotaco}")
    print(f"EDMOND: {edmond}")
    print(f"Report: {OUT / 'INDEPENDENT_CATALOG_VALIDATION.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
