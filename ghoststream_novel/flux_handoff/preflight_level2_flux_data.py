#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

FTP_PATTERNS = ("FTPdetectinfo*.txt", "FTPdetectinfo*.txt.bz2")
CONFIG_PATTERNS = ("*.config", ".config", "dfnstation.cfg")
PLATEPAR_PATTERNS = ("platepar_cmn2010.cal", "platepars_all_recalibrated.json", "platepars_flux_recalibrated.json")
CALSTARS_PATTERNS = ("CALSTARS*.txt", "CALSTARS*.txt.bz2")
FF_PATTERNS = ("FF*.fits", "FF*.bin", "FF*.fits.bz2", "FF*.bin.bz2")
MASK_PATTERNS = ("mask.bmp", "mask.png", "mask_latest.bmp")
TIME_INTERVAL_PATTERNS = ("flux_time_intervals.json", "*time_intervals*.json")
SENSOR_PATTERNS = ("flux_sensor_characterization.json", "*sensor_characterization*.json")
COLLECTION_PATTERNS = ("*collection_area*.json", "*collecting_area*.json", "*flux_fixed_bins*.ecsv", "*flux_fixed_bins*.csv")


def files_matching(directory: Path, patterns: Iterable[str]) -> list[str]:
    found: set[str] = set()
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                found.add(path.name)
    return sorted(found)


def discover_nights(root: Path) -> list[Path]:
    nights: set[Path] = set()
    for pattern in FTP_PATTERNS:
        for path in root.rglob(pattern):
            if path.is_file():
                nights.add(path.parent)
    return sorted(nights)


def audit_night(directory: Path) -> dict[str, object]:
    groups = {
        "ftpdetectinfo": files_matching(directory, FTP_PATTERNS),
        "config": files_matching(directory, CONFIG_PATTERNS),
        "platepar": files_matching(directory, PLATEPAR_PATTERNS),
        "calstars": files_matching(directory, CALSTARS_PATTERNS),
        "ff": files_matching(directory, FF_PATTERNS),
        "mask": files_matching(directory, MASK_PATTERNS),
        "time_intervals": files_matching(directory, TIME_INTERVAL_PATTERNS),
        "sensor_characterization": files_matching(directory, SENSOR_PATTERNS),
        "collection_area_or_fixed_bins": files_matching(directory, COLLECTION_PATTERNS),
    }
    base = bool(groups["ftpdetectinfo"] and groups["config"] and groups["platepar"] and groups["mask"])
    raw_ready = bool(base and groups["calstars"] and groups["ff"])
    metadata_ready = bool(base and groups["time_intervals"] and groups["sensor_characterization"] and groups["collection_area_or_fixed_bins"])
    status = "READY_RAW_RECOMPUTE" if raw_ready else "READY_PRECOMPUTED_METADATA" if metadata_ready else "INCOMPLETE"
    missing = []
    if not groups["ftpdetectinfo"]: missing.append("FTPdetectinfo")
    if not groups["config"]: missing.append("station config")
    if not groups["platepar"]: missing.append("platepar/recalibrated platepars")
    if not groups["mask"]: missing.append("mask")
    if not raw_ready and not metadata_ready:
        missing.append("either CALSTARS+FF raw calibration inputs or complete precomputed flux metadata")
    station_hint = directory.name.split("_")[0] if "_" in directory.name else directory.name
    return {"directory": str(directory.resolve()), "station_hint": station_hint, "status": status, "missing": missing, "files": groups}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.root.is_dir(): raise NotADirectoryError(args.root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audits = [audit_night(path) for path in discover_nights(args.root)]
    counts: dict[str, int] = {}
    for item in audits: counts[item["status"]] = counts.get(item["status"], 0) + 1
    payload = {"root": str(args.root.resolve()), "night_directories_found": len(audits), "status_counts": counts, "audits": audits}
    (args.output_dir / "level2_flux_preflight.json").write_text(json.dumps(payload, indent=2) + "\n")
    with (args.output_dir / "level2_flux_preflight.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["directory", "station_hint", "status", "missing"])
        writer.writeheader()
        for item in audits:
            writer.writerow({"directory": item["directory"], "station_hint": item["station_hint"], "status": item["status"], "missing": "; ".join(item["missing"])})
    print(json.dumps({"night_directories_found": len(audits), "status_counts": counts}, indent=2))
    return 0 if audits and counts.get("INCOMPLETE", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
