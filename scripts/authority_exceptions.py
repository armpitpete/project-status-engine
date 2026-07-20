#!/usr/bin/env python3
"""Read and render owner-only completion-authority exception records.

Exception records live on the automation exception branch in each repository.
They are never exposed through the public status view.
"""
from __future__ import annotations

import base64
import html
import json
import re
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 2
EXCEPTION_BRANCH = "automation/project-status-bootstrap-exception"
EXCEPTION_PATH = ".project/bootstrap-exception.json"
REGISTRY_PATH = "config/portfolio-authority-registry.json"
PRIMARY_CODES = (
    "missing_completion_contract",
    "missing_authoritative_source",
    "missing_readme_marker",
    "ambiguous_project_type",
    "contradictory_evidence",
    "no_completion_evidence",
    "inactive_repository_candidate",
)
PRIMARY_CODE_SET = frozenset(PRIMARY_CODES)
SHA = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_FIELDS = {
    "schema_version",
    "status",
    "source_sha",
    "project_type",
    "code",
    "registry",
    "detail",
    "accepted_evidence",
}


class AuthorityExceptionError(ValueError):
    """Raised when an exception record is structurally invalid."""


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityExceptionError(f"{field} must be a non-empty string")
    return value.strip()


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityExceptionError(f"exception record contains duplicate key: {key}")
        result[key] = value
    return result


def decode_contents_payload(payload: Any) -> Any:
    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise AuthorityExceptionError("exception path is not a file")
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise AuthorityExceptionError("exception record must be returned as base64 content")
    try:
        raw = base64.b64decode(
            payload["content"].replace("\n", ""), validate=True
        ).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise AuthorityExceptionError("exception record is not valid UTF-8 base64") from exc
    try:
        return json.loads(raw, object_pairs_hook=_object_without_duplicates)
    except AuthorityExceptionError:
        raise
    except json.JSONDecodeError as exc:
        raise AuthorityExceptionError(
            f"exception record is not valid JSON: line {exc.lineno}, column {exc.colno}"
        ) from exc


def validate_exception(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise AuthorityExceptionError("exception record must be a JSON object")
    unknown = sorted(set(document) - ALLOWED_FIELDS)
    if unknown:
        raise AuthorityExceptionError(
            "exception record contains unknown fields: " + ", ".join(unknown)
        )
    if set(document) != ALLOWED_FIELDS:
        missing = sorted(ALLOWED_FIELDS - set(document))
        raise AuthorityExceptionError(
            "exception record is missing fields: " + ", ".join(missing)
        )
    if document.get("schema_version") != SCHEMA_VERSION:
        raise AuthorityExceptionError(f"schema_version must be {SCHEMA_VERSION}")
    if document.get("status") != "requires_authority":
        raise AuthorityExceptionError("status must be requires_authority")
    source_sha = _required_text(document.get("source_sha"), "source_sha")
    if not SHA.fullmatch(source_sha):
        raise AuthorityExceptionError("source_sha must be a 40-character lowercase Git SHA")
    project_type = _required_text(document.get("project_type"), "project_type")
    code = _required_text(document.get("code"), "code")
    if code not in PRIMARY_CODE_SET:
        raise AuthorityExceptionError("code must be a registered primary exception")
    if document.get("registry") != REGISTRY_PATH:
        raise AuthorityExceptionError(f"registry must be {REGISTRY_PATH}")
    detail = _required_text(document.get("detail"), "detail")
    accepted_evidence = _required_text(
        document.get("accepted_evidence"), "accepted_evidence"
    )
    return {
        "code": code,
        "project_type": project_type,
        "detail": detail,
        "source_sha": source_sha,
        "source_branch": EXCEPTION_BRANCH,
        "source_path": EXCEPTION_PATH,
        "accepted_evidence": accepted_evidence,
    }


def fetch_repository_exception(
    repo_full_name: str,
    getter: Callable[[str, dict[str, str | int] | None], Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch one repository's private exception record, treating 404 as no exception."""
    path = f"/repos/{repo_full_name}/contents/{EXCEPTION_PATH}"
    try:
        payload = getter(path, {"ref": EXCEPTION_BRANCH})
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "GitHub API error 404" in message or " 404" in message:
            return None, None
        return None, f"authority exception scan failed: {message}"
    try:
        return validate_exception(decode_contents_payload(payload)), None
    except AuthorityExceptionError as exc:
        return None, f"invalid {EXCEPTION_PATH}: {exc}"


def queue_for(projects: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for project in projects:
        exception = project.get("authority_exception")
        if not isinstance(exception, dict):
            continue
        queue.append(
            {
                "name": project.get("name") or project.get("full_name") or "Unknown",
                "full_name": project.get("full_name") or project.get("name") or "Unknown",
                "private": bool(project.get("private")),
                "url": project.get("url") or "",
                "code": exception["code"],
                "project_type": exception["project_type"],
                "detail": exception["detail"],
                "source_sha": exception["source_sha"],
            }
        )
    return sorted(queue, key=lambda item: (item["code"], item["full_name"]))


def summary_for(queue: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts = {code: 0 for code in PRIMARY_CODES}
    total = 0
    for item in queue:
        code = item.get("code")
        if code not in PRIMARY_CODE_SET:
            raise AuthorityExceptionError("queue contains an unregistered primary exception")
        counts[code] += 1
        total += 1
    return {"total": total, "counts": counts}


def render_markdown(data: dict[str, Any]) -> str:
    queue = data.get("authority_exception_queue") or []
    lines = [
        "# Completion Authority Exceptions",
        "",
        "Owner-only work queue generated from repository exception branches.",
        "",
    ]
    if not queue:
        lines.append("No completion-authority exceptions are currently recorded.")
        return "\n".join(lines).strip() + "\n"
    lines.extend(["| Repository | Primary exception | Detail |", "|---|---|---|"])
    for item in queue:
        detail = str(item.get("detail") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{item['full_name']}` | `{item['code']}` | {detail} |"
        )
    return "\n".join(lines).strip() + "\n"


def render_html(data: dict[str, Any]) -> str:
    queue = data.get("authority_exception_queue") or []
    if not queue:
        body = "<p>No completion-authority exceptions are currently recorded.</p>"
    else:
        rows = "".join(
            "<tr>"
            f"<td><a href=\"{html.escape(str(item.get('url') or ''), quote=True)}\">"
            f"{html.escape(str(item.get('full_name') or 'Unknown'))}</a></td>"
            f"<td><code>{html.escape(str(item.get('code') or ''))}</code></td>"
            f"<td>{html.escape(str(item.get('detail') or ''))}</td>"
            "</tr>"
            for item in queue
        )
        body = (
            "<div class=\"table-wrap\"><table><thead><tr>"
            "<th>Repository</th><th>Primary exception</th><th>Detail</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    return (
        "<section id=\"authority-exceptions\">"
        "<h2>Completion authority exceptions</h2>"
        "<p>Owner-only work queue generated from repository exception branches.</p>"
        f"{body}</section>"
    )
