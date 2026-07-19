#!/usr/bin/env python3
"""Run the README synchroniser with open-PR idempotence.

The transformation and GitHub API primitives live in ``readme_sync``. This
runner adds branch-state comparison so a daily run creates no new commit when
an existing synchroniser pull request already contains the desired README.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import readme_sync as core


@dataclass(frozen=True)
class RunnerPlan:
    target: core.Target
    default_branch: str
    owner: str
    default_sha: str
    default_source_sha: str
    desired: bytes
    action: str
    existing_pr_number: int | None


def prepare_target(target: core.Target, client: Any) -> RunnerPlan:
    """Preflight default-branch, automation-branch and pull-request state."""
    repository = client.repository(target.full_name)
    default_branch = repository.get("default_branch") if isinstance(repository, dict) else None
    owner = (
        repository.get("owner", {}).get("login")
        if isinstance(repository, dict) and isinstance(repository.get("owner"), dict)
        else None
    )
    if not isinstance(default_branch, str) or not default_branch:
        raise core.SyncClosed("default_branch_missing")
    if not isinstance(owner, str) or not owner:
        raise core.SyncClosed("repository_owner_missing")
    if default_branch == core.SYNC_BRANCH:
        raise core.SyncClosed("default_branch_is_sync_branch")

    default_payload = client.file(target.full_name, core.README_PATH, default_branch)
    default_readme, default_source_sha = core._decode_readme(default_payload)
    desired = core.desired_readme(default_readme, target.completion)

    default_ref = client.ref(target.full_name, default_branch)
    if not isinstance(default_ref, dict):
        raise core.SyncClosed("default_ref_missing")
    default_sha = default_ref.get("object", {}).get("sha")
    if not isinstance(default_sha, str) or not default_sha:
        raise core.SyncClosed("default_sha_missing")

    pulls = client.open_pull_requests(target.full_name, owner, core.SYNC_BRANCH, default_branch)
    if len(pulls) > 1:
        raise core.SyncClosed("multiple_sync_prs")
    existing_pr_number: int | None = None
    if pulls:
        number = pulls[0].get("number")
        if not isinstance(number, int):
            raise core.SyncClosed("sync_pr_number")
        existing_pr_number = number

    if desired == default_readme:
        return RunnerPlan(
            target=target,
            default_branch=default_branch,
            owner=owner,
            default_sha=default_sha,
            default_source_sha=default_source_sha,
            desired=desired,
            action="unchanged",
            existing_pr_number=existing_pr_number,
        )

    if existing_pr_number is not None:
        sync_ref = client.ref(target.full_name, core.SYNC_BRANCH)
        if not isinstance(sync_ref, dict):
            raise core.SyncClosed("open_pr_branch_missing")
        sync_payload = client.file(target.full_name, core.README_PATH, core.SYNC_BRANCH)
        sync_readme, _ = core._decode_readme(sync_payload)
        if sync_readme == desired:
            return RunnerPlan(
                target=target,
                default_branch=default_branch,
                owner=owner,
                default_sha=default_sha,
                default_source_sha=default_source_sha,
                desired=desired,
                action="unchanged_pr",
                existing_pr_number=existing_pr_number,
            )

    return RunnerPlan(
        target=target,
        default_branch=default_branch,
        owner=owner,
        default_sha=default_sha,
        default_source_sha=default_source_sha,
        desired=desired,
        action="update",
        existing_pr_number=existing_pr_number,
    )


def apply_plan(plan: RunnerPlan, client: Any, *, apply: bool) -> core.SyncResult:
    """Apply only a plan that requires a new automation-branch commit."""
    if plan.action in {"unchanged", "unchanged_pr"}:
        return core.SyncResult(plan.target.target_id, plan.action)
    if not apply:
        return core.SyncResult(plan.target.target_id, "would_update")

    sync_ref = client.ref(plan.target.full_name, core.SYNC_BRANCH)
    if sync_ref is None:
        client.create_ref(plan.target.full_name, core.SYNC_BRANCH, plan.default_sha)
    else:
        client.update_ref(plan.target.full_name, core.SYNC_BRANCH, plan.default_sha)

    client.update_file(
        plan.target.full_name,
        core.README_PATH,
        core.SYNC_BRANCH,
        plan.desired,
        plan.default_source_sha,
    )
    if plan.existing_pr_number is not None:
        client.update_pull_request(plan.target.full_name, plan.existing_pr_number)
        action = "updated_pr"
    else:
        client.create_pull_request(
            plan.target.full_name,
            core.SYNC_BRANCH,
            plan.default_branch,
        )
        action = "opened_pr"
    return core.SyncResult(plan.target.target_id, action)


def run(
    dataset: Path,
    allowlist: Path,
    *,
    apply: bool,
    client: Any,
) -> list[core.SyncResult]:
    targets = core.load_targets(dataset, allowlist)
    plans: list[RunnerPlan] = []
    for target in targets:
        try:
            plans.append(prepare_target(target, client))
        except (core.SyncClosed, core.ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            raise core.SyncClosed(f"target_{target.target_id[:12]}_{code}") from None

    results: list[core.SyncResult] = []
    for plan in plans:
        try:
            results.append(apply_plan(plan, client, apply=apply))
        except (core.SyncClosed, core.ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            raise core.SyncClosed(f"target_{plan.target.target_id[:12]}_{code}") from None
    return results


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    token = os.getenv("README_SYNC_TOKEN", "")
    try:
        client = core.GitHubClient(token)
        results = run(args.dataset, args.allowlist, apply=args.apply, client=client)
    except (core.SyncClosed, core.ApiFailure) as exc:
        code = exc.code if hasattr(exc, "code") else "closed"
        print(json.dumps({"status": "closed", "code": code}, separators=(",", ":")))
        return 1
    for result in results:
        print(core.safe_event(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
