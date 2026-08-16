#!/usr/bin/env python3
"""Download and inspect the 2026 Shober EDMOND sporadic subset from Zenodo."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import requests

OUT = Path("ghoststream_shober_edmond_inspection")
RECORD_API = "https://zenodo.org/api/records/18664293"
TARGET = "EDMOND_shober_2026_subset.csv"
EXPECTED_MD5 = "c5a3ee2c89cdff792bd114a39179350b"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "GhostStream independent-validation/1.0"})
    record_response = session.get(RECORD_API, timeout=120)
    record_response.raise_for_status()
    record = record_response.json()
    files = {item["key"]: item for item in record.get("files", [])}
    if TARGET not in files:
        raise RuntimeError(f"{TARGET} not present; available={sorted(files)}")
    item = files[TARGET]
    url = item.get("links", {}).get("content") or item.get("links", {}).get("self")
    if not url:
        raise RuntimeError(f"No content URL in file metadata: {item}")

    path = OUT / TARGET
    digest = hashlib.md5()
    total = 0
    with session.get(url, timeout=300, stream=True) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                print(f"downloaded {total:,} bytes", flush=True)
    md5 = digest.hexdigest()
    if md5 != EXPECTED_MD5:
        raise RuntimeError(f"MD5 mismatch: expected {EXPECTED_MD5}, got {md5}")

    data = pd.read_csv(path, low_memory=False)
    summary = {
        "record_id": record.get("id"),
        "record_title": record.get("metadata", {}).get("title"),
        "published": record.get("metadata", {}).get("publication_date"),
        "license": record.get("metadata", {}).get("license", {}).get("id"),
        "file": TARGET,
        "content_url": url,
        "bytes": total,
        "md5": md5,
        "rows": int(len(data)),
        "columns": list(map(str, data.columns)),
        "dtypes": {str(column): str(dtype) for column, dtype in data.dtypes.items()},
        "head": data.head(5).where(pd.notna(data.head(5)), None).to_dict(orient="records"),
    }
    for column in data.columns:
        low = str(column).lower()
        if any(token in low for token in ("year", "date", "time", "sol", "lambda", "node", "omega", "peri", "ra", "dec", "vg", "speed")):
            series = data[column]
            summary.setdefault("candidate_column_summaries", {})[str(column)] = {
                "non_null": int(series.notna().sum()),
                "unique": int(series.nunique(dropna=True)),
                "sample": [None if pd.isna(value) else str(value) for value in series.drop_duplicates().head(10)],
            }
            numeric = pd.to_numeric(series, errors="coerce")
            if numeric.notna().any():
                summary["candidate_column_summaries"][str(column)].update({
                    "numeric_min": float(numeric.min()),
                    "numeric_max": float(numeric.max()),
                })

    (OUT / "inspection.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    lines = [
        "# Shober 2026 EDMOND subset inspection", "",
        f"- Rows: **{len(data):,}**",
        f"- Bytes: **{total:,}**",
        f"- MD5 verified: **{md5}**",
        f"- Columns: `{list(data.columns)}`", "",
        "## First rows", "", "```json",
        json.dumps(summary["head"], indent=2, default=str), "```", "",
    ]
    (OUT / "INSPECTION.md").write_text("\n".join(lines))
    print(json.dumps({
        "rows": len(data), "columns": list(data.columns), "md5": md5,
        "candidate_column_summaries": summary.get("candidate_column_summaries", {}),
    }, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
