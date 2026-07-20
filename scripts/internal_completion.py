#!/usr/bin/env python3
"""Build the unredacted full-owner completion and authority-exception dataset.

This output is for trusted internal consumers such as the README synchroniser.
It is never a public or dashboard artifact.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import authority_exceptions as exceptions
import completion_status as completion
import live_status as core

INTERNAL_OUT_DIR = Path(os.getenv("INTERNAL_STATUS_OUT_DIR", "internal-build"))
INTERNAL_DATASET_NAME = "completion-status.json"


def _repository_record(project: dict[str, Any]) -> dict[str, Any]:
    """Return identity, completion and authority-exception fields for internal consumers."""
    return {
        "name": project.get("name") or project.get("full_name") or "Unknown",
        "full_name": project.get("full_name") or project.get("name") or "Unknown",
        "private": bool(project.get("private")),
        "url": project.get("url") or "",
        "completion": copy.deepcopy(project.get("completion") or completion.not_configured()),
        "authority_exception": copy.deepcopy(project.get("authority_exception")),
    }


def build_data(
    ranked: list[dict[str, Any]], errors: list[str], now: dt.datetime
) -> dict[str, Any]:
    """Preserve every discovered repository without public redaction or top-five limiting."""
    repositories = [_repository_record(project) for project in ranked]
    queue = exceptions.queue_for(ranked)
    return {
        "view": "internal-owner-completion",
        "owner": core.OWNER,
        "generated_at": now.isoformat(),
        "source_path": completion.PROGRESS_PATH,
        "authority_exception_source": {
            "branch": exceptions.EXCEPTION_BRANCH,
            "path": exceptions.EXCEPTION_PATH,
        },
        "repository_count": len(repositories),
        "repositories": repositories,
        "completion_summary": completion.summary_for(repositories, include_private=True),
        "authority_exception_queue": queue,
        "authority_exception_summary": exceptions.summary_for(queue),
        "errors": list(errors),
    }


def write_output(data: dict[str, Any]) -> Path:
    """Write the trusted dataset outside both public and private dashboard trees."""
    INTERNAL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = INTERNAL_OUT_DIR / INTERNAL_DATASET_NAME
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target
