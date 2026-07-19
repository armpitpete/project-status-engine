#!/usr/bin/env python3
"""Bulk-bootstrap authority-backed completion contracts across an owner portfolio.

The controller inventories every active owner repository, classifies the project,
reads only explicit completion counts from existing authority/status documents,
and opens one reviewable automation PR when a contract or README marker block is
required. It never derives completion from repository activity and never accepts
percentage-only evidence.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

API_ROOT = "https://api.github.com"
OWNER = os.getenv("STATUS_OWNER", "armpitpete")
TOKEN = os.getenv("README_SYNC_TOKEN", "") or os.getenv("PROJECT_STATUS_TOKEN", "")
PROGRESS_PATH = ".project/progress.json"
README_PATH = "README.md"
BOOTSTRAP_BRANCH = "automation/project-status-bootstrap"
BOOTSTRAP_PR_TITLE = "Bootstrap authority-backed project completion"
EXCEPTION_ISSUE_TITLE = "Project completion bootstrap requires authority"
START_MARKER = b"<!-- AUTO:PROJECT-COMPLETION:START -->"
END_MARKER = b"<!-- AUTO:PROJECT-COMPLETION:END -->"
MAX_AUTHORITY_BYTES = 512_000
MAX_STAGES = 24

AUTHORITY_PATH_PRIORITY = (
    "docs/PROJECT_AUTHORITY.md",
    "PROJECT_AUTHORITY.md",
    "docs/COMPLETION_AUTHORITY.md",
    "COMPLETION_AUTHORITY.md",
    "docs/PROJECT_STATUS.md",
    "PROJECT_STATUS.md",
    "docs/STATUS.md",
    "STATUS.md",
    "README.md",
)
AUTHORITY_NAME_TERMS = ("authority", "completion", "progress", "status", "readiness")
COMPLETION_TERMS = (
    "complete",
    "completed",
    "accepted",
    "merged",
    "verified",
    "closed",
    "done",
    "progress",
    "recovered",
    "recovery",
    "implemented",
    "approved",
)

# Strict count patterns. A percentage is optional, but a completed/total pair is mandatory.
TABLE_COUNT = re.compile(
    r"^\s*\|\s*(?P<label>[^|]+?)\s*\|\s*`?(?P<done>\d{1,6})\s*/\s*(?P<total>\d{1,6})`?"
    r"(?:\s*(?:—|-|–|:)\s*\*{0,2}(?P<pct>\d{1,3}(?:\.\d+)?)%\*{0,2})?\s*\|"
)
LABELLED_OF = re.compile(
    r"^\s*(?:[-*+]\s*)?(?P<label>[^:|]{2,160}?)\s*[:—–-]\s*"
    r"[*_`]*(?P<done>\d{1,6})\s+(?:of|out\s+of)\s+(?P<total>\d{1,6})\b"
    r"(?P<tail>[^\n]*)$",
    re.IGNORECASE,
)
LABELLED_SLASH = re.compile(
    r"^\s*(?:[-*+]\s*)?(?P<label>[^:|]{2,160}?)\s*[:—–-]\s*"
    r"[*_`]*(?P<done>\d{1,6})\s*/\s*(?P<total>\d{1,6})\b(?P<tail>[^\n]*)$",
    re.IGNORECASE,
)
UNLABELLED_OF = re.compile(
    r"\b(?P<done>\d{1,6})\s+(?:of|out\s+of)\s+(?P<total>\d{1,6})\b(?P<tail>[^\n]*)$",
    re.IGNORECASE,
)
PERCENT = re.compile(r"(?P<pct>\d{1,3}(?:\.\d+)?)\s*%")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")


class BootstrapClosed(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


class ApiFailure(RuntimeError):
    def __init__(self, operation: str, status: int | None = None):
        code = f"api_{operation}" + (f"_{status}" if status is not None else "")
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EvidenceStage:
    label: str
    completed: int
    total: int
    evidence: str


@dataclass(frozen=True)
class RepositoryPlan:
    full_name: str
    private: bool
    default_branch: str
    default_sha: str
    project_type: str
    action: str
    files: dict[str, bytes]
    exception_code: str | None = None
    exception_detail: str = ""
    pending_pr_number: int | None = None


@dataclass(frozen=True)
class Result:
    target_id: str
    action: str
    code: str | None = None


def target_id(full_name: str) -> str:
    return hashlib.sha256(full_name.encode("utf-8")).hexdigest()


def safe_event(result: Result) -> str:
    payload: dict[str, Any] = {"target": result.target_id[:12], "action": result.action}
    if result.code:
        payload["code"] = result.code
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return text[:64] or "completion"


def _clean_label(value: str) -> str:
    value = re.sub(r"[`*_]", "", value)
    value = re.sub(r"\s+", " ", value).strip(" .:—–-|")
    return value[:180] or "Completion"


def _percent_matches(done: int, total: int, explicit: str | None) -> bool:
    if explicit is None:
        return True
    try:
        value = float(explicit)
    except ValueError:
        return False
    return math.isfinite(value) and abs(value - round(done / total * 100, 1)) <= 0.11


def _stage_from_match(
    match: re.Match[str], *, path: str, line_number: int, heading: str, line: str
) -> EvidenceStage | None:
    done = int(match.group("done"))
    total = int(match.group("total"))
    if total <= 0 or done < 0 or done > total:
        raise BootstrapClosed("contradictory_counts", f"{path}#L{line_number}")
    explicit = match.groupdict().get("pct")
    tail = match.groupdict().get("tail") or ""
    if explicit is None:
        pct_match = PERCENT.search(tail)
        explicit = pct_match.group("pct") if pct_match else None
    if explicit is not None and not _percent_matches(done, total, explicit):
        raise BootstrapClosed("contradictory_percentage", f"{path}#L{line_number}")

    label = match.groupdict().get("label") or heading
    context = f"{heading} {label} {tail} {line}".lower()
    if not any(term in context for term in COMPLETION_TERMS):
        return None
    label = _clean_label(label or heading)
    if label.lower() in {"current state", "status", "progress", "completion"} and heading:
        label = _clean_label(heading)
    return EvidenceStage(label, done, total, f"{path}#L{line_number}")


def extract_stages(text: str, path: str) -> list[EvidenceStage]:
    """Extract explicit bounded completion counts from one authority document."""
    heading = ""
    candidates: list[EvidenceStage] = []
    for number, line in enumerate(text.splitlines(), 1):
        heading_match = HEADING.match(line)
        if heading_match:
            heading = _clean_label(heading_match.group(2))
            continue
        for pattern in (TABLE_COUNT, LABELLED_OF, LABELLED_SLASH):
            match = pattern.search(line)
