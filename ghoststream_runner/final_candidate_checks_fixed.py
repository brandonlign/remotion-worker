#!/usr/bin/env python3
"""Execute final_candidate_checks with its missing deterministic seed fixed."""
from pathlib import Path

path = Path(__file__).with_name("final_candidate_checks.py")
source = path.read_text()
needle = 'IAU_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamfulldata2026.txt"\n'
if needle not in source:
    raise SystemExit("Expected IAU_URL line not found")
source = source.replace(needle, needle + "SEED = 20260731\n", 1)
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
