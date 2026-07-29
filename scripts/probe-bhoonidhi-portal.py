#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

OUT = Path(sys.argv[1])
RAW = OUT / "raw" / "bhoonidhi_downloader_source"
RAW.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "BlindSlope-Pilot/0.5", "Accept": "application/json,text/plain,*/*"}


def fetch(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 45):
    h = dict(HEADERS)
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "url": r.geturl(), "headers": dict(r.headers), "body": r.read(), "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "url": e.geturl(), "headers": dict(e.headers), "body": e.read(), "error": None}
    except Exception as e:
        return {"status": None, "url": url, "headers": {}, "body": b"", "error": f"{type(e).__name__}: {e}"}


report: dict = {"package": {}, "source_hints": [], "url_probes": [], "portal_asset_probes": []}
meta = fetch("https://pypi.org/pypi/bhoonidhi-downloader/json")
if meta["status"] == 200:
    payload = json.loads(meta["body"])
    files = payload.get("urls", [])
    wheel = next((x for x in files if str(x.get("filename", "")).endswith(".whl")), None)
    report["package"] = {"version": payload.get("info", {}).get("version"), "wheel": wheel.get("url") if wheel else None}
    if wheel:
        wr = fetch(wheel["url"], timeout=60)
        if wr["status"] == 200:
            z = zipfile.ZipFile(io.BytesIO(wr["body"]))
            py_names = [n for n in z.namelist() if n.endswith(".py")]
            for name in py_names:
                text = z.read(name).decode("utf-8", "replace")
                path = RAW / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                for number, line in enumerate(text.splitlines(), 1):
                    low = line.lower()
                    if any(k in low for k in ["http", "request", "endpoint", "bhoonidhi", "search", "archive"]):
                        if len(report["source_hints"]) < 500:
                            report["source_hints"].append({"file": name, "line": number, "text": line.strip()[:500]})
            urls = sorted(set(re.findall(r"https?://[^\s'\"<>]+", "\n".join((RAW / n).read_text() for n in py_names))))
            for url in urls:
                if "bhoonidhi" not in url.lower() and "nrsc.gov.in" not in url.lower():
                    continue
                clean = url.rstrip(").,;]}")
                r = fetch(clean, timeout=25)
                report["url_probes"].append({"url": clean, "status": r["status"], "final_url": r["url"], "error": r["error"], "body_prefix": r["body"][:500].decode("utf-8", "replace")})
        else:
            report["package"]["wheel_error"] = {"status": wr["status"], "error": wr["error"]}
else:
    report["package"]["metadata_error"] = {"status": meta["status"], "error": meta["error"]}

# Probe likely assets from the public single-page application. JavaScript bundles often reveal
# the anonymous catalogue endpoint even where the HTML does not.
index = fetch("https://bhoonidhi.nrsc.gov.in/bhoonidhi/index.html", timeout=45)
html = index["body"].decode("utf-8", "replace")
(OUT / "raw" / "bhoonidhi_index.html").write_text(html)
assets = re.findall(r"(?:src|href)=[\"']([^\"']+\.(?:js|json)(?:\?[^\"']*)?)[\"']", html, flags=re.I)
for asset in assets:
    url = urllib.parse.urljoin(index["url"], asset)
    r = fetch(url, timeout=45)
    record = {"url": url, "status": r["status"], "error": r["error"], "bytes": len(r["body"])}
    if r["status"] == 200 and len(r["body"]) <= 20_000_000:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
        (OUT / "raw" / f"portal_asset_{safe}").write_bytes(r["body"])
        text = r["body"].decode("utf-8", "replace")
        hits = []
        for pat in [r"https?://[^\s'\"<>]+", r"/[A-Za-z0-9_.-]*(?:search|catalog|archive|query|product)[A-Za-z0-9_./?=&-]*"]:
            hits.extend(re.findall(pat, text, flags=re.I))
        record["endpoint_hints"] = sorted(set(x[:500] for x in hits if "mapbox" not in x.lower()))[:300]
    report["portal_asset_probes"].append(record)

(OUT / "portal_probe.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(report, indent=2, sort_keys=True))
