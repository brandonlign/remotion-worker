#!/usr/bin/env python3
"""Run one month with drift- and activity-aware IAU catalog matching."""
import os
import re
from pathlib import Path

month = int(os.environ["GHOSTSTREAM_MONTH"])
if month < 1 or month > 12:
    raise SystemExit(f"Invalid GHOSTSTREAM_MONTH={month}")
path = Path(__file__).with_name("run_novel_search.py")
source = path.read_text()
source = source.replace("MONTHS = tuple(range(1, 13))", f"MONTHS = ({month},)")
old_split = '''        ordered_nights = {value: index for index, value in enumerate(sorted(unique_nights.tolist()))}
        split_a_members = np.asarray([ordered_nights[value] % 2 == 0 for value in member_nights])
        split_a_all = np.asarray([ordered_nights.get(value, 0) % 2 == 0 for value in nights])
'''
new_split = '''        global_night_order = {value: index for index, value in enumerate(sorted(np.unique(nights).tolist()))}
        split_a_all = np.asarray([global_night_order[value] % 2 == 0 for value in nights])
        split_a_members = split_a_all[members]
'''
if old_split not in source:
    raise SystemExit("Expected observing-night split block not found")
source = source.replace(old_split, new_split)

new_parse = r'''def ecliptic_to_equatorial(lam_deg: float, beta_deg: float) -> tuple[float, float]:
    lam, beta, eps = np.deg2rad([lam_deg, beta_deg, 23.43928])
    x = np.cos(beta) * np.cos(lam)
    y = np.cos(beta) * np.sin(lam)
    z = np.sin(beta)
    ye = y * np.cos(eps) - z * np.sin(eps)
    ze = y * np.sin(eps) + z * np.cos(eps)
    return float(np.rad2deg(np.arctan2(ye, x)) % 360.0), float(np.rad2deg(np.arcsin(np.clip(ze, -1, 1))))


def angular_separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    a1, d1, a2, d2 = np.deg2rad([ra1, dec1, ra2, dec2])
    cosine = np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(a1 - a2)
    return float(np.rad2deg(np.arccos(np.clip(cosine, -1, 1))))


def active_at(sol: float, start: float | None, end: float | None, mean: float, pad: float = 2.0) -> bool:
    if start is None or end is None:
        return abs(float(circ_diff(sol, mean))) <= 10.0
    span = (end - start) % 360.0
    phase = (sol - start) % 360.0
    return phase <= span or abs(float(circ_diff(sol, start))) <= pad or abs(float(circ_diff(sol, end))) <= pad


def parse_iau() -> list[dict[str, Any]]:
    text = requests.get(IAU_URL, timeout=60).text
    solutions: list[dict[str, Any]] = []
    for line in text.splitlines():
        if "|" not in line or not line.lstrip().startswith('"'):
            continue
        try:
            row = next(csv.reader(io.StringIO(line), delimiter="|", quotechar='"'))
        except Exception:
            continue
        if len(row) < 29:
            continue
        sol, vg, slon, beta = number(row[10]), number(row[15]), number(row[17]), number(row[18])
        ra, dec = number(row[11]), number(row[12])
        if None in {sol, vg, slon, beta, ra, dec}:
            continue
        e, q, peri, node, inc = number(row[24]), number(row[23]), number(row[25]), number(row[26]), number(row[27])
        orbit = None if None in {e, q, peri, node, inc} else np.asarray([e, q, inc, peri, node], dtype=float)
        solutions.append({
            "iau_no": row[1].strip(' "'), "code": row[3].strip(' "'),
            "status": int(number(row[4]) or 0), "name": row[6].strip(' "'),
            "sol_start": number(row[8]), "sol_end": number(row[9]), "sol": float(sol),
            "ra": float(ra), "dec": float(dec), "dra": number(row[13]), "ddec": number(row[14]),
            "slon": float(circ_diff(float(slon), 0.0)), "beta": float(beta), "vg": float(vg),
            "orbit": orbit,
        })
    if len(solutions) < 1500:
        raise RuntimeError(f"Only {len(solutions)} IAU solutions parsed")
    return solutions
'''
source, count = re.subn(r"def parse_iau\(\) -> list\[dict\[str, Any\]\]:.*?(?=\ndef iau_match)", new_parse, source, count=1, flags=re.S)
if count != 1:
    raise SystemExit("Could not replace IAU parser")

new_match = r'''def iau_match(center: np.ndarray, medoid: np.ndarray, catalog: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_ra, candidate_dec = ecliptic_to_equatorial((center[3] + center[0]) % 360.0, center[1])
    best: dict[str, Any] | None = None
    for item in catalog:
        delta = float(circ_diff(center[3], item["sol"]))
        predicted_ra = (item["ra"] + (item["dra"] or 0.0) * delta) % 360.0
        predicted_dec = item["dec"] + (item["ddec"] or 0.0) * delta
        sky = angular_separation(candidate_ra, candidate_dec, predicted_ra, predicted_dec)
        speed_delta = abs(center[2] - item["vg"])
        radiant = math.sqrt((float(circ_diff(center[0], item["slon"])) / 4.0) ** 2
                            + ((center[1] - item["beta"]) / 4.0) ** 2
                            + (speed_delta / 3.0) ** 2)
        od = None if item["orbit"] is None else float(orbit_distance_matrix(medoid[None, :], item["orbit"][None, :])[0, 0])
        active = active_at(float(center[3]), item["sol_start"], item["sol_end"], item["sol"])
        orbit_ok = od is None or od <= 0.25
        matched = bool(active and speed_delta <= 6.0 and orbit_ok and (sky <= 5.0 or radiant <= 1.5))
        score = ((0.0 if active else 4.0) + (sky / 5.0) ** 2 + (speed_delta / 5.0) ** 2
                 + ((od / 0.20) ** 2 if od is not None else 1.0))
        candidate = {"matched": matched, "code": item["code"], "name": item["name"],
                     "status": item["status"], "active_at_candidate": active,
                     "solar_delta_from_mean": abs(delta), "sky_distance_with_drift": sky,
                     "speed_delta": speed_delta, "radiant_scaled_distance": radiant,
                     "orbit_d": od, "score": score}
        if best is None or score < best["score"]:
            best = candidate
    return best or {"matched": False}
'''
source, count = re.subn(r"def iau_match\(center: np\.ndarray, medoid: np\.ndarray, catalog: list\[dict\[str, Any\]\]\) -> dict\[str, Any\]:.*?(?=\ndef load_month)", new_match, source, count=1, flags=re.S)
if count != 1:
    raise SystemExit("Could not replace IAU matcher")

namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
