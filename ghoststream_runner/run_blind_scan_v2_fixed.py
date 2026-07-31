#!/usr/bin/env python3
"""Execute run_blind_scan_v2 with its day-value compatibility bug fixed."""
from pathlib import Path

path = Path(__file__).with_name("run_blind_scan_v2.py")
source = path.read_text()
old = 'day_values = pd.to_numeric(data["day"], errors="coerce").fillna(np.arange(len(data))).to_numpy(np.int64)'
new = 'day_series = pd.to_numeric(data["day"], errors="coerce"); day_values = np.where(np.isfinite(day_series.to_numpy(float)), day_series.to_numpy(float), np.arange(len(data), dtype=float)).astype(np.int64)'
if old not in source:
    raise SystemExit("Expected compatibility line not found")
source = source.replace(old, new)
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
