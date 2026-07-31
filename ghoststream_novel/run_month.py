#!/usr/bin/env python3
"""Run one frozen month of the all-season GhostStream search."""
import os
from pathlib import Path

month = int(os.environ["GHOSTSTREAM_MONTH"])
if month < 1 or month > 12:
    raise SystemExit(f"Invalid GHOSTSTREAM_MONTH={month}")
path = Path(__file__).with_name("run_novel_search_fixed.py")
base_path = Path(__file__).with_name("run_novel_search.py")
source = path.read_text()
# The fixed wrapper reads and executes the base script. Point it to a temporary
# month-specific copy whose only scientific change is the frozen month subset.
base = base_path.read_text()
old = "MONTHS = tuple(range(1, 13))"
new = f"MONTHS = ({month},)"
if old not in base:
    raise SystemExit("Expected MONTHS declaration not found")
month_base = Path(__file__).with_name(f"run_novel_search_month_{month:02d}.py")
month_base.write_text(base.replace(old, new))
source = source.replace('path = Path(__file__).with_name("run_novel_search.py")',
                        f'path = Path(__file__).with_name("run_novel_search_month_{month:02d}.py")')
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
