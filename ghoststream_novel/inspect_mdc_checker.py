#!/usr/bin/env python3
import io
import os
import zipfile
import requests

url = "https://ceresiaumdc.ta3.sk/downloads/source_programs/checking_program.zip"
r = requests.get(url, timeout=120)
print("download", r.status_code, len(r.content), r.headers.get("content-type"))
r.raise_for_status()
with zipfile.ZipFile(io.BytesIO(r.content)) as z:
    print("members")
    for n in z.namelist():
        print(n)
    z.extractall("mdc_checker")

print("\ntext previews")
for root, _, files in os.walk("mdc_checker"):
    for name in files:
        path = os.path.join(root, name)
        print("\n###", path, os.path.getsize(path))
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read(20000)
            print(text)
        except Exception as exc:
            print("binary/unreadable", exc)
