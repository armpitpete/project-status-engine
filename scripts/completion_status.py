#!/usr/bin/env python3
"""Validate and render explicit repository completion authority.

Completion is read only from ``.project/progress.json``. Repository activity,
commit counts, issues, pull requests, and filenames are never used to infer a
percentage.
"""
from __future__ import annotations

import base64
import html
import json
import math
import os
import re
from typing import Any, Callable

SCHEMA_VERSION = 1
PROGRESS_PATH = os.getenv("STATUS_PROGRESS_PATH", ".project/progress.json")
STAGE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

TOP_LEVEL_FIELDS = {"schema_version", "authority", "project_type", "note", "stages", "overall"}
STAGE_FIELDS = {"id", "label", "completed", "total", "weight", "evidence"}
OVERALL_FIELDS = {"enabled"}


class ProgressValidationError(ValueError):
    """Raised when a progress authority document is structurally invalid."""


def _reject_unknown(mapping: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ProgressValidationError(f"{field} contains unknown fields: {', '.join(unknown)}")


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProgressValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _required_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProgressValidationError(f"{field} must be an integer")
    return value


def _optional_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProgressValidationError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ProgressValidationError(f"{field} must be finite")
    if number < 0:
        raise ProgressValidationError(f"{field} must not be negative")
    return number


def validate_progress(document: Any) -> dict[str, Any]:
    """Validate a v1 document and return deterministic calculated values."""
    if not isinstance(document, dict):
        raise ProgressValidationError("document must be a JSON object")
    _reject_unknown(document, TOP_LEVEL_FIELDS, "document")

    if document.get("schema_version") != SCHEMA_VERSION:
        raise ProgressValidationError(f"schema_version must be {SCHEMA_VERSION}")

    authority = _required_text(document.get("authority"), "authority")
    stages_raw = document.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise ProgressValidationError("stages must be a non-empty array")

    seen: set[str] = set()
    stages: list[dict[str, Any]] = []
    for index, raw in enumerate(stages_raw):
        prefix = f"stages[{index}]"
        if not isinstance(raw, dict):
            raise ProgressValidationError(f"{prefix} must be an object")
        _reject_unknown(raw, STAGE_FIELDS, prefix)

        stage_id = _required_text(raw.get("id"), f"{prefix}.id")
        if not STAGE_ID.fullmatch(stage_id):
            raise ProgressValidationError(
                f"{prefix}.id must use lowercase letters, numbers, '-' or '_'"
            )
        if stage_id in seen:
            raise ProgressValidationError(f"duplicate stage id: {stage_id}")
        seen.add(stage_id)

        label = _required_text(raw.get("label"), f"{prefix}.label")
        completed = _required_int(raw.get("completed"), f"{prefix}.completed")
        total = _required_int(raw.get("total"), f"{prefix}.total")
        if total <= 0:
            raise ProgressValidationError(f"{prefix}.total must be greater than zero")
        if completed < 0:
            raise ProgressValidationError(f"{prefix}.completed must not be negative")
        if completed > total:
            raise ProgressValidationError(f"{prefix}.completed must not exceed total")

        weight = _optional_number(raw.get("weight"), f"{prefix}.weight")
        percentage = round(completed / total * 100, 1)
        state = (
            "complete"
            if completed == total
            else "not_started"
            if completed == 0
            else "in_progress"
        )
        stage = {
            "id": stage_id,
            "label": label,
            "completed": completed,
            "total": total,
            "percentage": percentage,
            "state": state,
            "weight": weight,
        }
        if "evidence" in raw:
            stage["evidence"] = _required_text(raw["evidence"], f"{prefix}.evidence")
        stages.append(stage)

    if "overall" in document:
        overall_raw = document["overall"]
        if not isinstance(overall_raw, dict):
            raise ProgressValidationError("overall must be an object")
    else:
        overall_raw = {}
    _reject_unknown(overall_raw, OVERALL_FIELDS, "overall")

    enabled = overall_raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProgressValidationError("overall.enabled must be true or false")

    overall_percentage: float | None = None
    if enabled:
        missing = [stage["id"] for stage in stages if stage["weight"] is None]
        if missing:
            raise ProgressValidationError(
                "overall is enabled but stages are missing weights: " + ", ".join(missing)
            )
        weight_total = sum(float(stage["weight"]) for stage in stages)
        if abs(weight_total - 100.0) > 0.001:
            raise ProgressValidationError(
                f"stage weights must total 100; found {weight_total:g}"
            )
        overall_percentage = round(
            sum(
                stage["percentage"] * float(stage["weight"])
                for stage in stages
            )
            / 100,
            1,
        )

    result = {
        "configured": True,
        "state": "valid",
        "schema_version": SCHEMA_VERSION,
        "authority": authority,
        "overall_enabled": enabled,
        "overall_percentage": overall_percentage,
        "stages": stages,
    }
    if "project_type" in document:
        result["project_type"] = _required_text(document["project_type"], "project_type")
    if "note" in document:
        result["note"] = _required_text(document["note"], "note")
    return result


def _reject_json_constant(value: str) -> None:
    raise ProgressValidationError(f"progress file contains non-standard JSON constant: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgressValidationError(f"progress file contains duplicate key: {key}")
        result[key] = value
    return result


def decode_contents_payload(payload: Any) -> Any:
    """Decode a GitHub Contents API file response as strict JSON."""
    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise ProgressValidationError("progress path is not a file")
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise ProgressValidationError("progress file must be returned as base64 content")
    try:
        raw = base64.b64decode(
            payload["content"].replace("\n", ""), validate=True
        ).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise ProgressValidationError("progress file is not valid UTF-8 base64") from exc
    try:
        return json.loads(
            raw,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_object_without_duplicates,
        )
    except ProgressValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ProgressValidationError(
            f"progress file is not valid JSON: line {exc.lineno}, column {exc.colno}"
        ) from exc


def not_configured() -> dict[str, Any]:
    return {
        "configured": False,
        "state": "not_configured",
        "source_path": PROGRESS_PATH,
        "overall_enabled": False,
        "overall_percentage": None,
        "stages": [],
    }


def invalid(message: str) -> dict[str, Any]:
    return {
        "configured": True,
        "state": "invalid",
        "source_path": PROGRESS_PATH,
        "overall_enabled": False,
        "overall_percentage": None,
        "stages": [],
        "error": message,
    }


def fetch_repository_progress(
    repo_full_name: str,
    getter: Callable[[str, dict[str, str | int] | None], Any],
) -> tuple[dict[str, Any], str | None]:
    """Fetch one repository's explicit progress authority."""
    path = f"/repos/{repo_full_name}/contents/{PROGRESS_PATH}"
    try:
        payload = getter(path, None)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "GitHub API error 404" in message or " 404" in message:
            return not_configured(), None
        return (
            invalid("progress authority could not be read"),
            f"completion scan failed: {message}",
        )

    try:
        result = validate_progress(decode_contents_payload(payload))
    except ProgressValidationError as exc:
        message = str(exc)
        return invalid(message), f"invalid {PROGRESS_PATH}: {message}"
    result["source_path"] = PROGRESS_PATH
    return result, None


def summary_for(
    projects: list[dict[str, Any]], *, include_private: bool
) -> dict[str, int]:
    summary = {
        "valid": 0,
        "invalid": 0,
        "not_configured": 0,
        "redacted": 0,
        "overall_available": 0,
    }
    for project in projects:
        if project.get("private") and not include_private:
            summary["redacted"] += 1
            continue
        project_completion = project.get("completion") or not_configured()
        state = project_completion.get("state", "not_configured")
        if state not in {"valid", "invalid", "not_configured"}:
            state = "invalid"
        summary[state] += 1
        if (
            state == "valid"
            and project_completion.get("overall_percentage") is not None
        ):
            summary["overall_available"] += 1
    return summary


def _project_completion(
    project: dict[str, Any], *, include_private: bool
) -> tuple[str, str, str]:
    if project.get("private") and not include_private:
        return "Redacted", "—", "Private repository completion is not published."
    project_completion = project.get("completion") or not_configured()
    state = project_completion.get("state")
    if state == "not_configured":
        return "Not configured", "—", f"Add {PROGRESS_PATH}."
    if state == "invalid":
        return (
            "Invalid",
            "—",
            str(project_completion.get("error") or "Invalid completion authority."),
        )
    overall = project_completion.get("overall_percentage")
    overall_text = "—" if overall is None else f"{overall:.1f}%"
    stages = project_completion.get("stages") or []
    stage_text = "; ".join(
        f"{stage['label']} {stage['completed']}/{stage['total']} "
        f"({stage['percentage']:.1f}%)"
        for stage in stages
    )
    return "Valid", overall_text, stage_text or "No stages."


def render_html(data: dict[str, Any]) -> str:
    include_private = data.get("view") == "private"
    rows = []
    for project in data.get("projects", []):
        state, overall, detail = _project_completion(
            project, include_private=include_private
        )
        name = html.escape(
            str(project.get("full_name") or project.get("name") or "Unknown"),
            quote=True,
        )
        rows.append(
            f"<tr><td>{name}</td><td>{html.escape(state)}</td>"
            f"<td>{html.escape(overall)}</td><td>{html.escape(detail)}</td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan='4'>No repositories found.</td></tr>"
    return (
        "<section class='panel'><h2>Completion authority</h2>"
        "<p class='muted'>Percentages come only from validated "
        ".project/progress.json files; activity is never treated as completion.</p>"
        "<div style='overflow-x:auto'><table class='heat'><thead><tr>"
        "<th>Project</th><th>Authority</th><th>Overall</th><th>Stages</th>"
        f"</tr></thead><tbody>{body}</tbody></table></div></section>"
    )


def render_markdown(data: dict[str, Any]) -> str:
    include_private = data.get("view") == "private"
    lines = [
        "# Completion Status",
        "",
        "Percentages are calculated only from validated "
        "`.project/progress.json` authority files.",
        "Repository activity is not completion.",
        "",
        "| Repository | Authority | Overall | Stage detail |",
        "|---|---|---:|---|",
    ]
    for project in data.get("projects", []):
        state, overall, detail = _project_completion(
            project, include_private=include_private
        )
        name = str(
            project.get("full_name") or project.get("name") or "Unknown"
        ).replace("|", "\\|")
        detail = detail.replace("|", "\\|")
        lines.append(f"| {name} | {state} | {overall} | {detail} |")
    if not data.get("projects"):
        lines.append("| _None_ | — | — | — |")
    return "\n".join(lines).strip() + "\n"
