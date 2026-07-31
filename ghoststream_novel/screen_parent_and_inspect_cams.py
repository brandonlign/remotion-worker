#!/usr/bin/env python3
"""Screen NASA/JPL SBDB for candidate parents and inspect official CAMS files."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import requests

OUT = Path("ghoststream_parent_cams")
STREAM = np.asarray([0.946296, 0.079202, 24.709376, 333.493819, 37.937477], dtype=float)
JPL_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
FIELDS = [
    "full_name", "pdes", "kind", "class", "neo", "t_jup", "moid",
    "epoch", "e", "a", "q", "i", "om", "w", "first_obs", "last_obs",
    "condition_code", "data_arc", "H",
]
CONSTRAINTS = {
    "AND": [
        "e|RG|0.70|1.30",
        "q|RG|0.01|0.35",
        "i|RG|0|60",
    ]
}
CAMS_CANDIDATES = [
    "https://www.astro.sk/~ne/IAUMDC/PhVR2020/CAMS_by_date_v2.1l",
    "https://www.astro.sk/~ne/IAUMDC/PhVR2020/video/CAMS_by_date_v2.1l",
    "https://www.astro.sk/~ne/IAUMDC/PhVR2020/CAMS_California_v2.zip",
    "https://www.astro.sk/~ne/IAUMDC/PhVR2020/video/CAMS_California_v2.zip",
    "https://www.astro.sk/~ne/IAUMDC/PhV2016/CAMS_by_date_v2.1l",
    "https://www.astro.sk/~ne/IAUMDC/PhV2016/CAMS_California_v2.zip",
]


def perihelion_vector(orbits: np.ndarray) -> np.ndarray:
    inc = np.deg2rad(orbits[:, 2])
    arg = np.deg2rad(orbits[:, 3])
    node = np.deg2rad(orbits[:, 4])
    return np.column_stack([
        np.cos(node) * np.cos(arg) - np.sin(node) * np.sin(arg) * np.cos(inc),
        np.sin(node) * np.cos(arg) + np.cos(node) * np.sin(arg) * np.cos(inc),
        np.sin(arg) * np.sin(inc),
    ])


def orbit_distance_matrix(a: np.ndarray, b: np.ndarray | None = None) -> np.ndarray:
    b = a if b is None else b
    e1, q1 = a[:, 0][:, None], a[:, 1][:, None]
    e2, q2 = b[:, 0][None, :], b[:, 1][None, :]
    i1, n1 = np.deg2rad(a[:, 2])[:, None], np.deg2rad(a[:, 4])[:, None]
    i2, n2 = np.deg2rad(b[:, 2])[None, :], np.deg2rad(b[:, 4])[None, :]
    plane = np.arccos(np.clip(np.cos(i1) * np.cos(i2) + np.sin(i1) * np.sin(i2) * np.cos(n1 - n2), -1, 1))
    p1, p2 = perihelion_vector(a), perihelion_vector(b)
    peri = np.arccos(np.clip(p1 @ p2.T, -1, 1))
    d2 = ((e1 - e2) ** 2 + (q1 - q2) ** 2 + (2 * np.sin(plane / 2)) ** 2
          + (((e1 + e2) / 2) * 2 * np.sin(peri / 2)) ** 2)
    return np.sqrt(np.maximum(d2, 0.0))


def get_json(params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(JPL_URL, params=params, timeout=180)
    response.raise_for_status()
    payload = response.json()
    signature = payload.get("signature", {})
    if signature.get("version") != "1.0":
        raise RuntimeError(f"Unexpected JPL API signature: {signature}")
    return payload


def screen_jpl() -> dict[str, Any]:
    constraint = json.dumps(CONSTRAINTS, separators=(",", ":"))
    count_payload = get_json({"sb-cdata": constraint})
    count = int(count_payload.get("count", 0))
    print(f"JPL broad-compatible objects: {count}", flush=True)
    page_size = 500
    rows: list[list[Any]] = []
    api_fields: list[str] | None = None
    for start in range(0, count, page_size):
        payload = get_json({
            "fields": ",".join(FIELDS), "sb-cdata": constraint,
            "full-prec": "true", "limit": page_size, "limit-from": start,
            "sort": "q",
        })
        fields = payload.get("fields", FIELDS)
        if api_fields is None:
            api_fields = list(fields)
        elif list(fields) != api_fields:
            raise RuntimeError("JPL fields changed between pages")
        rows.extend(payload.get("data", []))
        print(f"  fetched {min(start + page_size, count)}/{count}", flush=True)
    api_fields = api_fields or FIELDS
    records = []
    for row in rows:
        item = dict(zip(api_fields, row))
        try:
            orbit = np.asarray([
                float(item["e"]), float(item["q"]), float(item["i"]),
                float(item["w"]), float(item["om"]),
            ])
        except (TypeError, ValueError, KeyError):
            continue
        d_direct = float(orbit_distance_matrix(orbit[None, :], STREAM[None, :])[0, 0])
        # Equivalent node/peri representation can differ by 180 degrees.
        flipped = orbit.copy()
        flipped[3] = (flipped[3] + 180.0) % 360.0
        flipped[4] = (flipped[4] + 180.0) % 360.0
        d_flipped = float(orbit_distance_matrix(flipped[None, :], STREAM[None, :])[0, 0])
        item["d_stream"] = min(d_direct, d_flipped)
        item["d_direct"] = d_direct
        item["d_flipped"] = d_flipped
        records.append(item)
    records.sort(key=lambda item: item["d_stream"])
    shortlist = records[:100]
    likely = [item for item in records if item["d_stream"] <= 0.15]
    possible = [item for item in records if item["d_stream"] <= 0.25]
    return {
        "api": JPL_URL,
        "constraint": CONSTRAINTS,
        "count_reported": count,
        "rows_fetched": len(rows),
        "valid_orbits": len(records),
        "stream_orbit": STREAM.tolist(),
        "d_le_0_15": len(likely),
        "d_le_0_25": len(possible),
        "top_100": shortlist,
    }


def inspect_cams() -> dict[str, Any]:
    results = []
    for url in CAMS_CANDIDATES:
        try:
            response = requests.get(url, timeout=240)
            result: dict[str, Any] = {
                "url": url, "status": response.status_code,
                "bytes": len(response.content),
                "content_type": response.headers.get("content-type"),
            }
            if response.status_code != 200:
                results.append(result)
                continue
            if response.content[:4] == b"PK\x03\x04":
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    result["archive_names"] = archive.namelist()[:50]
                    samples = []
                    for name in archive.namelist():
                        if name.endswith("/"):
                            continue
                        raw = archive.read(name)
                        text = raw[:20000].decode("utf-8", errors="replace")
                        samples.append({
                            "name": name, "bytes": len(raw),
                            "first_lines": text.splitlines()[:12],
                        })
                        if len(samples) >= 5:
                            break
                    result["samples"] = samples
            else:
                text = response.content[:30000].decode("utf-8", errors="replace")
                result["first_lines"] = text.splitlines()[:25]
            results.append(result)
            print(f"CAMS candidate success: {url} ({len(response.content):,} bytes)", flush=True)
        except Exception as exc:
            results.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    successes = [item for item in results if item.get("status") == 200]
    return {"attempts": results, "successes": len(successes)}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    jpl = screen_jpl()
    cams = inspect_cams()
    payload = {"jpl_parent_screen": jpl, "cams_archive_inspection": cams}
    (OUT / "parent_and_cams.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    lines = [
        "# GhostStream parent-body screen and CAMS archive inspection", "",
        f"- JPL objects in broad orbit box: **{jpl['count_reported']}**",
        f"- Objects with stream D <= 0.15: **{jpl['d_le_0_15']}**",
        f"- Objects with stream D <= 0.25: **{jpl['d_le_0_25']}**",
        f"- CAMS URLs successfully opened: **{cams['successes']}**", "",
        "## Nearest JPL objects", "",
    ]
    for item in jpl["top_100"][:20]:
        lines.append(
            f"- `{item.get('pdes')}` {item.get('full_name')}: kind={item.get('kind')}, "
            f"D={item['d_stream']:.5f}, e={item.get('e')}, q={item.get('q')}, "
            f"i={item.get('i')}, node={item.get('om')}, peri={item.get('w')}"
        )
    lines += ["", "## CAMS attempts", ""]
    for item in cams["attempts"]:
        lines.append(f"- `{item['url']}`: status={item.get('status')}, bytes={item.get('bytes')}, error={item.get('error')}")
    (OUT / "PARENT_AND_CAMS.md").write_text("\n".join(lines) + "\n")
    print(f"Nearest JPL object: {jpl['top_100'][0] if jpl['top_100'] else None}")
    print(f"CAMS successes: {cams['successes']}")
    print(f"Report: {OUT / 'PARENT_AND_CAMS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
