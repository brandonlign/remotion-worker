#!/usr/bin/env python3
"""One-time, least-privilege cleanup for the Telic render destination.

The script uses the existing rclone OAuth token, operates only inside the
configured Drive root, extracts approved final MP4s into one folder, moves all
render-job history into a temporary folder, and removes duplicate legacy roots.
"""

from __future__ import annotations

import base64
import configparser
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

FOLDER_MIME = "application/vnd.google-apps.folder"
LEGACY_ROOT_NAME = "Telic-Renders"
FINAL_FOLDER_NAME = "FINAL VIDEOS"
TEMP_FOLDER_NAME = "TEMP RENDERS & REVIEWS"


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_rclone_config() -> tuple[str, str, str]:
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
        if "gdrive" not in parser:
            fail("rclone config has no gdrive remote")
        section = parser["gdrive"]
        if section.get("scope", "").strip() != "drive.file":
            fail("Drive remote is not using drive.file scope")

        root_id = section.get("root_folder_id", "").strip()
        if not root_id:
            fail("Drive remote has no configured root folder")

        token = json.loads(section.get("token", "{}"))
        access_token = str(token.get("access_token", "")).strip()
        if not access_token:
            fail("Drive OAuth token has no access token")
        return handle.name, root_id, access_token
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def drive_request(
    access_token: str,
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
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {access_token}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"Drive API {method} failed with HTTP {exc.code}: {detail[:500]}")


def list_children(access_token: str, parent_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params = {
            "q": f"'{parent_id}' in parents and trashed = false",
            "spaces": "drive",
            "pageSize": "1000",
            "fields": "nextPageToken,files(id,name,mimeType,createdTime,modifiedTime,parents,size)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        response = drive_request(access_token, "GET", "files", params=params)
        items.extend(response.get("files", []))
        page_token = str(response.get("nextPageToken", ""))
        if not page_token:
            return items


def create_folder(access_token: str, parent_id: str, name: str) -> dict[str, Any]:
    return drive_request(
        access_token,
        "POST",
        "files",
        params={"fields": "id,name,mimeType,createdTime,parents", "supportsAllDrives": "true"},
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
    )


def ensure_unique_folder(access_token: str, parent_id: str, name: str) -> dict[str, Any]:
    matches = [
        item
        for item in list_children(access_token, parent_id)
        if item.get("name") == name and item.get("mimeType") == FOLDER_MIME
    ]
    if len(matches) > 1:
        fail(f"More than one destination folder named {name!r}")
    return matches[0] if matches else create_folder(access_token, parent_id, name)


def move_item(access_token: str, item: dict[str, Any], destination_id: str) -> None:
    current_parents = [str(parent) for parent in item.get("parents", []) if parent]
    if destination_id in current_parents and len(current_parents) == 1:
        return
    params = {
        "addParents": destination_id,
        "supportsAllDrives": "true",
        "fields": "id,name,mimeType,parents,size",
    }
    if current_parents:
        params["removeParents"] = ",".join(current_parents)
    drive_request(access_token, "PATCH", f"files/{item['id']}", params=params, body={})


def delete_item(access_token: str, file_id: str) -> None:
    drive_request(
        access_token,
        "DELETE",
        f"files/{file_id}",
        params={"supportsAllDrives": "true"},
    )


def normalized_final_group(name: str) -> str | None:
    if name.startswith("FINAL - "):
        return re.sub(r"\s+-\s+(FIXED|OLD|ARCHIVE)$", "", name, flags=re.IGNORECASE)
    match = re.match(r"^(.*)-final-(\d+)$", name, flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


def final_rank(item: dict[str, Any]) -> tuple[int, str]:
    name = str(item.get("name", ""))
    match = re.match(r"^.*-final-(\d+)$", name, flags=re.IGNORECASE)
    numeric = int(match.group(1)) if match else 0
    return numeric, str(item.get("createdTime", ""))


def select_final_job_folders(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item.get("mimeType") != FOLDER_MIME:
            continue
        group = normalized_final_group(str(item.get("name", "")))
        if group is not None:
            groups[group].append(item)
    return [max(group_items, key=final_rank) for group_items in groups.values()]


def select_final_video(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    videos = [
        item
        for item in items
        if item.get("mimeType") == "video/mp4"
        and str(item.get("name", "")).lower() != "review.mp4"
    ]
    if not videos:
        return None
    return max(videos, key=lambda item: int(item.get("size", "0") or 0))


def main() -> None:
    config_path, root_id, access_token = load_rclone_config()
    try:
        final_folder = ensure_unique_folder(access_token, root_id, FINAL_FOLDER_NAME)
        temp_folder = ensure_unique_folder(access_token, root_id, TEMP_FOLDER_NAME)

        root_children = list_children(access_token, root_id)
        legacy_roots = [
            item
            for item in root_children
            if item.get("name") == LEGACY_ROOT_NAME and item.get("mimeType") == FOLDER_MIME
        ]

        if not legacy_roots:
            print("Cleanup already complete: no legacy render roots remain.")
            return

        legacy_children: list[dict[str, Any]] = []
        for legacy_root in legacy_roots:
            legacy_children.extend(list_children(access_token, str(legacy_root["id"])))

        final_jobs = select_final_job_folders(legacy_children)
        moved_final_count = 0
        existing_final_names = {
            str(item.get("name", "")) for item in list_children(access_token, str(final_folder["id"]))
        }
        for job in final_jobs:
            job_children = list_children(access_token, str(job["id"]))
            video = select_final_video(job_children)
            if video is None:
                continue
            if str(video.get("name", "")) in existing_final_names:
                continue
            move_item(access_token, video, str(final_folder["id"]))
            existing_final_names.add(str(video.get("name", "")))
            moved_final_count += 1

        moved_temp_count = 0
        for item in legacy_children:
            move_item(access_token, item, str(temp_folder["id"]))
            moved_temp_count += 1

        for legacy_root in legacy_roots:
            remaining = list_children(access_token, str(legacy_root["id"]))
            if remaining:
                fail("A legacy render root was not empty after migration")
            delete_item(access_token, str(legacy_root["id"]))

        root_after = list_children(access_token, root_id)
        if any(
            item.get("name") == LEGACY_ROOT_NAME and item.get("mimeType") == FOLDER_MIME
            for item in root_after
        ):
            fail("Legacy render roots still remain after cleanup")

        final_after = list_children(access_token, str(final_folder["id"]))
        invalid_final_items = [item for item in final_after if item.get("mimeType") != "video/mp4"]
        if invalid_final_items:
            fail("FINAL VIDEOS contains a non-MP4 item")

        temp_after = list_children(access_token, str(temp_folder["id"]))
        print(
            "Drive cleanup complete: "
            f"removed {len(legacy_roots)} duplicate roots, "
            f"placed {moved_final_count} approved videos in FINAL VIDEOS, "
            f"and moved {moved_temp_count} job-history items into temporary storage. "
            f"Verified final_count={len(final_after)} temp_count={len(temp_after)}."
        )
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
