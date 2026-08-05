#!/usr/bin/env python3
"""Apply the frozen GhostStream April solution to the official legacy CAMS catalog."""
from __future__ import annotations

import io
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from scipy.stats import fisher_exact

OUT = Path("ghoststream_cams_validation")
CAMS_URL = "https://www.astro.sk/~ne/IAUMDC/PhVR2020/CAMS_by_date_v2.1l"
SEED = 20260731
SOL0 = 36.901963
SUNLON0 = -149.3763247
BETA0 = 7.3230377
VG0 = 37.641692
SUNLON_SLOPE = -0.1029483
BETA_SLOPE = -0.0230546
VG_SLOPE = -0.0293492
SUNLON_SIGMA = 0.7369
BETA_SIGMA = 0.6250
VG_SIGMA = 1.1596
REFINED_ORBIT = np.asarray([0.946296, 0.079202, 24.709376, 333.493819, 37.937477], dtype=float)
TIME_HALF_WIDTH = 4.0
SEASON_HALF_WIDTH = 18.0
CORE_RADIUS2 = 9.0
LOCAL_RADIUS2 = 36.0
ORBIT_MEMBER_D = 0.15
NULL_DRAWS = 9999
MIN_MEMBERS = 5
MIN_ACTIVE_YEARS = 2
MIN_PER_ACTIVE_YEAR = 2
MAX_ACTIVITY_P = 0.01
MAX_SHIFT_P = 0.05
MAX_ORBIT_MEDIAN_D = 0.12
MAX_ORBIT_Q90_D = 0.22
MAX_ORBIT_NULL_P = 0.01
ANTIHELION_CENTER = 180.0
ANTIHELION_HALF_WIDTH = 60.0
ANTIHELION_BETA_MAX = 35.0
ANTIHELION_SPEED_MIN = 15.0
ANTIHELION_SPEED_MAX = 50.0


def circ_diff(value: np.ndarray | float, center: np.ndarray | float) -> np.ndarray:
    return (np.asarray(value) - np.asarray(center) + 180.0) % 360.0 - 180.0


def solar_longitude_approx(dt: datetime) -> float:
    jd = 2440587.5 + dt.timestamp() / 86400.0
    n = jd - 2451545.0
    mean_long = (280.460 + 0.9856474 * n) % 360.0
    mean_anom = math.radians((357.528 + 0.9856003 * n) % 360.0)
    return float((mean_long + 1.915 * math.sin(mean_anom) + 0.020 * math.sin(2.0 * mean_anom)) % 360.0)


def equatorial_to_ecliptic(ra_deg: np.ndarray, dec_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ra = np.deg2rad(ra_deg); dec = np.deg2rad(dec_deg); eps = math.radians(23.43928)
    x = np.cos(dec) * np.cos(ra); y = np.cos(dec) * np.sin(ra); z = np.sin(dec)
    ye = y * math.cos(eps) + z * math.sin(eps)
    ze = -y * math.sin(eps) + z * math.cos(eps)
    return np.rad2deg(np.arctan2(ye, x)) % 360.0, np.rad2deg(np.arcsin(np.clip(ze, -1, 1)))


def perihelion_vector(orbits: np.ndarray) -> np.ndarray:
    inc = np.deg2rad(orbits[:, 2]); arg = np.deg2rad(orbits[:, 3]); node = np.deg2rad(orbits[:, 4])
    return np.column_stack([
        np.cos(node) * np.cos(arg) - np.sin(node) * np.sin(arg) * np.cos(inc),
        np.sin(node) * np.cos(arg) + np.cos(node) * np.sin(arg) * np.cos(inc),
        np.sin(arg) * np.sin(inc),
    ])


def orbit_distance_matrix(a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    b = a if b is None else b
    e1, q1 = a[:, 0][:, None], a[:, 1][:, None]; e2, q2 = b[:, 0][None, :], b[:, 1][None, :]
    i1, n1 = np.deg2rad(a[:, 2])[:, None], np.deg2rad(a[:, 4])[:, None]
    i2, n2 = np.deg2rad(b[:, 2])[None, :], np.deg2rad(b[:, 4])[None, :]
    plane = np.arccos(np.clip(np.cos(i1) * np.cos(i2) + np.sin(i1) * np.sin(i2) * np.cos(n1 - n2), -1, 1))
    p1, p2 = perihelion_vector(a), perihelion_vector(b)
    peri = np.arccos(np.clip(p1 @ p2.T, -1, 1))
    d2 = ((e1-e2)**2 + (q1-q2)**2 + (2*np.sin(plane/2))**2
          + (((e1+e2)/2)*2*np.sin(peri/2))**2)
    return np.sqrt(np.maximum(d2, 0.0))


def orbit_summary(orbits: np.ndarray) -> dict[str, Any]:
    matrix = orbit_distance_matrix(orbits)
    idx = int(np.argmin(np.median(matrix, axis=1)))
    distances = matrix[idx]
    return {"medoid": orbits[idx], "median_d": float(np.median(distances)),
            "q90_d": float(np.percentile(distances, 90))}


def parse_catalog() -> pd.DataFrame:
    response = requests.get(CAMS_URL, timeout=240)
    response.raise_for_status()
    lines = response.text.splitlines()[2:]
    rows = []
    for line in lines:
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            rows.append({
                "id": parts[0], "year": int(parts[1]), "month": int(parts[2]), "day": float(parts[3]),
                "q": float(parts[4]), "e": float(parts[5]), "inc": float(parts[6]),
                "peri": float(parts[7]), "node_raw": float(parts[8]),
                "ra": float(parts[9]), "dec": float(parts[10]), "vg": float(parts[11]),
                "vh": float(parts[12]),
            })
        except ValueError:
            continue
    frame = pd.DataFrame(rows)
    datetimes = []
    for row in frame.itertuples(index=False):
        day_integer = max(1, int(math.floor(row.day)))
        fraction = row.day - math.floor(row.day)
        dt = datetime(row.year, row.month, 1, tzinfo=timezone.utc) + timedelta(days=day_integer - 1 + fraction)
        datetimes.append(dt)
    frame["datetime"] = datetimes
    frame["sol"] = [solar_longitude_approx(dt) for dt in datetimes]
    ecl_lon, beta = equatorial_to_ecliptic(frame["ra"].to_numpy(float), frame["dec"].to_numpy(float))
    frame["ecl_lon"] = ecl_lon; frame["beta"] = beta
    frame["sunlon"] = circ_diff(ecl_lon, frame["sol"].to_numpy(float))
    node = frame["node_raw"].to_numpy(float).copy() % 360.0
    peri = frame["peri"].to_numpy(float).copy() % 360.0
    opposite = np.abs(circ_diff(node, frame["sol"].to_numpy(float))) > 90.0
    node[opposite] = (node[opposite] + 180.0) % 360.0
    peri[opposite] = (peri[opposite] + 180.0) % 360.0
    frame["node"] = node; frame["peri_norm"] = peri
    frame["node_convention_flipped"] = opposite
    valid = np.isfinite(frame[["sol","sunlon","beta","vg","e","q","inc","peri_norm","node"]]).all(axis=1)
    valid &= frame["vg"].between(5,75) & frame["q"].between(0.001,2) & frame["e"].between(0,1.5)
    return frame.loc[valid].reset_index(drop=True)


def masks(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    sol = frame["sol"].to_numpy(float); delta = circ_diff(sol, SOL0)
    pred_sun = SUNLON0 + SUNLON_SLOPE * delta
    pred_beta = BETA0 + BETA_SLOPE * delta
    pred_vg = VG0 + VG_SLOPE * delta
    score = ((circ_diff(frame["sunlon"].to_numpy(float), pred_sun)/SUNLON_SIGMA)**2
             + ((frame["beta"].to_numpy(float)-pred_beta)/BETA_SIGMA)**2
             + ((frame["vg"].to_numpy(float)-pred_vg)/VG_SIGMA)**2)
    antihelion = (np.abs(circ_diff(frame["sunlon"].to_numpy(float)%360, ANTIHELION_CENTER)) <= ANTIHELION_HALF_WIDTH)
    antihelion &= np.abs(frame["beta"].to_numpy(float)) <= ANTIHELION_BETA_MAX
    antihelion &= frame["vg"].to_numpy(float) >= ANTIHELION_SPEED_MIN
    antihelion &= frame["vg"].to_numpy(float) <= ANTIHELION_SPEED_MAX
    season = np.abs(delta) <= SEASON_HALF_WIDTH; temporal = np.abs(delta) <= TIME_HALF_WIDTH
    core = score <= CORE_RADIUS2; local = score <= LOCAL_RADIUS2
    orbits = frame[["e","q","inc","peri_norm","node"]].to_numpy(float)
    orbit_d = orbit_distance_matrix(orbits, REFINED_ORBIT[None,:])[:,0]
    return {"delta":delta,"score":score,"antihelion":antihelion,"season":season,
            "temporal":temporal,"core":core,"local":local,"orbit_d":orbit_d,
            "radiant_time_member":core & temporal & antihelion,
            "strict_member":core & temporal & antihelion & (orbit_d<=ORBIT_MEMBER_D)}


def activity_test(frame: pd.DataFrame, m: dict[str,np.ndarray]) -> dict[str,Any]:
    bg=m["antihelion"]&m["season"]; core=m["core"]&bg; inside=m["temporal"]
    a=int(np.sum(core&inside)); b=int(np.sum(bg&inside&~core)); c=int(np.sum(core&~inside)); d=int(np.sum(bg&~inside&~core))
    odds,p=fisher_exact([[a,b],[c,d]],alternative="greater")
    return {"table":[[a,b],[c,d]],"core_inside":a,"background_inside":a+b,
            "core_outside":c,"background_outside":c+d,"odds_ratio":float(odds),"p":float(p)}


def shifted_test(frame: pd.DataFrame,m:dict[str,np.ndarray])->dict[str,Any]:
    sol=frame["sol"].to_numpy(float); bg=m["antihelion"]&m["season"]; core=m["core"]&bg
    obs=m["temporal"]; on=int(np.sum(core&obs)); od=int(np.sum(bg&obs)); ratio=on/od if od else 0
    controls=[]
    for offset in np.arange(-SEASON_HALF_WIDTH+TIME_HALF_WIDTH,SEASON_HALF_WIDTH-TIME_HALF_WIDTH+1e-9,.25):
        if abs(offset)<=2*TIME_HALF_WIDTH: continue
        win=np.abs(circ_diff(sol,(SOL0+offset)%360))<=TIME_HALF_WIDTH; den=int(np.sum(bg&win))
        if den<5: continue
        num=int(np.sum(core&win)); controls.append(num/den)
    p=(1+sum(x>=ratio for x in controls))/(1+len(controls)) if controls else 1
    return {"observed_core":on,"observed_background":od,"observed_ratio":ratio,
            "control_windows":len(controls),"empirical_p":float(p),
            "control_q95":float(np.percentile(controls,95)) if controls else None}


def orbit_test(frame:pd.DataFrame,m:dict[str,np.ndarray])->dict[str,Any]:
    selected=m["radiant_time_member"]
    orbits=frame.loc[selected,["e","q","inc","peri_norm","node"]].to_numpy(float)
    if len(orbits)<2:return {"members":len(orbits),"passed":False,"reason":"too_few"}
    observed=orbit_summary(orbits)
    pool_mask=m["antihelion"]&m["temporal"]&~m["core"]
    pool=frame.loc[pool_mask,["e","q","inc","peri_norm","node"]].to_numpy(float)
    if len(pool)<len(orbits)*3:
        pool_mask=m["antihelion"]&m["season"]&m["local"]&~m["core"]
        pool=frame.loc[pool_mask,["e","q","inc","peri_norm","node"]].to_numpy(float)
    if len(pool)<len(orbits)*3:return {"members":len(orbits),"pool":len(pool),"observed":observed,"passed":False,"reason":"small_pool"}
    rng=np.random.default_rng(SEED); null=[]
    for _ in range(NULL_DRAWS):
        sample=pool[rng.choice(len(pool),size=len(orbits),replace=False)]
        null.append(orbit_summary(sample)["median_d"])
    p=(1+sum(x<=observed["median_d"] for x in null))/(NULL_DRAWS+1)
    return {"members":len(orbits),"pool":len(pool),"observed":observed,"null_p":float(p),
            "null_q01":float(np.percentile(null,1)),"passed":bool(observed["median_d"]<=MAX_ORBIT_MEDIAN_D and observed["q90_d"]<=MAX_ORBIT_Q90_D and p<=MAX_ORBIT_NULL_P)}


def main()->int:
    OUT.mkdir(exist_ok=True); frame=parse_catalog(); m=masks(frame)
    activity=activity_test(frame,m); shift=shifted_test(frame,m); orbit=orbit_test(frame,m)
    members=frame.loc[m["strict_member"]].copy()
    counts={str(int(y)):int(n) for y,n in members["year"].value_counts().sort_index().items()}
    active=[int(y) for y,n in members["year"].value_counts().items() if int(n)>=MIN_PER_ACTIVE_YEAR]
    passed=bool(len(members)>=MIN_MEMBERS and len(active)>=MIN_ACTIVE_YEARS and activity["p"]<=MAX_ACTIVITY_P and shift["empirical_p"]<=MAX_SHIFT_P and orbit.get("passed",False))
    verdict="APRIL_STREAM_REPLICATED_IN_LEGACY_CAMS" if passed else "APRIL_STREAM_NOT_REPLICATED_IN_LEGACY_CAMS"
    cols=["id","year","month","day","sol","sunlon","beta","vg","e","q","inc","peri_norm","node","orbit_d"]
    frame["orbit_d"]=m["orbit_d"]; members[cols].to_csv(OUT/"cams_candidate_members.csv",index=False)
    payload={"verdict":verdict,"passed":passed,"url":CAMS_URL,"catalog_rows":len(frame),
             "years":sorted(map(int,frame["year"].unique())),"node_flips":int(frame["node_convention_flipped"].sum()),
             "strict_members":len(members),"member_counts_by_year":counts,"active_years":sorted(active),
             "activity":activity,"shifted_windows":shift,"orbit":orbit}
    (OUT/"cams_validation.json").write_text(json.dumps(payload,indent=2,default=lambda x:x.tolist() if isinstance(x,np.ndarray) else str(x))+"\n")
    lines=["# Legacy CAMS validation", "",f"**Verdict:** `{verdict}`","",f"- Catalog rows: **{len(frame)}**",f"- Years: **{payload['years']}**",f"- Strict members: **{len(members)}**",f"- By year: `{counts}`",f"- Activity p: **{activity['p']}**",f"- Shifted-window p: **{shift['empirical_p']}**",f"- Orbit median D: **{orbit.get('observed',{}).get('median_d')}**",f"- Orbit-null p: **{orbit.get('null_p')}**",""]
    (OUT/"CAMS_VALIDATION.md").write_text("\n".join(lines))
    print(f"Verdict: {verdict}");print(f"Catalog rows: {len(frame)} years={payload['years']}");print(f"Members: {len(members)} {counts}");print(f"Activity p={activity['p']} shift p={shift['empirical_p']} orbit={orbit}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
