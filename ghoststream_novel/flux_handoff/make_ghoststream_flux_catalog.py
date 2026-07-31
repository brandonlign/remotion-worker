#!/usr/bin/env python3
"""Create an RMS flux_shower catalogue containing the GhostStream candidate.

The script does not compute flux. It prepares a reproducible custom shower entry
for a consented/internal GMN Level 2 run. The user must supply a mass index;
there is deliberately no scientific default.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SOL_BEGIN = 35.902
SOL_REFERENCE = 38.652
SOL_END = 39.902
RA_REFERENCE = 248.502564
DRA = 0.887078
DEC_REFERENCE = -14.579393
DDEC = -0.157506
VG_REFERENCE = 37.573416
DVG = -0.029349
ASSOCIATION_RADIUS = 3.0
INTERNAL_IAU_NUMBER = 0
INTERNAL_CODE = "GSA"
FULL_NAME = "GhostStream April candidate"

BINNING = {
    "all_years": {"min_tap": 30, "min_meteors": 20, "min_bin_duration": 6, "max_bin_duration": 48},
    "yearly": {"min_tap": 10, "min_meteors": 8, "min_bin_duration": 6, "max_bin_duration": 48},
}


def population_index(mass_index: float) -> float:
    return 10.0 ** ((mass_index - 1.0) / 2.5)


def make_entry(mass_index: float) -> str:
    r = population_index(mass_index)
    fields = [
        f"{INTERNAL_IAU_NUMBER:5d}", f"{INTERNAL_CODE:<4s}", f"{FULL_NAME:<33s}",
        f"{SOL_BEGIN:.3f}", f"{SOL_REFERENCE:.3f}", f"{SOL_END:.3f}",
        f"{RA_REFERENCE:.6f}", f"{DRA:.6f}", f"{DEC_REFERENCE:.6f}", f"{DDEC:.6f}",
        f"{VG_REFERENCE:.6f}", f"{DVG:.6f}", "annual", f"{SOL_REFERENCE:.3f}",
        "1.0", "0.0", "0.0", f"{r:.8f}", "0.0", f"{ASSOCIATION_RADIUS:.2f}", repr(BINNING),
    ]
    return "|".join(fields)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rms-root", type=Path, required=True)
    parser.add_argument("--mass-index", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1.2 <= args.mass_index <= 3.0:
        raise ValueError("Mass index is outside the broad physically plausible range 1.2-3.0")
    official = args.rms_root / "share" / "flux_showers.csv"
    if not official.is_file():
        raise FileNotFoundError(f"Official RMS flux shower table not found: {official}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "flux_showers_ghoststream.csv"
    text = official.read_text(encoding="utf-8").rstrip() + "\n"
    text += "# Internal candidate entry below. GSA is not an official IAU code.\n"
    text += make_entry(args.mass_index) + "\n"
    output.write_text(text, encoding="utf-8")
    metadata = {
        "official_source": str(official.resolve()), "output": str(output.resolve()),
        "mass_index": args.mass_index, "population_index": population_index(args.mass_index),
        "internal_code": INTERNAL_CODE, "official_iau_status": "unassigned_candidate",
        "activity_bounds_solar_longitude_deg": [SOL_BEGIN, SOL_END],
        "reference_solar_longitude_deg": SOL_REFERENCE,
        "radiant_at_reference": {
            "ra_deg": RA_REFERENCE, "dec_deg": DEC_REFERENCE, "vg_km_s": VG_REFERENCE,
            "dra_deg_per_deg_solar_longitude": DRA,
            "ddec_deg_per_deg_solar_longitude": DDEC,
            "dvg_km_s_per_deg_solar_longitude": DVG,
        },
        "association_radius_deg": ASSOCIATION_RADIUS,
        "warning": "ZHR/activity-shape fields are operational placeholders; use explicit bounds and calibrated TAP.",
    }
    (args.output_dir / "ghoststream_flux_catalog_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(output)
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
