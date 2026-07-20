#!/usr/bin/env python3
"""Validate generated output contracts, authority alignment and privacy separation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import completion_status  # noqa: E402
import live_status  # noqa: E402
import resolve_readme_pilots as resolver  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "public"
PRIVATE_DIR = ROOT / "private-build"
INTERNAL_DIR = ROOT / "internal-build"
PROGRESS_PATH = ROOT / ".project" / "progress.json"
POLICY_PATH = ROOT / "config" / "readme-sync-policy.json"

PUBLIC_FILES = {
    "index.html",
    "status.json",
    "project-status.md",
    "completion-status.md",
    "home-pc-tasks.md",
}
PRIVATE_FILES = {
    "index.html",
    "projects.html",
    "completion.html",
    "exceptions.html",
    "operations.html",
    "status.json",
    "project-status.md",
    "completion-status.md",
    "authority-exceptions.md",
    "authority-resolution-templates.md",
    "home-pc-tasks.md",
}


class ValidationError(RuntimeError):
    """Raised when generated output does not satisfy the committed contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"unreadable JSON output: {path}") from exc
    if not isinstance(document, dict):
        raise ValidationError(f"JSON output is not an object: {path}")
    return document


def validate_required_files() -> None:
    for name in sorted(PUBLIC_FILES):
        path = PUBLIC_DIR / name
        require(path.is_file() and path.stat().st_size > 0, f"missing public output: {name}")
    for name in sorted(PRIVATE_FILES):
        path = PRIVATE_DIR / name
        require(path.is_file() and path.stat().st_size > 0, f"missing private output: {name}")
    internal = INTERNAL_DIR / "completion-status.json"
    require(internal.is_file() and internal.stat().st_size > 0, "missing internal completion output")
    for forbidden in (
        PUBLIC_DIR / "private-build",
        PUBLIC_DIR / "private",
        PUBLIC_DIR / "internal-build",
        PUBLIC_DIR / "completion-status.json",
        PUBLIC_DIR / "authority-exceptions.md",
        PUBLIC_DIR / "authority-resolution-templates.md",
    ):
        require(not forbidden.exists(), f"private/internal output crossed public boundary: {forbidden}")


def validate_common(document: dict[str, Any], expected_view: str) -> None:
    require(document.get("schema_version") == live_status.OUTPUT_SCHEMA_VERSION, f"invalid schema_version for {expected_view}")
    require(document.get("activity_score_version") == live_status.ACTIVITY_SCORE_VERSION, f"invalid activity score version for {expected_view}")
    require(document.get("view") == expected_view, f"invalid view: {expected_view}")
    require(document.get("scan_state") in {"complete", "partial"}, f"invalid scan state: {expected_view}")
    require(isinstance(document.get("generated_at"), str) and bool(document["generated_at"]), f"missing generated_at: {expected_view}")
    require(isinstance(document.get("source_repository_count"), int) and document["source_repository_count"] >= 0, f"invalid source repository count: {expected_view}")
    health = document.get("scan_health")
    require(isinstance(health, dict), f"missing scan health: {expected_view}")
    for field in ("request_count", "failure_count"):
        require(isinstance(health.get(field), int) and health[field] >= 0, f"invalid {field}: {expected_view}")
    for field in ("rate_limit_remaining", "rate_limit_limit"):
        value = health.get(field)
        require(value is None or (isinstance(value, int) and value >= 0), f"invalid {field}: {expected_view}")
    reset_at = health.get("rate_limit_reset_at")
    require(reset_at is None or isinstance(reset_at, str), f"invalid rate_limit_reset_at: {expected_view}")


def repository_map(internal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    repositories = internal.get("repositories")
    require(isinstance(repositories, list), "internal repositories missing")
    result: dict[str, dict[str, Any]] = {}
    for item in repositories:
        require(isinstance(item, dict), "internal repository record is invalid")
        full_name = item.get("full_name")
        require(isinstance(full_name, str) and "/" in full_name, "internal repository identity is invalid")
        digest = hashlib.sha256(full_name.encode("utf-8")).hexdigest()
        require(digest not in result, "duplicate internal repository identity")
        result[digest] = item
    return result


def validate_runtime_authority(internal: dict[str, Any]) -> None:
    repositories = repository_map(internal)
    runtime_name = os.environ.get("GITHUB_REPOSITORY", "armpitpete/project-status-engine")
    runtime_hash = hashlib.sha256(runtime_name.encode("utf-8")).hexdigest()
    require(runtime_hash in repositories, "runtime repository absent from internal dataset")
    runtime_record = repositories[runtime_hash]
    runtime_completion = runtime_record.get("completion") or {}
    local_progress = completion_status.validate_progress(read_json(PROGRESS_PATH))

    require(runtime_record.get("private") is False, "runtime repository unexpectedly private")
    require(runtime_completion.get("state") == "valid", "runtime completion is not valid")
    require(runtime_completion.get("authority") == local_progress.get("authority"), "runtime authority differs from local contract")
    require(runtime_completion.get("project_type") == local_progress.get("project_type"), "runtime project type differs from local contract")
    require(runtime_completion.get("overall_percentage") is None, "runtime overall percentage unexpectedly enabled")
    require(local_progress.get("overall_percentage") is None, "local overall percentage unexpectedly enabled")

    live_stages = {
        stage["id"]: stage["percentage"]
        for stage in runtime_completion.get("stages", [])
    }
    local_stages = {
        stage["id"]: stage["percentage"] for stage in local_progress["stages"]
    }
    require(live_stages == local_stages, "runtime completion stages differ from the committed authority contract")


def validate_policy(internal_path: Path, internal: dict[str, Any]) -> None:
    resolved = resolver.resolve_policy(internal_path, POLICY_PATH)
    expected = sorted(
        hashlib.sha256(item["full_name"].encode("utf-8")).hexdigest()
        for item in internal["repositories"]
        if item.get("completion", {}).get("state") == "valid"
    )
    require(resolved.get("target_hashes") == expected, "all-valid policy did not resolve every valid completion contract")


def validate_exception_queues(internal: dict[str, Any], private: dict[str, Any]) -> None:
    expected = sorted(
        item["full_name"]
        for item in internal["repositories"]
        if item.get("authority_exception")
    )
    internal_queue = internal.get("authority_exception_queue") or []
    private_queue = private.get("authority_exception_queue") or []
    require(sorted(item["full_name"] for item in internal_queue) == expected, "internal exception queue is incomplete")
    require(sorted(item["full_name"] for item in private_queue) == expected, "private exception queue is incomplete")
    require(internal.get("authority_exception_summary") == private.get("authority_exception_summary"), "private/internal exception summaries differ")
    require(internal["authority_exception_summary"].get("total") == len(expected), "exception total is invalid")
    for item in internal_queue:
        require(bool(item.get("resolution_lane")), "exception resolution lane missing")
        require(bool(item.get("required_action")), "exception required action missing")
        require(isinstance(item.get("owner_decision_required"), bool), "exception owner decision flag invalid")


def validate_structural_redaction(
    internal: dict[str, Any], public: dict[str, Any]
) -> None:
    require("authority_exception_queue" not in public, "public exception queue leaked")
    require("authority_exception_summary" not in public, "public exception summary leaked")
    public_projects = public.get("projects")
    internal_projects = internal.get("repositories")
    require(isinstance(public_projects, list), "public projects missing")
    require(len(public_projects) == len(internal_projects), "public pool differs from internal pool")

    for rank, (internal_record, public_record) in enumerate(
        zip(internal_projects, public_projects, strict=True), 1
    ):
        require(public_record.get("rank") == rank, "public rank differs from internal order")
        require("authority_exception" not in public_record, "public project contains authority exception")
        if internal_record.get("private"):
            placeholder = f"Private project #{rank}"
            require(public_record.get("private") is True, "private placeholder lost privacy flag")
            require(public_record.get("name") == placeholder, "private project name leaked")
            require(public_record.get("full_name") == placeholder, "private full name leaked")
            require(public_record.get("url") == "", "private URL leaked")
            require(public_record.get("open_issues") == [], "private issues leaked")
            require(public_record.get("open_prs") == [], "private PRs leaked")
            require(public_record.get("latest_commit") is None, "private commit leaked")
            require(public_record.get("recent_commit_count") == 0, "private commit count leaked")
            require("completion" not in public_record, "private completion leaked")
        else:
            require(public_record.get("private") is False, "public project marked private")
            require(public_record.get("full_name") == internal_record.get("full_name"), "public repository identity mismatch")

    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PUBLIC_DIR.rglob("*")
        if path.is_file()
    )
    for record in internal_projects:
        if not record.get("private"):
            continue
        for value in (record.get("full_name") or "", record.get("url") or ""):
            if value:
                require(value not in public_text, "private identity appeared in public output")


def validate_private_navigation() -> None:
    expected = {
        "index.html": "Overview",
        "projects.html": "Projects",
        "completion.html": "Completion",
        "exceptions.html": "Exceptions",
        "operations.html": "Operations",
    }
    for filename, label in expected.items():
        text = (PRIVATE_DIR / filename).read_text(encoding="utf-8")
        require("aria-label='Owner dashboard'" in text, f"private navigation missing: {filename}")
        require("Skip to content" in text, f"skip link missing: {filename}")
        require(label in text, f"page label missing: {filename}")
    overview = (PRIVATE_DIR / "index.html").read_text(encoding="utf-8")
    require("Exception evidence details" not in overview, "full exception detail remains on compact overview")
    require("Open the complete exception queue" in overview, "exception detail link missing from overview")


def validate() -> None:
    validate_required_files()
    public_path = PUBLIC_DIR / "status.json"
    private_path = PRIVATE_DIR / "status.json"
    internal_path = INTERNAL_DIR / "completion-status.json"
    public = read_json(public_path)
    private = read_json(private_path)
    internal = read_json(internal_path)

    validate_common(public, "public")
    validate_common(private, "private")
    validate_common(internal, "internal-owner-completion")
    require(public.get("source_repository_count") == internal.get("source_repository_count"), "public/internal source counts differ")
    require(private.get("source_repository_count") == internal.get("source_repository_count"), "private/internal source counts differ")
    require(private.get("project_count") <= 5, "private dashboard exceeds top-five boundary")

    validate_runtime_authority(internal)
    validate_policy(internal_path, internal)
    validate_exception_queues(internal, private)
    validate_structural_redaction(internal, public)
    validate_private_navigation()


def main() -> int:
    try:
        validate()
    except (ValidationError, completion_status.ProgressValidationError, resolver.ResolutionClosed) as exc:
        print(f"generated-output validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Verified output schemas, runtime completion authority, all-valid policy, "
        "owner-wide exception queues, compact private navigation and structural public redaction."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
