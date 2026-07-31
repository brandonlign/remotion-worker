#!/usr/bin/env python3
"""Download small samples of independent orbit archives and print schemas."""
import io
import zipfile
import requests

URLS = {
    "sonotaco_2022": "https://ceres.ta3.sk/iaumdcdb/dataDBs/video_offline/iaumdcSNMv3_S22.csv.zip",
    "edmond_2022": "https://meteornews.net/assets/2025-03-29-edmond-database/U2_2022_EDM.zip",
}

for name, url in URLS.items():
    print(f"\n=== {name} ===", flush=True)
    response = requests.get(url, timeout=180)
    print("status", response.status_code, "bytes", len(response.content), "type", response.headers.get("content-type"), flush=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        print("files", archive.namelist(), flush=True)
        for member in archive.namelist()[:3]:
            if member.endswith("/"):
                continue
            raw = archive.read(member)
            print("member", member, "bytes", len(raw), flush=True)
            text = raw[:8000].decode("utf-8", errors="replace")
            print("first lines:")
            print("\n".join(text.splitlines()[:8]))
