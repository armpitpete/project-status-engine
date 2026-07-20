#!/usr/bin/env python3
"""Read and route owner-only completion-authority exception records.

Exception records live on the automation exception branch in each repository.
They are enriched from an identity-free resolution policy and never exposed
through the public status view.
"""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 2
EXCEPTION_BRANCH = "automation/project-status-bootstrap-exception"
EXCEPTION_PATH = ".project/bootstrap-exception.json"
REGISTRY_PATH = "config/portfolio-authority-registry.json"
RESOLUTION_REGISTRY_REFERENCE = "config/authority-resolution-lanes.json"
RESOLUTION_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / RESOLUTION_REGISTRY_REFERENCE
)
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
LANE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
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
RESOLUTION_FIELDS = {
    "resolution_lane",
    "owner_decision_required",
    "required_action",
    "template_kind",
}


class AuthorityExceptionError(ValueError):
    """Raised when an exception or resolution-policy record is invalid."""


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityExceptionError(f"{field} must be a non-empty string")
    return value.strip()


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthorityExceptionError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityExceptionError(f"{label} is unreadable") from exc


def load_resolution_registry(
    path: Path = RESOLUTION_REGISTRY_PATH,
) -> dict[str, dict[str, Any]]:
    document = _load_json(path, "authority resolution registry")
    if not isinstance(document, dict):
        raise AuthorityExceptionError("authority resolution registry must be an object")
    if set(document) != {"schema_version", "registry_type", "lanes"}:
        raise AuthorityExceptionError("authority resolution registry fields are invalid")
    if document.get("schema_version") != 1:
        raise AuthorityExceptionError("authority resolution registry schema_version must be 1")
    if document.get("registry_type") != "authority-resolution-policy":
        raise AuthorityExceptionError("authority resolution registry type is invalid")
    lanes = document.get("lanes")
    if not isinstance(lanes, dict) or set(lanes) != PRIMARY_CODE_SET:
        raise AuthorityExceptionError("authority resolution registry must cover all primary codes")
    result: dict[str, dict[str, Any]] = {}
    for code in PRIMARY_CODES:
        raw = lanes.get(code)
        if not isinstance(raw, dict) or set(raw) != RESOLUTION_FIELDS:
            raise AuthorityExceptionError(f"resolution lane fields are invalid for {code}")
        lane = _required_text(raw.get("resolution_lane"), f"{code}.resolution_lane")
        if not LANE_ID.fullmatch(lane):
            raise AuthorityExceptionError(f"{code}.resolution_lane is invalid")
        owner_required = raw.get("owner_decision_required")
        if not isinstance(owner_required, bool):
            raise AuthorityExceptionError(
                f"{code}.owner_decision_required must be true or false"
            )
        result[code] = {
            "resolution_lane": lane,
            "owner_decision_required": owner_required,
            "required_action": _required_text(
                raw.get("required_action"), f"{code}.required_action"
            ),
            "template_kind": _required_text(
                raw.get("template_kind"), f"{code}.template_kind"
            ),
        }
    return result


RESOLUTION_LANES = load_resolution_registry()


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
        code = exception["code"]
        policy = RESOLUTION_LANES[code]
        queue.append(
            {
                "name": project.get("name") or project.get("full_name") or "Unknown",
                "full_name": project.get("full_name") or project.get("name") or "Unknown",
                "private": bool(project.get("private")),
                "url": project.get("url") or "",
                "code": code,
                "project_type": exception["project_type"],
                "detail": exception["detail"],
                "source_sha": exception["source_sha"],
                "resolution_lane": policy["resolution_lane"],
                "owner_decision_required": policy["owner_decision_required"],
                "required_action": policy["required_action"],
                "template_kind": policy["template_kind"],
            }
        )
    return sorted(queue, key=lambda item: (item["code"], item["full_name"]))


def summary_for(queue: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts = {code: 0 for code in PRIMARY_CODES}
    lane_counts = {
        policy["resolution_lane"]: 0
        for policy in RESOLUTION_LANES.values()
    }
    total = 0
    owner_decisions = 0
    for item in queue:
        code = item.get("code")
        if code not in PRIMARY_CODE_SET:
            raise AuthorityExceptionError("queue contains an unregistered primary exception")
        expected = RESOLUTION_LANES[code]
        if item.get("resolution_lane") != expected["resolution_lane"]:
            raise AuthorityExceptionError("queue contains an invalid resolution lane")
        counts[code] += 1
        lane_counts[expected["resolution_lane"]] += 1
        total += 1
        if bool(item.get("owner_decision_required")):
            owner_decisions += 1
    return {
        "total": total,
        "owner_decision_required": owner_decisions,
        "counts": counts,
        "lane_counts": dict(sorted(lane_counts.items())),
    }


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
    lines.extend(
        [
            "| Repository | Primary exception | Resolution lane | Owner decision | Required action |",
            "|---|---|---|---:|---|",
        ]
    )
    for item in queue:
        action = str(item.get("required_action") or "").replace("|", "\\|").replace("\n", " ")
        decision = "yes" if item.get("owner_decision_required") else "no"
        lines.append(
            f"| `{item['full_name']}` | `{item['code']}` | `{item['resolution_lane']}` | {decision} | {action} |"
        )
    return "\n".join(lines).strip() + "\n"


def _template_for(item: dict[str, Any]) -> list[str]:
    kind = item["template_kind"]
    if kind == "new_authority_record":
        return [
            "Suggested file: `docs/PROJECT_AUTHORITY.md`",
            "",
            "```markdown",
            "# Project Authority",
            "",
            "## Completion scope",
            "[Human-approved bounded project scope]",
            "",
            "## Bounded completion evidence",
            "- [Stage label]: [completed] of [total] complete",
            "```",
        ]
    if kind == "bounded_evidence_addition":
        return [
            "Add to one existing authority or status document:",
            "",
            "```markdown",
            "## Bounded completion evidence",
            "- [Stage label]: [completed] of [total] complete",
            "```",
            "",
            "The values must be human-approved; do not derive them from activity or file counts.",
        ]
    if kind == "project_type_decision":
        return [
            "Record one owner decision:",
            "",
            "```text",
            "Project type: manuscript | website | software | hardware | music | documentation | mixed",
            "Decision evidence: [why this type is authoritative]",
            "```",
        ]
    if kind == "evidence_reconciliation":
        return [
            "Reconciliation record:",
            "",
            "```text",
            "Conflicting sources: [paths and statements]",
            "Authoritative source retained: [path]",
            "Superseded statement removed or corrected: [path and change]",
            "Approved completed/total evidence: [stage and counts]",
            "```",
        ]
    if kind == "repository_lifecycle_decision":
        return [
            "Record one owner lifecycle decision:",
            "",
            "```text",
            "Decision: active | archive | excluded",
            "Reason: [bounded rationale]",
            "Completion onboarding required: yes | no",
            "```",
        ]
    if kind == "readme_marker_decision":
        return [
            "Authorise one exact README marker correction:",
            "",
            "```text",
            "Human-written bytes to preserve: [range or hash]",
            "Marker pair to retain or create: exactly one ordered pair",
            "Duplicate/partial/reversed markers to remove: [exact locations]",
            "```",
        ]
    if kind == "contract_repair_review":
        return [
            "Run the controlled completion-contract repair lane. When it remains unresolved, add or reconcile explicit bounded authority evidence rather than editing generated percentages.",
        ]
    raise AuthorityExceptionError(f"unknown resolution template kind: {kind}")


def render_resolution_templates(data: dict[str, Any]) -> str:
    queue = data.get("authority_exception_queue") or []
    lines = [
        "# Authority and Owner-Decision Templates",
        "",
        "Generated owner-only prompts. Placeholder values require human approval and are never filled from repository activity.",
        "",
    ]
    if not queue:
        lines.append("No authority or owner-decision templates are currently required.")
        return "\n".join(lines).strip() + "\n"
    for item in queue:
        lines.extend(
            [
                f"## {item['full_name']}",
                "",
                f"- Primary exception: `{item['code']}`",
                f"- Resolution lane: `{item['resolution_lane']}`",
                f"- Owner decision required: `{'yes' if item['owner_decision_required'] else 'no'}`",
                f"- Required action: {item['required_action']}",
                "",
                *_template_for(item),
                "",
            ]
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
            f"<td><code>{html.escape(str(item.get('resolution_lane') or ''))}</code></td>"
            f"<td>{'yes' if item.get('owner_decision_required') else 'no'}</td>"
            f"<td>{html.escape(str(item.get('required_action') or ''))}</td>"
            "</tr>"
            for item in queue
        )
        body = (
            "<div class=\"table-wrap\"><table><thead><tr>"
            "<th>Repository</th><th>Primary exception</th><th>Resolution lane</th>"
            "<th>Owner decision</th><th>Required action</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    return (
        "<section id=\"authority-exceptions\">"
        "<h2>Completion authority exceptions</h2>"
        "<p>Owner-only work queue generated from repository exception branches.</p>"
        f"{body}</section>"
    )
