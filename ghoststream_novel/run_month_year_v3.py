#!/usr/bin/env python3
"""Run the drift-aware blind scanner for an arbitrary discovery year/month."""
import os
from pathlib import Path

year = int(os.environ["GHOSTSTREAM_YEAR"])
month = int(os.environ["GHOSTSTREAM_MONTH"])
if year < 2019 or year > 2030 or month < 1 or month > 12:
    raise SystemExit(f"Invalid year/month: {year}-{month:02d}")

wrapper_path = Path(__file__).with_name("run_month_v2.py")
wrapper = wrapper_path.read_text()
old_month = 'month = int(os.environ["GHOSTSTREAM_MONTH"])\n'
new_month = old_month + 'year = int(os.environ["GHOSTSTREAM_YEAR"])\n'
if old_month not in wrapper:
    raise SystemExit("Could not locate month declaration in v2 wrapper")
wrapper = wrapper.replace(old_month, new_month, 1)
old_replace = 'source = source.replace("MONTHS = tuple(range(1, 13))", f"MONTHS = ({month},)")'
new_replace = '''source = source.replace("MONTHS = tuple(range(1, 13))", f"MONTHS = ({month},)")
source = source.replace("DISCOVERY_YEAR = 2025", f"DISCOVERY_YEAR = {year}")
source = source.replace("VALIDATION_YEARS = (2024, 2023)", f"VALIDATION_YEARS = ({year - 1}, {year - 2})")
source = source.replace("if year == 2025 and before > MAX_SPORADIC:", f"if year == {year} and before > MAX_SPORADIC:")
source = source.replace('f"2025-{{month:02d}}', f'f"{year}-{{month:02d}}')
source = source.replace('["validation"]["2024"]', f'["validation"]["{year - 1}"]')
source = source.replace('["validation"]["2023"]', f'["validation"]["{year - 2}"]')
source = source.replace('"rep2024"', f'"rep{year - 1}"')
source = source.replace('"p2024"', f'"p{year - 1}"')
source = source.replace('"rep2023"', f'"rep{year - 2}"')
source = source.replace('"p2023"', f'"p{year - 2}"')
source = source.replace('f"- 2024: n=', f'f"- {year - 1}: n=')
source = source.replace('f"- 2023: n=', f'f"- {year - 2}: n=')
'''
if old_replace not in wrapper:
    raise SystemExit("Could not locate source-patch declaration in v2 wrapper")
wrapper = wrapper.replace(old_replace, new_replace, 1)
namespace = {"__name__": "__main__", "__file__": str(wrapper_path)}
exec(compile(wrapper, str(wrapper_path), "exec"), namespace)
