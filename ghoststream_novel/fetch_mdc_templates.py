#!/usr/bin/env python3
"""Fetch the current IAU MDC shower mean and lookup-table templates."""
from pathlib import Path
import requests

OUT = Path("ghoststream_mdc_templates")
OUT.mkdir(exist_ok=True)
URLS = {
    "template-mean-data.txt": "https://ceresiaumdc.ta3.sk/downloads/templates_data/template-mean-data.txt",
    "template-LUtable.csv": "https://ceresiaumdc.ta3.sk/downloads/templates_data/template-LUtable.csv",
}

for filename, url in URLS.items():
    response = requests.get(url, timeout=120)
    print(filename, response.status_code, len(response.content), response.headers.get("content-type"), flush=True)
    response.raise_for_status()
    (OUT / filename).write_bytes(response.content)
    print(response.text[:12000], flush=True)
