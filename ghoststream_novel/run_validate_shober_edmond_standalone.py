#!/usr/bin/env python3
"""Execute validate_shober_edmond with standalone orbit helpers."""
from pathlib import Path

path = Path(__file__).with_name("validate_shober_edmond.py")
source = path.read_text(encoding="utf-8")
old = "from validate_april_candidate import orbit_distance_matrix, orbit_summary"
new = "from orbit_helpers_standalone import orbit_distance_matrix, orbit_summary"
if old not in source:
    raise SystemExit("Expected GMN-dependent orbit import not found")
source = source.replace(old, new, 1)
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
