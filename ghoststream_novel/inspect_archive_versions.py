#!/usr/bin/env python3
import io
import re
import zipfile
import requests

URLS = {
    "sonotaco_2022_original": "https://www.astro.sk/iaumdcDB/public/data/SNMv3/022a.zip",
    "sonotaco_2024_original": "https://www.astro.sk/iaumdcDB/public/data/SNMv3/024a.zip",
    "sonotaco_2025_original": "https://www.astro.sk/iaumdcDB/public/data/SNMv3/025a.zip",
}

for name, url in URLS.items():
    print(f"\n=== {name} ===")
    r = requests.get(url, timeout=240)
    print("status", r.status_code, "bytes", len(r.content), "type", r.headers.get("content-type"))
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        print("names", z.namelist())
        member = next(x for x in z.namelist() if not x.endswith('/') and not x.startswith('__MACOSX/'))
        raw = z.read(member)
        print("member", member, "size", len(raw))
        print("\n".join(raw[:12000].decode("utf-8", errors="replace").splitlines()[:5]))

page = requests.get("https://meteornews.net/edmond/", timeout=120).text
print("\n=== EDMOND hrefs ===")
for href in sorted(set(re.findall(r'href=[\"\']([^\"\']*U2_202[234]_EDM\.zip[^\"\']*)', page, flags=re.I))):
    print(href)
print("all 2024 contexts")
for match in re.finditer(r'.{0,180}U2_2024_EDM\.zip.{0,180}', page, flags=re.I | re.S):
    print(re.sub(r'\s+', ' ', match.group(0)))
