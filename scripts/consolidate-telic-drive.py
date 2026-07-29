#!/usr/bin/env python3
"""One-time consolidation of Telic render folders using file-scoped Drive access."""

from __future__ import annotations

import base64
import configparser
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

FOLDER_MIME = "application/vnd.google-apps.folder"
PRODUCTION_NAME = "Telic Production"
LEGACY_NAME = "Telic-Renders"
FINAL_NAME = "FINAL VIDEOS"
TEMP_NAME = "TEMP RENDERS & REVIEWS"


def fail(message: str) -> None:
    raise RuntimeError(message)


def request_drive(
    token: str,
    method: str,
    endpoint: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"https://www.googleapis.com/drive/v3/{endpoint}"
    if query:
        url += "?" + query
    data = None if body is None else json.dumps(body).encode("utf-8")

    retry_delays = (0, 15, 30, 60, 90)
    last_detail = ""
    for delay in retry_delays:
        if delay:
            time.sleep(delay)
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                payload = response.read()
                time.sleep(1.5)
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_detail = detail
            transient = exc.code in {429, 500, 502, 503, 504} or any(
                marker in detail for marker in ("rateLimitExceeded", "Quota exceeded")
            )
            if not transient:
                fail(f"Drive API {method} failed with HTTP {exc.code}: {detail[:300]}")
    fail(f"Drive API {method} exhausted retries: {last_detail[:300]}")


def list_children(token: str, parent_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params = {
            "q": f"'{parent_id}' in parents and trashed = false",
            "spaces": "drive",
            "pageSize": "1000",
            "fields": "nextPageToken,files(id,name,mimeType,parents)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        response = request_drive(token, "GET", "files", params=params)
        results.extend(response.get("files", []))
        page_token = str(response.get("nextPageToken", ""))
        if not page_token:
            return results


def unique_folder(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [
        item for item in items
        if item.get("name") == name and item.get("mimeType") == FOLDER_MIME
    ]
    if len(matches) != 1:
        fail(f"Expected exactly one folder named {name!r}; found {len(matches)}")
    return matches[0]


def move_item(token: str, item: dict[str, Any], destination_id: str) -> None:
    parents = [str(parent) for parent in item.get("parents", []) if parent]
    if parents == [destination_id]:
        return
    params = {
        "addParents": destination_id,
        "supportsAllDrives": "true",
        "fields": "id,parents",
    }
    if parents:
        params["removeParents"] = ",".join(parents)
    request_drive(token, "PATCH", f"files/{item['id']}", params=params, body={})


def delete_folder(token: str, folder_id: str) -> None:
    request_drive(
        token,
        "DELETE",
        f"files/{folder_id}",
        params={"supportsAllDrives": "true"},
    )


def load_access() -> tuple[str, str]:
    encoded = os.environ.get("RCLONE_CONFIG_B64", "")
    if not encoded:
        fail("Drive credential is not configured")

    handle = tempfile.NamedTemporaryFile(prefix="rclone-", delete=False)
    try:
        handle.write(base64.b64decode(encoded))
        handle.close()
        os.chmod(handle.name, 0o600)
        subprocess.run(
            ["rclone", "lsf", "gdrive:", "--config", handle.name, "--max-depth", "1"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(handle.name)
        section = parser["gdrive"]
        if "drive.file" not in section.get("scope", ""):
            fail("Drive credential is not file-scoped")
        token_data = json.loads(section.get("token", "{}"))
        token = str(token_data.get("access_token", "")).strip()
        if not token:
            fail("Drive OAuth token is missing")
        configured_root = section.get("root_folder_id", "").strip()
        return token, configured_root
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


def main() -> None:
    token, configured_root = load_access()
    if configured_root:
        production_id = configured_root
    else:
        production = unique_folder(list_children(token, "root"), PRODUCTION_NAME)
        production_id = str(production["id"])

    root_items = list_children(token, production_id)
    final_folder = unique_folder(root_items, FINAL_NAME)
    temp_folder = unique_folder(root_items, TEMP_NAME)
    legacy_roots = [
        item for item in root_items
        if item.get("name") == LEGACY_NAME and item.get("mimeType") == FOLDER_MIME
    ]

    moved = 0
    for legacy in legacy_roots:
        for item in list_children(token, str(legacy["id"])):
            move_item(token, item, str(temp_folder["id"]))
            moved += 1

    deleted = 0
    for legacy in legacy_roots:
        remaining = list_children(token, str(legacy["id"]))
        if remaining:
            fail("A legacy render root still contains files after migration")
        delete_folder(token, str(legacy["id"]))
        deleted += 1

    root_after = list_children(token, production_id)
    if any(
        item.get("name") == LEGACY_NAME and item.get("mimeType") == FOLDER_MIME
        for item in root_after
    ):
        fail("A legacy Telic-Renders folder remains")

    final_items = list_children(token, str(final_folder["id"]))
    if not final_items or any(item.get("mimeType") != "video/mp4" for item in final_items):
        fail("FINAL VIDEOS is empty or contains a non-MP4 item")

    temp_items = list_children(token, str(temp_folder["id"]))
    print(
        "Telic Drive consolidation verified: "
        f"moved={moved}, deleted_legacy_roots={deleted}, "
        f"final_videos={len(final_items)}, temp_items={len(temp_items)}"
    )


if __name__ == "__main__":
    main()
