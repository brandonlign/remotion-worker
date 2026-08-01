#!/usr/bin/env python3
"""Verify the recovered January–July 2026 GhostStream discovery matrix."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

EXPECTED_CENTER = [-149.297555, 7.45007, 37.42224, 36.901963]
EXPECTED_MONTHS = tuple(range(1, 8))
ROOT = Path("ghoststream_blind_2026")
OUT = Path("ghoststream_blind_rediscovery_evidence")


def circular_delta(left: float, right: float) -> float:
    return (left - right + 180.0) % 360.0 - 180.0


def center_distance(candidate: list[float]) -> float:
    deltas = [
        circular_delta(float(candidate[0]), EXPECTED_CENTER[0]) / 3.5,
        (float(candidate[1]) - EXPECTED_CENTER[1]) / 3.0,
        (float(candidate[2]) - EXPECTED_CENTER[2]) / 2.5,
        circular_delta(float(candidate[3]), EXPECTED_CENTER[3]) / 2.5,
    ]
    return math.sqrt(sum(value * value for value in deltas))


def main() -> int:
    monthly: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []
    iau_counts: list[int] = []
    for month in EXPECTED_MONTHS:
        key = f"2026-{month:02d}"
        path = ROOT / key / "ghoststream_novel_search.json"
        if not path.is_file():
            raise AssertionError(f"Missing {path}")
        result = json.loads(path.read_text())
        if result.get("discovery_year") != 2026:
            raise AssertionError(f"{key}: wrong discovery year {result.get('discovery_year')}")
        if result.get("validation_years") != [2025, 2024]:
            raise AssertionError(f"{key}: wrong validation years {result.get('validation_years')}")
        if int(result.get("iau_solutions_parsed", 0)) < 1500:
            raise AssertionError(f"{key}: incomplete IAU parse")
        iau_counts.append(int(result["iau_solutions_parsed"]))
        monthly[key] = {
            "verdict": result.get("verdict"),
            "prevalidation_candidates": result.get("prevalidation_candidates"),
            "validated_candidates": result.get("validated_candidates"),
            "survivors": result.get("survivors"),
            "month_record": result.get("months", {}).get(key),
        }
        for candidate in result.get("candidates", []):
            tagged = dict(candidate)
            tagged["source_output"] = key
            candidates.append(tagged)

    survivors = [item for item in candidates if item.get("novel_discovery_gate_passed") is True]
    april = [
        (center_distance(item["center"]), item)
        for item in survivors
        if int(item.get("month", -1)) == 4 and center_distance(item["center"]) <= 0.10
    ]
    if not april:
        raise AssertionError(
            "No matching April survivor: "
            + json.dumps([
                {"month": item.get("month"), "center": item.get("center"), "distance": center_distance(item["center"])}
                for item in survivors
            ])
        )
    april.sort(key=lambda pair: pair[0])
    distance, candidate = april[0]
    validation = candidate.get("validation", {})
    for year in ("2025", "2024"):
        item = validation.get(year)
        if item is None or item.get("passed") is not True:
            raise AssertionError(f"April candidate failed {year}: {item}")
        if int(item.get("members", 0)) < 8 or float(item.get("p", 1.0)) > 0.01:
            raise AssertionError(f"April candidate insufficient {year}: {item}")
    clones = candidate.get("clone_stability", {})
    if clones.get("passed") is not True or float(clones.get("pass_fraction", 0.0)) < 0.80:
        raise AssertionError(f"Clone failure: {clones}")
    if candidate.get("nearest_iau", {}).get("matched") is True:
        raise AssertionError(f"IAU match: {candidate.get('nearest_iau')}")
    additional = [
        {"month": item.get("month"), "cluster": item.get("cluster"), "center": item.get("center")}
        for item in survivors
        if item is not candidate and int(item.get("month", -1)) != 4
    ]
    if additional:
        raise AssertionError(f"Additional non-April survivors require review: {additional}")

    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {
        "status": "EXACT_2026_BLIND_REDISCOVERY",
        "source_commit": "39972b5fe0cf4d47092d3caa2b3ced12bedb065e",
        "entrypoint": "ghoststream_novel/run_month_year_v3.py",
        "months_scanned": list(EXPECTED_MONTHS),
        "validation_years": [2025, 2024],
        "iau_solutions_parsed_range": [min(iau_counts), max(iau_counts)],
        "month_summaries": monthly,
        "full_gate_survivors_across_matrix": len(survivors),
        "additional_non_april_survivors": additional,
        "april_survivor": {
            "cluster": candidate.get("cluster"),
            "discovery_members": candidate.get("members_2025"),
            "center": candidate.get("center"),
            "expected_center": EXPECTED_CENTER,
            "normalized_center_distance": distance,
            "sigma_raw": candidate.get("sigma_raw"),
            "orbit_medoid": candidate.get("orbit_medoid"),
            "orbit_median_d": candidate.get("orbit_median_d"),
            "orbit_q90_d": candidate.get("orbit_q90_d"),
            "orbit_null": candidate.get("orbit_null"),
            "validation": validation,
            "clone_stability": clones,
            "nearest_iau": candidate.get("nearest_iau"),
        },
    }
    (OUT / "blind_rediscovery.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    lines = [
        "# GhostStream January–July 2026 blind rediscovery", "",
        "**Verdict:** `EXACT_2026_BLIND_REDISCOVERY`", "",
        f"- Months scanned: **7**", 
        f"- Full-gate survivors: **{len(survivors)}**",
        f"- Additional non-April survivors: **{len(additional)}**",
        f"- April discovery members: **{candidate.get('members_2025')}**",
        f"- 2025 validation: **{validation['2025']['members']} members, p={validation['2025']['p']:.6g}**",
        f"- 2024 validation: **{validation['2024']['members']} members, p={validation['2024']['p']:.6g}**",
        f"- Clone pass fraction: **{clones['pass_fraction']:.3f}**",
        f"- IAU matched: **{candidate.get('nearest_iau', {}).get('matched')}**", "",
    ]
    (OUT / "BLIND_REDISCOVERY.md").write_text("\n".join(lines))
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
