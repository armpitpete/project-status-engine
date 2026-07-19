#!/usr/bin/env python3
"""Build the unredacted full-owner completion dataset.

This output is for trusted internal consumers such as the future README
synchroniser. It is never a public or dashboard surface.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import completion_status as completion
import live_status as core

INTERNAL_OUT_DIR = Path(os.getenv("INTERNAL_STATUS_OUT_DIR", "internal-build"))
INTERNAL_DATASET_NAME = "completion-status.json"


def _repository_record(project: dict[str, Any]) -> dict[str, Any]:
    """Return only the identity and completion fields needed by internal consumers."""
    return {
        "name": project.get("name") or project.get("full_name") or "Unknown",
        "full_name": project.get("full_name") or project.get("name") or "Unknown",
        "private": bool(project.get("private")),
        "url": project.get("url") or "",
        "completion": copy.deepcopy(project.get("completion") or completion.not_configured()),
    }


def build_data(
    ranked: list[dict[str, Any]], errors: list[str], now: dt.datetime
) -> dict[str, Any]:
    """Preserve every discovered repository without public redaction or top-five limiting."""
    repositories = [_repository_record(project) for project in ranked]
    return {
        "view": "internal-owner-completion",
        "owner": core.OWNER,
        "generated_at": now.isoformat(),
        "source_path": completion.PROGRESS_PATH,
        "repository_count": len(repositories),
        "repositories": repositories,
        "completion_summary": completion.summary_for(repositories, include_private=True),
        "errors": list(errors),
    }


def write_output(data: dict[str, Any]) -> Path:
    """Write the trusted dataset outside both public and private dashboard trees."""
    INTERNAL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = INTERNAL_OUT_DIR / INTERNAL_DATASET_NAME
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
