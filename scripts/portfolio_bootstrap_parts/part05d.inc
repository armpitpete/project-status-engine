# Dedicated README marker-repair lane.
# Loaded after taxonomy classification and before merge-approved CLI handling.
README_REPAIR_BRANCH = "automation/project-status-readme-repair"
README_REPAIR_PR_TITLE = "Repair generated project completion README block"


def readme_marker_state(readme: bytes | None) -> str:
    """Classify only structurally safe README marker states.

    An absent pair and one correctly ordered pair are repairable. Duplicate,
    partial or reversed markers remain authority exceptions and are never
    rewritten automatically.
    """
    readme = readme or b""
    try:
        readme.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapClosed("readme_not_utf8") from exc
    start_count = readme.count(START_MARKER)
    end_count = readme.count(END_MARKER)
    if start_count == 0 and end_count == 0:
        return "absent"
    if start_count != 1 or end_count != 1:
        raise BootstrapClosed("readme_markers")
    if readme.index(START_MARKER) >= readme.index(END_MARKER):
        raise BootstrapClosed("readme_marker_order")
    return "valid"


_taxonomy_plan_repository = plan_repository


def plan_repository(repo: dict[str, Any], client: GitHubClient) -> RepositoryPlan:
    plan = _taxonomy_plan_repository(repo, client)
    if plan.action != "update" or set(plan.files) != {README_PATH}:
        return plan

    # README-only work is a separate repair lane. The legacy planner has already
    # validated the contract and built the desired bytes; this additional check
    # makes the permitted marker structures explicit.
    current = client.file(plan.full_name, README_PATH, plan.default_branch)
    readme_marker_state(current[0] if current is not None else None)
    return RepositoryPlan(
        plan.full_name,
        plan.private,
        plan.default_branch,
        plan.default_sha,
        plan.project_type,
        "readme_repair",
        plan.files,
        pending_pr_number=plan.pending_pr_number,
    )


def _upsert_readme_repair_pr(
    self: GitHubClient,
    full_name: str,
    base: str,
    project_type: str,
    authority: str,
) -> str:
    prs = self.open_prs(full_name, base)
    existing = next(
        (pr for pr in prs if pr.get("head", {}).get("ref") == README_REPAIR_BRANCH),
        None,
    )
    body = (
        "## Purpose\n\n"
        "Repair only the generated project-completion marker block for an existing valid completion contract.\n\n"
        "## Authority boundary\n\n"
        f"- project classification: `{project_type}`;\n"
        f"- existing completion authority: `{authority}`;\n"
        "- no stage, completed count, total, weight or percentage is changed;\n"
        "- activity, readiness and release state are not inferred.\n\n"
        "## README boundary\n\n"
        "This pull request changes only `README.md`. It either appends one missing marker pair or replaces only the interior of one correctly ordered marker pair. Human-written bytes outside the generated block are preserved. Duplicate, partial or reversed markers are not repaired automatically."
    )
    if existing and isinstance(existing.get("number"), int):
        self.request(
            "update_readme_repair_pr",
            "PATCH",
            f"/repos/{full_name}/pulls/{existing['number']}",
            body={"title": README_REPAIR_PR_TITLE, "body": body, "state": "open"},
        )
        return "updated_pr"
    self.request(
        "create_readme_repair_pr",
        "POST",
        f"/repos/{full_name}/pulls",
        body={
            "title": README_REPAIR_PR_TITLE,
            "head": README_REPAIR_BRANCH,
            "base": base,
            "body": body,
            "draft": False,
        },
    )
    return "opened_pr"


GitHubClient.upsert_readme_repair_pr = _upsert_readme_repair_pr


_taxonomy_apply_plan = apply_plan


def apply_plan(plan: RepositoryPlan, client: GitHubClient, *, apply: bool) -> Result:
    if plan.action != "readme_repair":
        return _taxonomy_apply_plan(plan, client, apply=apply)
    identifier = target_id(plan.full_name)
    if set(plan.files) != {README_PATH}:
        raise BootstrapClosed("readme_repair_scope")
    if not apply:
        return Result(identifier, "would_update")

    existing = client.file(plan.full_name, PROGRESS_PATH, plan.default_branch)
    if existing is None:
        raise BootstrapClosed("readme_repair_contract_missing")
    contract = _decode_json(existing[0], "progress_json")
    view = validate_progress(contract)
    authority = str(view.get("authority") or "")
    client.write_commit(
        plan.full_name,
        README_REPAIR_BRANCH,
        plan.default_sha,
        plan.files,
        "Repair generated project completion README block",
    )
    action = client.upsert_readme_repair_pr(
        plan.full_name,
        plan.default_branch,
        plan.project_type,
        authority,
    )
    client.clear_exception_report(plan.full_name)
    return Result(identifier, action)
