#!/usr/bin/env python3
"""Resolve EDMOND 2024 annual or Q2 data through public web archives.

The current MeteorNews links are broken. This script queries Wayback CDX,
Wayback availability, Common Crawl indexes, and archived EDMOND page snapshots.
A candidate is accepted only if it is a real ZIP containing a CSV with EDMOND
orbit columns. Q2 2024 is scientifically sufficient for the April candidate.
"""
from __future__ import annotations

import gzip
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("ghoststream_edmond_archive_resolution")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GhostStream-public-archive-resolver/1.0"})
BASE = "https://meteornews.net/"
PAGE = urljoin(BASE, "edmond/")
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_AVAILABILITY = "https://archive.org/wayback/available"
COMMON_CRAWL_INDEXES = "https://index.commoncrawl.org/collinfo.json"

TARGET_HINTS = (
    "U2_2024_EDM.zip",
    "Q2_2024_EDM.zip",
    "U2_Q2_2024_EDM.zip",
    "2024_Q2_EDM.zip",
    "EDM_2024_Q2.zip",
    "EDMOND_2024_Q2.zip",
)


def get(url: str, **kwargs) -> requests.Response:
    return SESSION.get(url, timeout=240, allow_redirects=True, **kwargs)


def is_relevant_zip(url: str) -> bool:
    low = url.lower()
    return low.endswith(".zip") and "2024" in low and (
        "edm" in low or "edmond" in low
    )


def extract_links(html: str, base_url: str) -> set[str]:
    links: set[str] = set()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("a", href=True):
        url = urljoin(base_url, tag["href"])
        if is_relevant_zip(url):
            links.add(url)
    for text in re.findall(r'https?://[^\s"\'<>]+\.zip(?:\?[^\s"\'<>]*)?', html, flags=re.I):
        if is_relevant_zip(text):
            links.add(text)
    return links


def wayback_cdx(url_pattern: str, audit: list[dict]) -> list[dict]:
    params = {
        "url": url_pattern,
        "output": "json",
        "fl": "timestamp,original,statuscode,mimetype,digest,length",
        "filter": "statuscode:200",
        "collapse": "digest",
        "from": "2024",
        "to": "2026",
    }
    try:
        response = get(WAYBACK_CDX, params=params)
        audit.append({"kind": "wayback_cdx", "query": url_pattern, "url": response.url,
                      "status": response.status_code, "bytes": len(response.content)})
        if response.status_code != 200:
            return []
        payload = response.json()
        if not payload or len(payload) < 2:
            return []
        header = payload[0]
        return [dict(zip(header, row)) for row in payload[1:]]
    except Exception as exc:
        audit.append({"kind": "wayback_cdx", "query": url_pattern,
                      "error": f"{type(exc).__name__}: {exc}"})
        return []


def archived_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


def validate_zip_bytes(content: bytes) -> dict:
    result: dict = {"bytes": len(content)}
    if not content.startswith(b"PK\x03\x04"):
        result["valid"] = False
        result["reason"] = "not_zip_signature"
        return result
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            csvs = [name for name in names if name.lower().endswith('.csv')]
            result["members"] = names[:100]
            if not csvs:
                result["valid"] = False
                result["reason"] = "no_csv"
                return result
            for name in csvs:
                raw = archive.read(name)
                first_lines = raw[:20000].decode("utf-8", errors="replace").splitlines()
                if not first_lines:
                    continue
                header = first_lines[0]
                expected = all(token in header for token in ("_sol", "_vg", "_q", "_e", "_node"))
                if expected:
                    result.update({
                        "valid": True,
                        "csv_member": name,
                        "csv_bytes": len(raw),
                        "header": header,
                        "first_data_line": first_lines[1] if len(first_lines) > 1 else None,
                    })
                    return result
            result["valid"] = False
            result["reason"] = "csv_without_expected_schema"
    except Exception as exc:
        result["valid"] = False
        result["reason"] = f"bad_zip:{type(exc).__name__}:{exc}"
    return result


def fetch_and_validate(url: str, source: str, validations: list[dict]) -> dict | None:
    try:
        response = get(url)
        validation = validate_zip_bytes(response.content) if response.status_code == 200 else {"valid": False}
        record = {
            "source": source,
            "url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type"),
            **validation,
        }
        validations.append(record)
        print(f"{source}: status={response.status_code} bytes={len(response.content):,} valid={record.get('valid')} {url}", flush=True)
        return record if record.get("valid") else None
    except Exception as exc:
        validations.append({"source": source, "url": url,
                            "error": f"{type(exc).__name__}: {exc}", "valid": False})
        return None


def wayback_availability(original: str, audit: list[dict]) -> str | None:
    try:
        response = get(WAYBACK_AVAILABILITY, params={"url": original, "timestamp": "20250601"})
        audit.append({"kind": "wayback_availability", "original": original,
                      "status": response.status_code, "bytes": len(response.content)})
        if response.status_code != 200:
            return None
        closest = response.json().get("archived_snapshots", {}).get("closest", {})
        if closest.get("available") and closest.get("status") == "200":
            return closest.get("url")
    except Exception as exc:
        audit.append({"kind": "wayback_availability", "original": original,
                      "error": f"{type(exc).__name__}: {exc}"})
    return None


def common_crawl_records(url_pattern: str, audit: list[dict]) -> list[dict]:
    records: list[dict] = []
    try:
        info = get(COMMON_CRAWL_INDEXES)
        indexes = info.json() if info.status_code == 200 else []
    except Exception as exc:
        audit.append({"kind": "common_crawl_indexes", "error": f"{type(exc).__name__}: {exc}"})
        return records
    for item in indexes[:12]:
        api = item.get("cdx-api")
        if not api:
            continue
        try:
            response = get(api, params={"url": url_pattern, "output": "json", "filter": "status:200"})
            audit.append({"kind": "common_crawl", "index": item.get("id"), "query": url_pattern,
                          "status": response.status_code, "bytes": len(response.content)})
            if response.status_code != 200:
                continue
            for line in response.text.splitlines():
                try:
                    record = json.loads(line)
                    record["crawl_index"] = item.get("id")
                    records.append(record)
                except json.JSONDecodeError:
                    pass
        except Exception as exc:
            audit.append({"kind": "common_crawl", "index": item.get("id"), "query": url_pattern,
                          "error": f"{type(exc).__name__}: {exc}"})
    return records


def fetch_common_crawl(record: dict, validations: list[dict]) -> dict | None:
    filename = record.get("filename")
    offset = record.get("offset")
    length = record.get("length")
    if not filename or offset is None or length is None:
        return None
    url = "https://data.commoncrawl.org/" + filename
    headers = {"Range": f"bytes={offset}-{int(offset)+int(length)-1}"}
    try:
        response = get(url, headers=headers)
        content = response.content
        # WARC response may be gzip-compressed.
        try:
            content = gzip.decompress(content)
        except OSError:
            pass
        # Extract HTTP payload after WARC and embedded HTTP headers.
        marker = content.find(b"\r\n\r\n", content.find(b"HTTP/"))
        payload = content[marker + 4:] if marker >= 0 else content
        validation = validate_zip_bytes(payload)
        result = {
            "source": "common_crawl",
            "original_url": record.get("url"),
            "crawl_index": record.get("crawl_index"),
            "warc_url": url,
            "range": headers["Range"],
            **validation,
        }
        validations.append(result)
        print(f"common_crawl: bytes={len(payload):,} valid={result.get('valid')} {record.get('url')}", flush=True)
        return result if result.get("valid") else None
    except Exception as exc:
        validations.append({"source": "common_crawl", "record": record,
                            "error": f"{type(exc).__name__}: {exc}", "valid": False})
        return None


def save_found(found: dict, content: bytes, name: str) -> None:
    path = OUT / name
    path.write_bytes(content)
    found["saved_to"] = str(path)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    audit: list[dict] = []
    validations: list[dict] = []
    candidates: set[str] = set()

    # Current page links.
    response = get(PAGE)
    audit.append({"kind": "current_page", "status": response.status_code,
                  "bytes": len(response.content), "url": response.url})
    if response.status_code == 200:
        candidates.update(extract_links(response.text, response.url))

    # Direct expected URLs and wildcard CDX queries.
    for hint in TARGET_HINTS:
        candidates.add(urljoin(BASE, f"assets/2025-03-29-edmond-database/{hint}"))
        candidates.add(urljoin(BASE, f"wp-content/uploads/2025/03/{hint}"))

    cdx_queries = [
        "meteornews.net/*U2_2024_EDM.zip",
        "meteornews.net/*Q2*2024*EDM*.zip",
        "meteornews.net/*2024*Q2*EDM*.zip",
        PAGE,
    ]
    cdx_records: list[dict] = []
    for query in cdx_queries:
        cdx_records.extend(wayback_cdx(query, audit))

    # Archived EDMOND pages may reveal historical paths not present now.
    for record in cdx_records:
        original = record.get("original", "")
        timestamp = record.get("timestamp", "")
        if original.rstrip("/") == PAGE.rstrip("/") and timestamp:
            archived_page = archived_url(timestamp, original)
            try:
                page_response = get(archived_page)
                audit.append({"kind": "archived_page", "url": archived_page,
                              "status": page_response.status_code, "bytes": len(page_response.content)})
                if page_response.status_code == 200:
                    candidates.update(extract_links(page_response.text, original))
            except Exception as exc:
                audit.append({"kind": "archived_page", "url": archived_page,
                              "error": f"{type(exc).__name__}: {exc}"})

    for record in cdx_records:
        original = record.get("original", "")
        if is_relevant_zip(original):
            candidates.add(original)

    found = None
    found_content = None

    # Direct and availability checks.
    for original in sorted(candidates):
        result = fetch_and_validate(original, "direct", validations)
        if result:
            found = result
            found_content = get(original).content
            break
        snapshot = wayback_availability(original, audit)
        if snapshot:
            result = fetch_and_validate(snapshot.replace("http://", "https://"), "wayback_availability", validations)
            if result:
                found = result
                found_content = get(snapshot.replace("http://", "https://")).content
                break

    # Direct CDX snapshots.
    if not found:
        for record in cdx_records:
            if not is_relevant_zip(record.get("original", "")):
                continue
            url = archived_url(record["timestamp"], record["original"])
            result = fetch_and_validate(url, "wayback_cdx_snapshot", validations)
            if result:
                found = result
                found_content = get(url).content
                break

    # Common Crawl URL index and WARC retrieval.
    cc_records: list[dict] = []
    if not found:
        for pattern in (
            "meteornews.net/*U2_2024_EDM.zip",
            "meteornews.net/*Q2*2024*EDM*.zip",
            "meteornews.net/*2024*Q2*EDM*.zip",
        ):
            cc_records.extend(common_crawl_records(pattern, audit))
        seen = set()
        for record in cc_records:
            key = (record.get("filename"), record.get("offset"), record.get("length"))
            if key in seen:
                continue
            seen.add(key)
            result = fetch_common_crawl(record, validations)
            if result:
                found = result
                # Re-fetch payload deterministically for saving.
                filename = record["filename"]
                start = int(record["offset"])
                length = int(record["length"])
                raw = get("https://data.commoncrawl.org/" + filename,
                          headers={"Range": f"bytes={start}-{start+length-1}"}).content
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    pass
                marker = raw.find(b"\r\n\r\n", raw.find(b"HTTP/"))
                found_content = raw[marker + 4:] if marker >= 0 else raw
                break

    if found and found_content:
        original_url = found.get("original_url") or found.get("final_url") or found.get("url", "")
        low = original_url.lower()
        name = "U2_2024_EDM.zip" if "u2_2024" in low else "EDMOND_Q2_2024.zip"
        save_found(found, found_content, name)

    payload = {
        "resolved": bool(found),
        "found": found,
        "candidate_urls": sorted(candidates),
        "wayback_records": cdx_records,
        "common_crawl_records": cc_records,
        "validations": validations,
        "audit": audit,
    }
    (OUT / "edmond_archive_resolution.json").write_text(json.dumps(payload, indent=2) + "\n")
    lines = ["# EDMOND 2024 web-archive resolution", "",
             f"**Resolved:** `{bool(found)}`", "",
             f"Direct/archived validations: **{len(validations)}**", "",
             f"Wayback CDX records: **{len(cdx_records)}**", "",
             f"Common Crawl records: **{len(cc_records)}**", ""]
    if found:
        lines += [f"- Source: `{found.get('source')}`",
                  f"- Original/final URL: `{found.get('original_url') or found.get('final_url') or found.get('url')}`",
                  f"- CSV member: `{found.get('csv_member')}`",
                  f"- CSV bytes: **{found.get('csv_bytes')}**", ""]
    else:
        lines += ["No retrievable annual or Q2 2024 ZIP was found in the current server, Wayback CDX/availability, or the recent Common Crawl indexes.", ""]
    (OUT / "EDMOND_ARCHIVE_RESOLUTION.md").write_text("\n".join(lines))
    return 0 if found else 2


if __name__ == "__main__":
    raise SystemExit(main())
