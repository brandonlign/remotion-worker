#!/usr/bin/env python3
"""Uniform external-archive synthesis with the corrected zero speed drift.

This reruns the frozen GhostStream radiant/time template on:
- legacy CAMS,
- permanent SonotaCo annual catalogs,
- the MD5-verified Shober 2026 shower-removed EDMOND subset.

The bootstrap showed that geocentric-speed drift is unresolved, so dVg/dlambda
is fixed to zero for every archive. Orbit is never used to select members; it
is tested afterward against source- and time-matched null groups.

CAMS+SonotaCo remains the primary cross-network comparison. Adding Shober
EDMOND is explicitly exploratory because EDMOND is a compilation and may share
upstream contributing networks with other historical archives, even though no
exact UTC event overlaps the selected members.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact

import synthesize_independent_archives as synth
import validate_cams_legacy as cams
import validate_independent_catalogs_v2 as independent
import validate_shober_edmond as shober

OUT = Path("ghoststream_all_external_zero_speed")
MAX_ACTIVITY_P = 0.005
MAX_SHIFT_P = 0.05
MIN_MEMBERS = 8
MIN_YEARS = 4


def canonical_shober() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw, download = shober.download()
    data, preparation = shober.prepare(raw)
    sol = data["_sol"].to_numpy(float)
    node_raw = data["_node"].to_numpy(float)
    peri_raw = data["_peri"].to_numpy(float)
    node, peri, flipped = independent.normalize_node_peri(sol, node_raw, peri_raw)
    frame = pd.DataFrame({
        "sol": sol,
        "ecl_lon": data["_elng"].to_numpy(float),
        "beta": data["_elat"].to_numpy(float),
        "vg": data["_vg"].to_numpy(float),
        "e": data["_e"].to_numpy(float),
        "q": data["_q"].to_numpy(float),
        "inc": data["_incl"].to_numpy(float),
        "peri_norm": peri,
        "node": node,
        "id": data["_localtime"].astype(str).to_numpy(),
        "year": data["_Y_ut"].astype(int).to_numpy(),
        "source": "Shober-EDMOND",
    })
    frame["sunlon"] = synth.circ_diff(frame["ecl_lon"].to_numpy(float), frame["sol"].to_numpy(float))
    return frame, {
        "download": download,
        "preparation": preparation,
        "opposite_node_solutions_normalized": flipped,
    }


def event_key(row: pd.Series) -> str | None:
    source = str(row.get("source", ""))
    if source == "CAMS" and pd.notna(row.get("datetime")):
        timestamp = pd.to_datetime(row["datetime"], utc=True, errors="coerce")
        if pd.notna(timestamp):
            return timestamp.strftime("%Y%m%d%H%M%S")
    text = str(row.get("id", ""))
    digits = re.sub(r"\D", "", text)
    return digits[:14] if len(digits) >= 14 else None


def cross_source_overlap(members: pd.DataFrame) -> dict[str, Any]:
    audit = members.copy()
    audit["event_key"] = audit.apply(event_key, axis=1)
    audit = audit.loc[audit["event_key"].notna()].copy()
    groups = []
    for key, group in audit.groupby("event_key"):
        sources = sorted(set(group["source"].astype(str)))
        if len(sources) > 1:
            groups.append({
                "event_key": key,
                "sources": sources,
                "rows": int(len(group)),
                "ids": group["id"].astype(str).tolist(),
            })
    return {
        "keys_checked": int(audit["event_key"].nunique()),
        "cross_source_duplicate_groups": groups,
        "cross_source_duplicate_count": int(len(groups)),
    }


def evidence_block(frames: list[tuple[pd.DataFrame, dict[str, np.ndarray]]]) -> tuple[dict[str, Any], pd.DataFrame]:
    tables = [synth.activity_counts(frame, masks) for frame, masks in frames]
    table = np.sum(tables, axis=0)
    odds, activity_p = fisher_exact(table.tolist(), alternative="greater")
    shift = synth.shifted_test(frames)
    orbit, members = synth.pooled_orbit_test(frames)
    active_years = sorted(set(int(year) for year in members["year"].tolist()))
    member_counts = {
        f"{source}-{int(year)}": int(count)
        for (source, year), count in members.groupby(["source", "year"]).size().items()
    }
    passed = bool(
        len(members) >= MIN_MEMBERS
        and len(active_years) >= MIN_YEARS
        and activity_p <= MAX_ACTIVITY_P
        and shift["empirical_p"] <= MAX_SHIFT_P
        and orbit.get("passed", False)
    )
    return {
        "activity_tables_by_frame": tables,
        "pooled_activity_table": table,
        "activity_odds_ratio": float(odds),
        "activity_p": float(activity_p),
        "shifted_windows": shift,
        "orbit": orbit,
        "members": int(len(members)),
        "active_years": active_years,
        "member_counts": member_counts,
        "passed": passed,
    }, members


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

    # Correct the template globally before any archive is selected.
    cams.VG_SLOPE = 0.0

    print("Loading legacy CAMS...", flush=True)
    cams_frame = cams.parse_catalog().copy()
    cams_frame["source"] = "CAMS"

    print("Loading permanent SonotaCo catalogs...", flush=True)
    son_frame, son_meta = synth.canonical_sonotaco()

    print("Loading MD5-verified Shober EDMOND subset...", flush=True)
    shober_frame, shober_meta = canonical_shober()

    cams_masks = synth.common_masks(cams_frame)
    son_masks = synth.common_masks(son_frame)
    shober_masks = synth.common_masks(shober_frame)

    primary, primary_members = evidence_block([
        (cams_frame, cams_masks),
        (son_frame, son_masks),
    ])
    extended, extended_members = evidence_block([
        (cams_frame, cams_masks),
        (son_frame, son_masks),
        (shober_frame, shober_masks),
    ])
    overlap = cross_source_overlap(extended_members)

    member_columns = [
        "source", "year", "id", "sol", "sunlon", "beta", "vg",
        "e", "q", "inc", "peri_norm", "node",
    ]
    extended_members[member_columns].sort_values(["source", "year", "sol"]).to_csv(
        OUT / "all_external_members_zero_speed.csv", index=False
    )

    stable = bool(primary["passed"] and extended["passed"] and overlap["cross_source_duplicate_count"] == 0)
    verdict = (
        "EXTERNAL_EVIDENCE_STABLE_WITH_ZERO_SPEED_DRIFT_AND_EDMOND_EXTENSION"
        if stable else "EXTERNAL_EVIDENCE_NOT_STABLE_UNDER_UNIFORM_REANALYSIS"
    )
    payload = {
        "stage": "uniform_zero_speed_drift_external_archive_synthesis",
        "verdict": verdict,
        "passed": stable,
        "template": {
            "speed_drift_km_s_per_solar_longitude_degree": 0.0,
            "all_other_centers_widths_activity_bounds_and_orbit_rules": "unchanged from frozen GMN solution",
            "orbit_used_for_member_selection": False,
        },
        "primary_cross_network": {
            "archives": ["CAMS", "SonotaCo"],
            **primary,
        },
        "extended_exploratory": {
            "archives": ["CAMS", "SonotaCo", "Shober-EDMOND"],
            **extended,
            "warning": (
                "The EDMOND subset is a compiled historical archive and may share upstream networks "
                "with other catalogs. The exact selected events do not overlap, but the three archive "
                "labels must not be treated as three fully independent instruments."
            ),
        },
        "cross_source_overlap": overlap,
        "sonotaco_metadata": son_meta,
        "shober_edmond_metadata": shober_meta,
        "rules": {
            "minimum_members": MIN_MEMBERS,
            "minimum_years": MIN_YEARS,
            "maximum_activity_p": MAX_ACTIVITY_P,
            "maximum_shifted_window_p": MAX_SHIFT_P,
            "maximum_orbit_null_p": synth.MAX_ORBIT_NULL_P,
        },
    }
    (OUT / "all_external_zero_speed.json").write_text(
        json.dumps(jsonable(payload), indent=2) + "\n"
    )

    lines = [
        "# Uniform zero-speed-drift external archive synthesis", "",
        f"**Verdict:** `{verdict}`", "",
        "The clustered bootstrap did not resolve a geocentric-speed drift, so every external archive was rerun with dVg/dλ⊙ = 0. All other template parameters remained frozen.", "",
        "## Primary cross-network evidence: CAMS + SonotaCo", "",
        f"- Members: **{primary['members']}**",
        f"- Years: **{primary['active_years']}**",
        f"- Activity p: **{primary['activity_p']:.8g}**",
        f"- Shifted-window p: **{primary['shifted_windows']['empirical_p']:.8g}**",
        f"- Median orbital D: **{primary['orbit']['observed']['median_d']:.6f}**",
        f"- Orbit-null p: **{primary['orbit']['null_p']}**",
        f"- Frozen family gate: **{primary['passed']}**", "",
        "## Extended exploratory evidence: + Shober EDMOND", "",
        f"- Members: **{extended['members']}**",
        f"- Years: **{extended['active_years']}**",
        f"- Counts: `{extended['member_counts']}`",
        f"- Activity p: **{extended['activity_p']:.8g}**",
        f"- Shifted-window p: **{extended['shifted_windows']['empirical_p']:.8g}**",
        f"- Median orbital D: **{extended['orbit']['observed']['median_d']:.6f}**",
        f"- Orbit q90 D: **{extended['orbit']['observed']['q90_d']:.6f}**",
        f"- Orbit-null p: **{extended['orbit']['null_p']}**",
        f"- Medoid distance to refined GMN orbit: **{extended['orbit']['distance_to_gmn_refined_orbit']:.6f}**",
        f"- Exact cross-source duplicate groups: **{overlap['cross_source_duplicate_count']}**", "",
        "The extended result is supporting, explicitly post-hoc evidence. EDMOND may share upstream network provenance with other historical compilations even though none of the selected UTC events overlap.", "",
    ]
    (OUT / "ALL_EXTERNAL_ZERO_SPEED.md").write_text("\n".join(lines))

    print(f"Verdict: {verdict}")
    print(f"Primary: N={primary['members']} p={primary['activity_p']} shift={primary['shifted_windows']['empirical_p']} orbit_p={primary['orbit']['null_p']}")
    print(f"Extended: N={extended['members']} p={extended['activity_p']} shift={extended['shifted_windows']['empirical_p']} orbit_p={extended['orbit']['null_p']}")
    print(f"Cross-source duplicates: {overlap['cross_source_duplicate_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
