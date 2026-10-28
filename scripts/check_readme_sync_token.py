#!/usr/bin/env python3
"""Verify that the dedicated README sync credential is accepted before costly work.

This deliberately probes only the authenticated user identity. Repository-specific
permissions are checked by the existing read-only all-target preflight. Neither
tokens, response bodies nor repository identities are logged here.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

API_USER = "https://api.github.com/user"


def check_token(token: str, *, urlopen: Any = urllib.request.urlopen) -> str:
    if not token:
        return "missing"
    request = urllib.request.Request(
        API_USER,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "project-status-engine-readme-preflight",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                return "unexpected_status"
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return "unauthorized"
        if exc.code == 403:
            return "forbidden"
        return "api_error"
    except (urllib.error.URLError, TimeoutError, OSError):
        return "api_unavailable"
    return "accepted"


def main() -> int:
    status = check_token(os.getenv("README_SYNC_TOKEN", ""))
    print(json.dumps({"credential_preflight": status}, separators=(",", ":")))
    return 0 if status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
