#!/usr/bin/env python3
"""Resolve the configured Telic root, then run the one-time cleanup safely."""

from __future__ import annotations

import base64
import configparser
import importlib.util
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name("drive-cleanup-once.py")
spec = importlib.util.spec_from_file_location("drive_cleanup_once", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load cleanup implementation")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


# Google Drive's shared API project can have a low per-minute query allowance.
# Pace every request and retry only transient quota/server failures. The cleanup
# itself is idempotent, so a retry never duplicates a moved file.
_original_drive_request = cleanup.drive_request


def throttled_drive_request(
    access_token: str,
    method: str,
    endpoint: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delays = (0, 15, 30, 60, 90)
    last_error: RuntimeError | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            result = _original_drive_request(
                access_token,
                method,
                endpoint,
                params=params,
                body=body,
            )
            time.sleep(1.5)
            return result
        except RuntimeError as exc:
            message = str(exc)
            transient = any(
                marker in message
                for marker in (
                    "rateLimitExceeded",
                    "Quota exceeded",
                    "HTTP 429",
                    "HTTP 500",
                    "HTTP 502",
                    "HTTP 503",
                    "HTTP 504",
                )
            )
            if not transient:
                raise
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Drive request failed without an error")


cleanup.drive_request = throttled_drive_request


def load_config_with_root_resolution() -> tuple[str, str, str]:
    encoded = os.environ.get("RCLONE_CONFIG_B64", "")
    if not encoded:
        cleanup.fail("Drive credential is not configured")

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
            cleanup.fail("rclone config has no gdrive remote")
        section = parser["gdrive"]
        if "drive.file" not in section.get("scope", "").strip():
            cleanup.fail("Drive remote is not using file-scoped access")

        token = json.loads(section.get("token", "{}"))
        access_token = str(token.get("access_token", "")).strip()
        if not access_token:
            cleanup.fail("Drive OAuth token has no access token")

        root_id = section.get("root_folder_id", "").strip()
        if not root_id:
            matches = [
                item
                for item in cleanup.list_children(access_token, "root")
                if item.get("name") == "Telic Production"
                and item.get("mimeType") == cleanup.FOLDER_MIME
            ]
            if len(matches) != 1:
                cleanup.fail("Could not resolve exactly one Telic Production folder")
            root_id = str(matches[0]["id"])

        return handle.name, root_id, access_token
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


cleanup.load_rclone_config = load_config_with_root_resolution
cleanup.main()
