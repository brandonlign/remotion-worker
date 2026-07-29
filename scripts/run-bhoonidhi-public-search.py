#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OUT = Path("bhoonidhi_public_search")
OUT.mkdir(exist_ok=True)
BASE = "https://bhoonidhi.nrsc.gov.in"
HEAD = {
    "User-Agent": "BlindSlope-Pilot/0.7",
    "Accept": "application/json,text/plain,*/*",
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": f"{BASE}/bhoonidhi/index.html",
}


def post(path: str, payload: dict[str, Any], token: str | None = None, timeout: int = 90) -> dict[str, Any]:
    headers = dict(HEAD)
    if token is not None:
        headers["token"] = token
    data = json.dumps(payload, separators=(",", ":")).encode()
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return {"status": r.status, "url": r.geturl(), "headers": dict(r.headers), "body": body, "error": None}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "url": e.geturl(), "headers": dict(e.headers), "body": e.read(), "error": None}
    except Exception as e:
        return {"status": None, "url": BASE + path, "headers": {}, "body": b"", "error": f"{type(e).__name__}: {e}"}


def parse_json(body: bytes):
    try:
        return json.loads(body)
    except Exception:
        return None


def strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


config_payload = {"userId": "T", "action": "GETAVCONFIG", "userEmail": "abc@xyz.com"}
config_resp = post("/bhoonidhi/SatSenServlet", config_payload)
config_json = parse_json(config_resp["body"])
(OUT / "archive_config_response.txt").write_bytes(config_resp["body"])

records = []
if isinstance(config_json, dict):
    value = config_json.get("Results")
    if isinstance(value, list):
        records = value

nisar_records = []
for record in records:
    text = json.dumps(record, sort_keys=True).lower()
    if "nisar" in text or "s-sar" in text or "ssar" in text:
        nisar_records.append(record)

# Build candidate selSats identifiers from every NISAR archive field. Bhoonidhi uses
# opaque archive codes in this field; the current configuration is the source of truth.
candidates: list[str] = []
for record in nisar_records:
    for key in ["satName", "satShortName", "satCode", "satId", "satID", "satellite", "sat"]:
        v = record.get(key) if isinstance(record, dict) else None
        if isinstance(v, str) and v.strip():
            candidates.append(v.strip())
    sensors = record.get("sensors", []) if isinstance(record, dict) else []
    if isinstance(sensors, list):
        for sensor in sensors:
            if not isinstance(sensor, dict):
                continue
            for key in ["senName", "senShortName", "senCode", "senId", "senID", "satSen", "satSenCode", "value", "id"]:
                v = sensor.get(key)
                if isinstance(v, str) and v.strip():
                    candidates.append(v.strip())
            # Common legacy format is SATELLITE_SENSOR.
            sat = next((record.get(k) for k in ["satShortName", "satCode", "satName"] if isinstance(record.get(k), str)), None)
            sen = next((sensor.get(k) for k in ["senShortName", "senCode", "senName"] if isinstance(sensor.get(k), str)), None)
            if sat and sen:
                candidates.extend([f"{sat}_{sen}", f"{sat}-{sen}", f"{sat}:{sen}"])

# Also include highly diagnostic literal values present in the live archive configuration.
for s in strings(nisar_records):
    if re.search(r"nisar|s-?sar|ssar|gunw|rifg|gslc", s, re.I) and len(s) <= 120:
        candidates.append(s.strip())

# Conservative fallback spellings used by release materials and portal UI.
candidates.extend(["NISAR", "NISAR_S-SAR", "NISAR_SSAR", "NISAR-SAR", "S-SAR", "SSAR"])
seen = set()
candidates = [x for x in candidates if x and not (x in seen or seen.add(x))][:80]

base_payload = {
    "userId": "T",
    "prod": "Standard",
    "offset": "0",
    "sdate": "JUL%2F08%2F2026",
    "edate": "JUL%2F29%2F2026",
    "query": "area",
    "queryType": "polygon",
    "isMX": "No",
    "tllat": 27.40,
    "tllon": 88.55,
    "brlat": 27.25,
    "brlon": 88.72,
    "filters": "%7B%7D",
}

attempts = []
successes = []
for sel in candidates:
    payload = dict(base_payload)
    payload["selSats"] = sel
    # Guest browsing normally has no authenticated JWT. Test both omitted and blank token,
    # matching browser behavior when localStorage has no logged-in token.
    for token_mode, token in [("omitted", None), ("blank", "")]:
        r = post("/bhoonidhi/ProductSearch", payload, token=token, timeout=45)
        parsed = parse_json(r["body"])
        result_count = None
        if isinstance(parsed, dict) and isinstance(parsed.get("Results"), list):
            result_count = len(parsed["Results"])
        rec = {
            "selSats": sel,
            "token_mode": token_mode,
            "status": r["status"],
            "error": r["error"],
            "result_count": result_count,
            "body_prefix": r["body"][:1200].decode("utf-8", "replace"),
        }
        attempts.append(rec)
        if r["status"] == 200 and result_count is not None:
            successes.append({"request": payload, "token_mode": token_mode, "response": parsed})
            # A nonempty result is enough to prove the public catalog path and capture scenes.
            if result_count > 0:
                break
    if successes and len(successes[-1]["response"].get("Results", [])) > 0:
        break

report = {
    "archive_config_status": config_resp["status"],
    "archive_config_error": config_resp["error"],
    "archive_record_count": len(records),
    "nisar_records": nisar_records,
    "candidate_selSats": candidates,
    "attempts": attempts,
    "successes": successes,
}
(OUT / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
print(json.dumps(report, indent=2, sort_keys=True, default=str))

if not nisar_records:
    sys.exit(2)
if not successes:
    sys.exit(3)
