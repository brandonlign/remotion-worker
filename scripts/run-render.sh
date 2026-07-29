#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: run-render.sh <request.json> <private-source-dir> <output-dir>" >&2
  exit 64
fi

REQUEST_FILE="$1"
SOURCE_DIR="$2"
OUTPUT_DIR="$3"
mkdir -p "$OUTPUT_DIR/raw"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

python3 - "$OUTPUT_DIR" <<'PY'
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT = Path(sys.argv[1])
RAW = OUT / "raw"
AOI = [88.55, 27.25, 88.72, 27.40]
START = "2026-06-17T00:00:00Z"
END = "2026-07-30T00:00:00Z"
CMR = "https://cmr.earthdata.nasa.gov/search"
BHO = "https://bhoonidhi-api.nrsc.gov.in"
COLLECTIONS = [
    "NISAR_L2_GUNW_PROVISIONAL_V1",
    "NISAR_L1_RIFG_PROVISIONAL_V1",
    "NISAR_L2_GSLC_PROVISIONAL_V1",
    "NISAR_L2_GCOV_PROVISIONAL_V1",
]
HEADERS = {
    "User-Agent": "BlindSlope-Pilot/0.4",
    "Client-Id": "BlindSlope-Pilot",
    "Accept": "application/json",
}


def request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None):
    h = dict(HEADERS)
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.geturl(), dict(r.headers), r.read(), None
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), dict(e.headers), e.read(), None
    except Exception as e:
        return None, url, {}, b"", f"{type(e).__name__}: {e}"


def bbox_from_umm(umm: dict[str, Any]):
    geom = umm.get("SpatialExtent", {}).get("HorizontalSpatialDomain", {}).get("Geometry", {})
    pts = []
    for poly in geom.get("GPolygons", []) or []:
        for p in poly.get("Boundary", {}).get("Points", []) or []:
            try:
                pts.append((float(p["Longitude"]), float(p["Latitude"])))
            except Exception:
                pass
    if not pts:
        return None
    return [min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts)]


def parse_name(name: str):
    clean = name.rsplit(".", 1)[0]
    parts = clean.split("_")
    parsed: dict[str, Any] = {
        "timestamps_in_name": re.findall(r"20\d{6}T\d{6}", name),
        "name_parts": parts,
    }
    # NISAR filenames consistently place cycle/track/direction/frame before timestamps.
    for i, token in enumerate(parts):
        if token in {"A", "D"} and i >= 2:
            parsed["direction"] = token
            parsed["track_candidate"] = parts[i - 1]
            parsed["cycle_candidate"] = parts[i - 2]
            if i + 1 < len(parts):
                parsed["frame_candidate"] = parts[i + 1]
            break
    return parsed


def related_urls(umm: dict[str, Any]):
    out = []
    for u in umm.get("RelatedUrls", []) or []:
        url = u.get("URL")
        if url:
            out.append({"url": url, "type": u.get("Type"), "subtype": u.get("Subtype")})
    return out


rows: list[dict[str, Any]] = []
collection_summary: dict[str, Any] = {}
for short in COLLECTIONS:
    cq = urllib.parse.urlencode({"short_name": short, "page_size": 20})
    cstatus, curl, cheaders, cbody, cerr = request(f"{CMR}/collections.umm_json?{cq}")
    (RAW / f"collection_{short}.json").write_bytes(cbody)
    if cerr or cstatus != 200:
        collection_summary[short] = {"collection_status": cstatus, "error": cerr, "count": -1}
        continue
    cpayload = json.loads(cbody)
    citems = cpayload.get("items", [])
    asf = [x for x in citems if x.get("meta", {}).get("provider-id") == "ASF"]
    citem = (asf or citems)[0] if citems else None
    if not citem:
        collection_summary[short] = {"collection_status": cstatus, "count": 0, "error": "collection missing"}
        continue
    cid = citem["meta"]["concept-id"]
    params = {
        "concept_id": cid,
        "bounding_box": ",".join(map(str, AOI)),
        "temporal": f"{START},{END}",
        "page_size": 2000,
        "sort_key[]": "start_date",
    }
    gstatus, gurl, gheaders, gbody, gerr = request(f"{CMR}/granules.umm_json?{urllib.parse.urlencode(params)}")
    (RAW / f"granules_{short}.json").write_bytes(gbody)
    if gerr or gstatus != 200:
        collection_summary[short] = {"concept_id": cid, "granule_status": gstatus, "error": gerr, "count": -1}
        continue
    gpayload = json.loads(gbody)
    granules = gpayload.get("items", [])
    collection_summary[short] = {
        "concept_id": cid,
        "granule_status": gstatus,
        "cmr_hits": int(gheaders.get("CMR-Hits", "-1")),
        "count": len(granules),
    }
    for item in granules:
        meta = item.get("meta", {})
        umm = item.get("umm", {})
        temporal = umm.get("TemporalExtent", {}).get("RangeDateTime", {})
        name = str(umm.get("GranuleUR") or meta.get("native-id") or meta.get("concept-id"))
        parsed = parse_name(name)
        rows.append({
            "collection": short,
            "concept_id": meta.get("concept-id"),
            "granule_id": name,
            "start_time": temporal.get("BeginningDateTime"),
            "end_time": temporal.get("EndingDateTime"),
            "bbox": bbox_from_umm(umm),
            "direction": parsed.get("direction"),
            "cycle_candidate": parsed.get("cycle_candidate"),
            "track_candidate": parsed.get("track_candidate"),
            "frame_candidate": parsed.get("frame_candidate"),
            "timestamps_in_name": parsed.get("timestamps_in_name"),
            "related_urls": related_urls(umm),
        })

csv_fields = [
    "collection", "concept_id", "granule_id", "start_time", "end_time", "bbox",
    "direction", "cycle_candidate", "track_candidate", "frame_candidate",
    "timestamps_in_name", "related_urls",
]
with (OUT / "l_band_granules.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=csv_fields)
    w.writeheader()
    for row in rows:
        w.writerow({k: json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v for k, v in row.items()})

# Probe S-band catalogue exactly as documented, without credentials. Authentication failure is
# an observed access result and is never interpreted as evidence that no S-band scenes exist.
s_payload = json.dumps({
    "collections": ["NISAR_SSAR_GUNW"],
    "bbox": AOI,
    "datetime": "2026-07-08T00:00:00Z/2026-07-30T00:00:00Z",
    "limit": 500,
}).encode()
sstatus, surl, sheaders, sbody, serr = request(
    f"{BHO}/data/search", s_payload, {"Content-Type": "application/json"}
)
(RAW / "bhoonidhi_gunw_response.txt").write_bytes(sbody)

s_feature_count = None
if sstatus == 200:
    try:
        sjson = json.loads(sbody)
        (RAW / "bhoonidhi_gunw_response.json").write_text(json.dumps(sjson, indent=2) + "\n")
        s_feature_count = len(sjson.get("features", []) or [])
    except Exception:
        pass

gunw_rows = [r for r in rows if r["collection"] == "NISAR_L2_GUNW_PROVISIONAL_V1"]
rifg_rows = [r for r in rows if r["collection"] == "NISAR_L1_RIFG_PROVISIONAL_V1"]
gslc_rows = [r for r in rows if r["collection"] == "NISAR_L2_GSLC_PROVISIONAL_V1"]
dates = sorted({str(r["start_time"])[:10] for r in rows if r.get("start_time")})
tracks = sorted({str(r["track_candidate"]) for r in rows if r.get("track_candidate")})
frames = sorted({str(r["frame_candidate"]) for r in rows if r.get("frame_candidate")})
directions = sorted({str(r["direction"]) for r in rows if r.get("direction")})

l_interferometric_gate = len(gunw_rows) >= 2 or len(rifg_rows) >= 2
l_raw_gate = len(gslc_rows) >= 3
s_catalog_gate = sstatus == 200 and bool(s_feature_count)
if l_interferometric_gate and s_catalog_gate:
    verdict = "MATCHED_CATALOG_GATE_PASS"
elif l_interferometric_gate and sstatus in {401, 403}:
    verdict = "L_GATE_PASS_S_BAND_AUTH_BLOCKED"
elif l_interferometric_gate:
    verdict = "L_GATE_PASS_S_BAND_UNRESOLVED"
else:
    verdict = "INSUFFICIENT_L_BAND_COVERAGE"

summary = {
    "pilot": "BlindSlope",
    "stage": "real_catalog_and_access_gate",
    "executed_at": datetime.now(timezone.utc).isoformat(),
    "synthetic_data_used": False,
    "aoi_bbox": AOI,
    "time_range": [START, END],
    "collections": collection_summary,
    "l_band_total": len(rows),
    "l_gunw_count": len(gunw_rows),
    "l_rifg_count": len(rifg_rows),
    "l_gslc_count": len(gslc_rows),
    "l_acquisition_dates": dates,
    "track_candidates": tracks,
    "frame_candidates": frames,
    "directions": directions,
    "s_band_http_status": sstatus,
    "s_band_error": serr,
    "s_band_feature_count": s_feature_count,
    "s_band_body_prefix": sbody[:1500].decode("utf-8", "replace"),
    "gates": {
        "l_interferometric_products": l_interferometric_gate,
        "l_three_or_more_slc_products": l_raw_gate,
        "s_catalog_results": s_catalog_gate,
        "matched_l_s_catalog": bool(l_interferometric_gate and s_catalog_gate),
    },
    "verdict": verdict,
    "interpretation": "A 401/403 S-band response is an access failure, not absence of coverage.",
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
(OUT / "REPORT.md").write_text(
    "# BlindSlope executed catalogue pilot\n\n"
    f"**Verdict:** `{verdict}`\n\n"
    f"- L-band total products over AOI: {len(rows)}\n"
    f"- GUNW: {len(gunw_rows)}\n"
    f"- RIFG: {len(rifg_rows)}\n"
    f"- GSLC: {len(gslc_rows)}\n"
    f"- Acquisition dates: {', '.join(dates) if dates else 'none'}\n"
    f"- S-band catalogue HTTP status: {sstatus}\n"
    f"- S-band feature count: {s_feature_count}\n\n"
    "No synthetic observations were used. Raw API responses are retained in `raw/`.\n"
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

cat > "$OUTPUT_DIR/status.json" <<EOF
{
  "status": "complete",
  "jobId": "${JOB_ID:-blindslope-pilot-20260729}",
  "sourceSha": "${SOURCE_SHA:-unknown}",
  "outputName": "blindslope-catalog-pilot"
}
EOF

find "$OUTPUT_DIR" -type f ! -name checksums.txt -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$OUTPUT_DIR/checksums.txt"
