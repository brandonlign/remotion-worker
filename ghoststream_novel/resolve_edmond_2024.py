#!/usr/bin/env python3
"""Resolve the broken public EDMOND v6.01 2024 ZIP link.

Searches WordPress REST media/posts, sitemap indexes, page HTML, and plausible
asset-date directories. It validates a candidate only when the response is a
real ZIP containing a CSV with the expected EDMOND/UFOOrbit schema.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT = Path("ghoststream_edmond_resolver")
BASE = "https://meteornews.net/"
TARGET = "U2_2024_EDM.zip"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GhostStream research archive resolver/1.0"})


def get(url: str, **kwargs):
    return SESSION.get(url, timeout=180, allow_redirects=True, **kwargs)


def candidate_from_url(url: str, source: str, candidates: dict[str, set[str]]) -> None:
    if TARGET.lower() in url.lower():
        candidates.setdefault(url, set()).add(source)


def extract_urls(value, source: str, candidates: dict[str, set[str]]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            extract_urls(item, source, candidates)
    elif isinstance(value, list):
        for item in value:
            extract_urls(item, source, candidates)
    elif isinstance(value, str):
        for match in re.findall(r'https?://[^\s"\'<>]+', value):
            candidate_from_url(match.rstrip('.,);'), source, candidates)
        if TARGET.lower() in value.lower() and value.startswith('/'):
            candidate_from_url(urljoin(BASE, value), source, candidates)


def query_json(endpoint: str, params: dict, source: str, candidates: dict[str, set[str]], audit: list[dict]):
    try:
        response = get(endpoint, params=params)
        audit.append({"source": source, "url": response.url, "status": response.status_code,
                      "bytes": len(response.content), "content_type": response.headers.get("content-type")})
        if response.status_code == 200:
            payload = response.json()
            extract_urls(payload, source, candidates)
            return payload
    except Exception as exc:
        audit.append({"source": source, "error": f"{type(exc).__name__}: {exc}"})
    return None


def inspect_page(candidates: dict[str, set[str]], audit: list[dict]) -> None:
    response = get(urljoin(BASE, "edmond/"))
    audit.append({"source": "edmond_page", "url": response.url, "status": response.status_code,
                  "bytes": len(response.content)})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for link in soup.find_all("a", href=True):
        candidate_from_url(urljoin(response.url, link["href"]), "edmond_page_href", candidates)
    extract_urls(response.text, "edmond_page_html", candidates)


def inspect_wordpress(candidates: dict[str, set[str]], audit: list[dict]) -> None:
    api = urljoin(BASE, "wp-json/wp/v2/")
    for kind in ("media", "pages", "posts"):
        for search in ("U2_2024_EDM", "EDMOND 2024", "EDMOND", "2024"):
            payload = query_json(
                api + kind,
                {"search": search, "per_page": 100, "page": 1, "context": "view"},
                f"wp_{kind}_{search}", candidates, audit,
            )
            if isinstance(payload, list):
                for item in payload:
                    extract_urls(item, f"wp_{kind}_{search}", candidates)

    # Inspect all media pages if the collection is modest enough.
    first = get(api + "media", params={"per_page": 100, "page": 1})
    if first.status_code == 200:
        total_pages = int(first.headers.get("X-WP-TotalPages", "1"))
        total_pages = min(total_pages, 100)
        for page in range(1, total_pages + 1):
            response = first if page == 1 else get(api + "media", params={"per_page": 100, "page": page})
            audit.append({"source": "wp_media_all", "page": page, "status": response.status_code,
                          "bytes": len(response.content)})
            if response.status_code != 200:
                continue
            extract_urls(response.json(), f"wp_media_page_{page}", candidates)


def inspect_sitemaps(candidates: dict[str, set[str]], audit: list[dict]) -> None:
    queue = [urljoin(BASE, "wp-sitemap.xml"), urljoin(BASE, "sitemap_index.xml")]
    seen = set()
    for _ in range(100):
        if not queue:
            break
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            response = get(url)
            audit.append({"source": "sitemap", "url": url, "status": response.status_code,
                          "bytes": len(response.content)})
            if response.status_code != 200:
                continue
            for loc in re.findall(r'<loc>(.*?)</loc>', response.text, flags=re.I | re.S):
                loc = loc.strip()
                candidate_from_url(loc, "sitemap_loc", candidates)
                if loc.endswith('.xml') and loc not in seen:
                    queue.append(loc)
        except Exception as exc:
            audit.append({"source": "sitemap", "url": url, "error": f"{type(exc).__name__}: {exc}"})


def add_plausible_paths(candidates: dict[str, set[str]]) -> None:
    directories = {
        "assets/2025-03-29-edmond-database/",
        "assets/2025-03-30-edmond-database/",
        "assets/2025-05-01-edmond-database/",
        "assets/2025-05-29-edmond-database/",
        "assets/2025-05-30-edmond-database/",
        "wp-content/uploads/2025/03/",
        "wp-content/uploads/2025/04/",
        "wp-content/uploads/2025/05/",
        "wp-content/uploads/2025/06/",
    }
    start = date(2025, 3, 1)
    end = date(2025, 6, 30)
    current = start
    while current <= end:
        directories.add(f"assets/{current.isoformat()}-edmond-database/")
        current += timedelta(days=1)
    for directory in sorted(directories):
        candidate_from_url(urljoin(BASE, directory + TARGET), "plausible_path", candidates)
        candidate_from_url(urljoin(BASE, directory + TARGET.lower()), "plausible_path_lower", candidates)


def validate(url: str) -> dict:
    result = {"url": url}
    try:
        response = get(url)
        result.update({"status": response.status_code, "final_url": response.url,
                       "bytes": len(response.content), "content_type": response.headers.get("content-type")})
        if response.status_code != 200:
            return result
        if not response.content.startswith(b"PK\x03\x04"):
            result["reason"] = "not_zip_signature"
            result["preview"] = response.content[:200].decode("utf-8", errors="replace")
            return result
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            result["members"] = archive.namelist()
            csvs = [name for name in archive.namelist() if name.lower().endswith('.csv')]
            if not csvs:
                result["reason"] = "zip_without_csv"
                return result
            raw = archive.read(csvs[0])
            header = raw[:10000].decode("utf-8", errors="replace").splitlines()[0]
            result["csv_member"] = csvs[0]
            result["csv_bytes"] = len(raw)
            result["header"] = header
            expected = all(token in header for token in ("_sol", "_vg", "_q", "_e", "_node"))
            result["valid_edmond_archive"] = bool(expected)
            if expected:
                output = OUT / TARGET
                output.write_bytes(response.content)
                result["saved_to"] = str(output)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> int:
    OUT.mkdir(exist_ok=True)
    candidates: dict[str, set[str]] = {}
    audit: list[dict] = []
    inspect_page(candidates, audit)
    inspect_wordpress(candidates, audit)
    inspect_sitemaps(candidates, audit)
    add_plausible_paths(candidates)

    # Prefer discovered links before brute-force paths.
    ordered = sorted(candidates, key=lambda url: ("plausible_path" in candidates[url], url))
    validations = []
    found = None
    for index, url in enumerate(ordered):
        result = validate(url)
        result["sources"] = sorted(candidates[url])
        validations.append(result)
        print(f"[{index+1}/{len(ordered)}] {result.get('status')} {result.get('bytes')} {url}", flush=True)
        if result.get("valid_edmond_archive"):
            found = result
            print(f"FOUND {url}", flush=True)
            break

    payload = {
        "target": TARGET,
        "candidate_count": len(ordered),
        "resolved": bool(found),
        "found": found,
        "validations": validations,
        "discovery_audit": audit,
    }
    (OUT / "edmond_2024_resolution.json").write_text(json.dumps(payload, indent=2) + "\n")
    lines = ["# EDMOND 2024 archive resolution", "",
             f"**Resolved:** `{bool(found)}`", "",
             f"Candidates tested: **{len(validations)} / {len(ordered)}**", ""]
    if found:
        lines += [f"- URL: `{found['url']}`", f"- Bytes: **{found['bytes']}**",
                  f"- CSV: `{found['csv_member']}`", f"- Header: `{found['header']}`", ""]
    else:
        lines += ["The public page advertises the archive, but no working public asset was located through the page, WordPress REST API, sitemaps, or plausible asset directories.", ""]
    (OUT / "EDMOND_2024_RESOLUTION.md").write_text("\n".join(lines))
    return 0 if found else 2


if __name__ == "__main__":
    raise SystemExit(main())
