#!/usr/bin/env python3
"""Synchronise generated README completion sections from the trusted internal dataset.

Completion values are consumed exactly as emitted by
``internal-build/completion-status.json``. This module never calculates a
percentage and never writes directly to a repository default branch.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

START_MARKER = b"<!-- AUTO:PROJECT-COMPLETION:START -->"
END_MARKER = b"<!-- AUTO:PROJECT-COMPLETION:END -->"
SYNC_BRANCH = "automation/readme-sync"
README_PATH = "README.md"
PR_TITLE = "Synchronise generated README completion"
PR_BODY = (
    "This pull request updates only the explicitly marked generated completion "
    "section in README.md from the validated internal completion dataset. "
    "Human-written README content is preserved byte-for-byte. No readiness or "
    "authority decision is made by this automation."
)
ALLOWED_COMPLETION_STATES = {"valid"}
DATASET_VIEW = "internal-owner-completion"


class SyncClosed(RuntimeError):
    """A safe failure that must not result in a repository write."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ApiFailure(RuntimeError):
    """Sanitised API failure that does not expose URLs, names, tokens or bodies."""

    def __init__(self, operation: str, status: int | None = None):
        code = f"api_{operation}"
        if status is not None:
            code += f"_{status}"
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Target:
    target_id: str
    full_name: str
    private: bool
    completion: dict[str, Any]


@dataclass(frozen=True)
class SyncResult:
    target_id: str
    action: str


@dataclass(frozen=True)
class SyncPlan:
    target: Target
    default_branch: str
    owner: str
    source_sha: str
    default_sha: str
    desired: bytes
    changed: bool
    existing_pr_number: int | None


def target_id(full_name: str) -> str:
    return hashlib.sha256(full_name.encode("utf-8")).hexdigest()


def load_allowlist(path: Path) -> set[str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncClosed("allowlist_unreadable") from exc
    if not isinstance(document, dict) or set(document) != {"schema_version", "target_hashes"}:
        raise SyncClosed("allowlist_shape")
    if document.get("schema_version") != 1:
        raise SyncClosed("allowlist_version")
    hashes = document.get("target_hashes")
    if not isinstance(hashes, list) or not hashes:
        raise SyncClosed("allowlist_empty")
    result: set[str] = set()
    for value in hashes:
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise SyncClosed("allowlist_hash")
        if value in result:
            raise SyncClosed("allowlist_duplicate")
        result.add(value)
    return result


def _validate_stage(stage: Any) -> dict[str, Any]:
    if not isinstance(stage, dict):
        raise SyncClosed("stage_shape")
    required = {"id", "label", "completed", "total", "percentage", "state", "weight"}
    if not required.issubset(stage):
        raise SyncClosed("stage_missing_field")
    if not isinstance(stage["id"], str) or not stage["id"]:
        raise SyncClosed("stage_id")
    if not isinstance(stage["label"], str) or not stage["label"].strip():
        raise SyncClosed("stage_label")
    if isinstance(stage["completed"], bool) or not isinstance(stage["completed"], int):
        raise SyncClosed("stage_completed")
    if isinstance(stage["total"], bool) or not isinstance(stage["total"], int):
        raise SyncClosed("stage_total")
    percentage = stage["percentage"]
    if isinstance(percentage, bool) or not isinstance(percentage, (int, float)):
        raise SyncClosed("stage_percentage")
    if not math.isfinite(float(percentage)) or not 0 <= float(percentage) <= 100:
        raise SyncClosed("stage_percentage_range")
    # Deliberately do not recalculate percentage from completed and total.
    return dict(stage)


def _validate_completion(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncClosed("completion_shape")
    if value.get("state") not in ALLOWED_COMPLETION_STATES:
        raise SyncClosed("completion_not_valid")
    authority = value.get("authority")
    if not isinstance(authority, str) or not authority.strip():
        raise SyncClosed("completion_authority_missing")
    stages = value.get("stages")
    if not isinstance(stages, list) or not stages:
        raise SyncClosed("completion_stages_missing")
    validated = dict(value)
    validated["authority"] = authority.strip()
    validated["stages"] = [_validate_stage(stage) for stage in stages]
    overall = value.get("overall_percentage")
    if overall is not None:
        if isinstance(overall, bool) or not isinstance(overall, (int, float)):
            raise SyncClosed("overall_percentage")
        if not math.isfinite(float(overall)) or not 0 <= float(overall) <= 100:
            raise SyncClosed("overall_percentage_range")
    return validated


def load_targets(dataset_path: Path, allowlist_path: Path) -> list[Target]:
    allowlist = load_allowlist(allowlist_path)
    try:
        document = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncClosed("dataset_unreadable") from exc
    if not isinstance(document, dict) or document.get("view") != DATASET_VIEW:
        raise SyncClosed("dataset_view")
    repositories = document.get("repositories")
    if not isinstance(repositories, list):
        raise SyncClosed("dataset_repositories")
    selected: list[Target] = []
    seen: set[str] = set()
    for record in repositories:
        if not isinstance(record, dict):
            raise SyncClosed("dataset_record")
        full_name = record.get("full_name")
        if not isinstance(full_name, str) or "/" not in full_name:
            raise SyncClosed("dataset_repository_name")
        identifier = target_id(full_name)
        if identifier not in allowlist:
            continue
        if identifier in seen:
            raise SyncClosed("dataset_duplicate_target")
        seen.add(identifier)
        private = record.get("private")
        if not isinstance(private, bool):
            raise SyncClosed("dataset_privacy_flag")
        selected.append(
            Target(
                target_id=identifier,
                full_name=full_name,
                private=private,
                completion=_validate_completion(record.get("completion")),
            )
        )
    if seen != allowlist:
        raise SyncClosed("pilot_missing")
    return sorted(selected, key=lambda item: item.target_id)


def _markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_generated_section(completion: dict[str, Any], newline: bytes = b"\n") -> bytes:
    lines = [
        "## Completion",
        "",
        "_Generated from validated project authority by `project-status-engine`. "
        "Repository activity is not completion._",
        "",
        "| Stage | Progress |",
        "|---|---:|",
    ]
    for stage in completion["stages"]:
        label = _markdown_escape(stage["label"])
        completed = stage["completed"]
        total = stage["total"]
        percentage = float(stage["percentage"])
        lines.append(f"| {label} | `{completed}/{total}` — **{percentage:.1f}%** |")
    lines += ["", f"Authority: `{_markdown_escape(completion['authority'])}`", ""]
    overall = completion.get("overall_percentage")
    if overall is None:
        lines.append("Overall completion is not enabled for this project.")
    else:
        lines.append(f"Overall completion: **{float(overall):.1f}%**")
    return newline.join(line.encode("utf-8") for line in lines)


def replace_generated_section(readme: bytes, generated: bytes) -> bytes:
    if readme.count(START_MARKER) != 1 or readme.count(END_MARKER) != 1:
        raise SyncClosed("readme_markers")
    start = readme.index(START_MARKER)
    end = readme.index(END_MARKER)
    if start >= end:
        raise SyncClosed("readme_marker_order")
    inner_start = start + len(START_MARKER)
    prefix = readme[:inner_start]
    suffix = readme[end:]
    newline = b"\r\n" if b"\r\n" in readme else b"\n"
    replacement = prefix + newline + generated + newline + suffix
    # The complete byte sequences outside the generated region must be identical.
    if replacement[:inner_start] != prefix or replacement[-len(suffix):] != suffix:
        raise SyncClosed("human_bytes_changed")
    return replacement


def desired_readme(readme: bytes, completion: dict[str, Any]) -> bytes:
    newline = b"\r\n" if b"\r\n" in readme else b"\n"
    return replace_generated_section(readme, render_generated_section(completion, newline))


class GitHubClient:
    def __init__(self, token: str, api_base: str = "https://api.github.com"):
        if not token:
            raise SyncClosed("token_missing")
        self._token = token
        self._api_base = api_base.rstrip("/")

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        url = self._api_base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "project-status-engine-readme-sync",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                return json.loads(payload.decode("utf-8")) if payload else None
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            raise ApiFailure(operation, exc.code) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ApiFailure(operation) from None

    def repository(self, full_name: str) -> dict[str, Any]:
        return self._request("repository", "GET", f"/repos/{full_name}")

    def file(self, full_name: str, path: str, ref: str) -> dict[str, Any] | None:
        return self._request(
            "file",
            "GET",
            f"/repos/{full_name}/contents/{path}",
            query={"ref": ref},
            allow_404=True,
        )

    def ref(self, full_name: str, branch: str) -> dict[str, Any] | None:
        encoded = urllib.parse.quote(f"heads/{branch}", safe="/")
        return self._request(
            "ref",
            "GET",
            f"/repos/{full_name}/git/ref/{encoded}",
            allow_404=True,
        )

    def create_ref(self, full_name: str, branch: str, sha: str) -> None:
        self._request(
            "create_ref",
            "POST",
            f"/repos/{full_name}/git/refs",
            body={"ref": f"refs/heads/{branch}", "sha": sha},
        )

    def update_ref(self, full_name: str, branch: str, sha: str) -> None:
        encoded = urllib.parse.quote(f"heads/{branch}", safe="/")
        self._request(
            "update_ref",
            "PATCH",
            f"/repos/{full_name}/git/refs/{encoded}",
            body={"sha": sha, "force": True},
        )

    def update_file(
        self, full_name: str, path: str, branch: str, content: bytes, source_sha: str
    ) -> dict[str, Any]:
        return self._request(
            "update_file",
            "PUT",
            f"/repos/{full_name}/contents/{path}",
            body={
                "message": "Synchronise generated README completion",
                "content": base64.b64encode(content).decode("ascii"),
                "sha": source_sha,
                "branch": branch,
            },
        )

    def open_pull_requests(
        self, full_name: str, owner: str, branch: str, base: str
    ) -> list[dict[str, Any]]:
        value = self._request(
            "list_prs",
            "GET",
            f"/repos/{full_name}/pulls",
            query={"state": "open", "head": f"{owner}:{branch}", "base": base},
        )
        return value if isinstance(value, list) else []

    def create_pull_request(self, full_name: str, branch: str, base: str) -> None:
        self._request(
            "create_pr",
            "POST",
            f"/repos/{full_name}/pulls",
            body={
                "title": PR_TITLE,
                "head": branch,
                "base": base,
                "body": PR_BODY,
                "draft": False,
            },
        )

    def update_pull_request(self, full_name: str, number: int) -> None:
        self._request(
            "update_pr",
            "PATCH",
            f"/repos/{full_name}/pulls/{number}",
            body={"title": PR_TITLE, "body": PR_BODY, "state": "open"},
        )


def _decode_readme(payload: Any) -> tuple[bytes, str]:
    if not isinstance(payload, dict):
        raise SyncClosed("readme_missing")
    if payload.get("type") != "file":
        raise SyncClosed("readme_not_file")
    if payload.get("encoding") != "base64":
        raise SyncClosed("readme_encoding")
    content = payload.get("content")
    sha = payload.get("sha")
    if not isinstance(content, str) or not isinstance(sha, str):
        raise SyncClosed("readme_payload")
    try:
        raw = base64.b64decode(content.replace("\n", ""), validate=True)
        raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise SyncClosed("readme_utf8") from exc
    return raw, sha


def prepare_target(target: Target, client: Any) -> SyncPlan:
    """Read and validate all target state without performing a write."""
    repository = client.repository(target.full_name)
    default_branch = repository.get("default_branch") if isinstance(repository, dict) else None
    owner = (
        repository.get("owner", {}).get("login")
        if isinstance(repository, dict) and isinstance(repository.get("owner"), dict)
        else None
    )
    if not isinstance(default_branch, str) or not default_branch:
        raise SyncClosed("default_branch_missing")
    if not isinstance(owner, str) or not owner:
        raise SyncClosed("repository_owner_missing")
    if default_branch == SYNC_BRANCH:
        raise SyncClosed("default_branch_is_sync_branch")

    default_file = client.file(target.full_name, README_PATH, default_branch)
    readme, source_sha = _decode_readme(default_file)
    desired = desired_readme(readme, target.completion)
    changed = desired != readme

    default_ref = client.ref(target.full_name, default_branch)
    if not isinstance(default_ref, dict):
        raise SyncClosed("default_ref_missing")
    default_sha = default_ref.get("object", {}).get("sha")
    if not isinstance(default_sha, str) or not default_sha:
        raise SyncClosed("default_sha_missing")

    pulls = client.open_pull_requests(target.full_name, owner, SYNC_BRANCH, default_branch)
    if len(pulls) > 1:
        raise SyncClosed("multiple_sync_prs")
    existing_pr_number: int | None = None
    if pulls:
        number = pulls[0].get("number")
        if not isinstance(number, int):
            raise SyncClosed("sync_pr_number")
        existing_pr_number = number

    return SyncPlan(
        target=target,
        default_branch=default_branch,
        owner=owner,
        source_sha=source_sha,
        default_sha=default_sha,
        desired=desired,
        changed=changed,
        existing_pr_number=existing_pr_number,
    )


def apply_plan(plan: SyncPlan, client: Any, *, apply: bool) -> SyncResult:
    """Apply a prevalidated plan only to the automation-owned branch."""
    if not plan.changed:
        return SyncResult(plan.target.target_id, "unchanged")
    if not apply:
        return SyncResult(plan.target.target_id, "would_update")

    sync_ref = client.ref(plan.target.full_name, SYNC_BRANCH)
    if sync_ref is None:
        client.create_ref(plan.target.full_name, SYNC_BRANCH, plan.default_sha)
    else:
        client.update_ref(plan.target.full_name, SYNC_BRANCH, plan.default_sha)

    client.update_file(
        plan.target.full_name,
        README_PATH,
        SYNC_BRANCH,
        plan.desired,
        plan.source_sha,
    )
    if plan.existing_pr_number is not None:
        client.update_pull_request(plan.target.full_name, plan.existing_pr_number)
        action = "updated_pr"
    else:
        client.create_pull_request(
            plan.target.full_name,
            SYNC_BRANCH,
            plan.default_branch,
        )
        action = "opened_pr"
    return SyncResult(plan.target.target_id, action)


def safe_event(result: SyncResult) -> str:
    # Only an opaque digest prefix and fixed action leave the process.
    return json.dumps(
        {"target": result.target_id[:12], "action": result.action},
        sort_keys=True,
        separators=(",", ":"),
    )


def run(
    dataset: Path,
    allowlist: Path,
    *,
    apply: bool,
    client: Any,
) -> list[SyncResult]:
    targets = load_targets(dataset, allowlist)
    plans: list[SyncPlan] = []
    # Preflight every pilot before any write. One invalid or unreadable target
    # closes the complete batch without a partial update.
    for target in targets:
        try:
            plans.append(prepare_target(target, client))
        except (SyncClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            raise SyncClosed(f"target_{target.target_id[:12]}_{code}") from None
    results: list[SyncResult] = []
    for plan in plans:
        try:
            results.append(apply_plan(plan, client, apply=apply))
        except (SyncClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            raise SyncClosed(f"target_{plan.target.target_id[:12]}_{code}") from None
    return results


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    token = os.getenv("README_SYNC_TOKEN", "")
    try:
        client = GitHubClient(token)
        results = run(args.dataset, args.allowlist, apply=args.apply, client=client)
    except (SyncClosed, ApiFailure) as exc:
        code = exc.code if hasattr(exc, "code") else "closed"
        print(json.dumps({"status": "closed", "code": code}, separators=(",", ":")))
        return 1
    for result in results:
        print(safe_event(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
