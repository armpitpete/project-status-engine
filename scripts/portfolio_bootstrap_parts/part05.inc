    default_branch = repo["default_branch"]
    ref = client.ref(full_name, default_branch)
    default_sha = ref.get("object", {}).get("sha") if isinstance(ref, dict) else None
    if not isinstance(default_sha, str):
        raise BootstrapClosed("default_sha_missing")
    tree = client.tree(full_name, default_sha)
    paths = [item.get("path") for item in tree if item.get("type") == "blob" and isinstance(item.get("path"), str)]
    project_type = classify_project(repo, paths)

    pending = pending_onboarding_pr(client, full_name, default_branch)
    if pending is not None:
        return RepositoryPlan(
            full_name,
            private,
            default_branch,
            default_sha,
            project_type,
            "pending_onboarding_pr",
            {},
            pending_pr_number=pending,
        )

    progress_file = client.file(full_name, PROGRESS_PATH, default_branch)
    contract: dict[str, Any]
    contract_is_new = False
    if progress_file is not None:
        raw_progress, _ = progress_file
        contract = _decode_json(raw_progress, "progress_json")
        try:
            view = validate_progress(contract)
        except BootstrapClosed as exc:
            return RepositoryPlan(
                full_name,
                private,
                default_branch,
                default_sha,
                project_type,
                "exception",
                {},
                exc.code,
                exc.detail,
            )
    else:
        selected_path = ""
        selected_stages: list[EvidenceStage] = []
        contradiction: BootstrapClosed | None = None
        for path in authority_candidates(paths):
            item = next((entry for entry in tree if entry.get("path") == path), None)
            size = item.get("size") if isinstance(item, dict) else None
            if isinstance(size, int) and size > MAX_AUTHORITY_BYTES:
                continue
            file_value = client.file(full_name, path, default_branch)
            if file_value is None:
                continue
            raw, _ = file_value
            try:
                text = raw.decode("utf-8")
                stages = extract_stages(text, path)
            except UnicodeDecodeError:
                continue
            except BootstrapClosed as exc:
                contradiction = exc
                break
            if stages:
                selected_path = path
                selected_stages = stages
                break
        if contradiction is not None:
            return RepositoryPlan(
                full_name,
                private,
                default_branch,
                default_sha,
                project_type,
                "exception",
                {},
                contradiction.code,
                contradiction.detail,
            )
        if not selected_stages:
            return RepositoryPlan(
                full_name,
                private,
                default_branch,
                default_sha,
                project_type,
                "exception",
                {},
                "insufficient_authority",
                "No authority/status document contained an explicit completed/total count.",
            )
        contract = build_contract(project_type, selected_path, selected_stages)
        view = progress_view(contract)
        contract_is_new = True

    readme_file = client.file(full_name, README_PATH, default_branch)
    readme = readme_file[0] if readme_file is not None else None
    try:
        desired = desired_readme(readme, view)
    except BootstrapClosed as exc:
        return RepositoryPlan(
            full_name,
            private,
            default_branch,
            default_sha,
            project_type,
            "exception",
            {},
            exc.code,
            exc.detail,
        )

    files: dict[str, bytes] = {}
    if contract_is_new:
        files[PROGRESS_PATH] = (json.dumps(contract, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if readme != desired:
        files[README_PATH] = desired
    if not files:
        return RepositoryPlan(
            full_name,
            private,
            default_branch,
            default_sha,
            project_type,
            "unchanged",
            {},
        )
    return RepositoryPlan(
        full_name,
        private,
        default_branch,
        default_sha,
        project_type,
        "update",
        files,
    )


def apply_plan(plan: RepositoryPlan, client: GitHubClient, *, apply: bool) -> Result:
    identifier = target_id(plan.full_name)
    if plan.action == "exception":
        if apply:
            client.upsert_exception_issue(
                plan.full_name,
                plan.exception_code or "closed",
                plan.exception_detail,
            )
        return Result(identifier, "exception", plan.exception_code)
    if plan.action == "pending_onboarding_pr":
        return Result(identifier, "pending_pr")
    if plan.action == "unchanged":
        if apply:
            client.close_exception_issue(plan.full_name)
        return Result(identifier, "unchanged")
    if not apply:
        return Result(identifier, "would_update")

    client.write_commit(
        plan.full_name,
        BOOTSTRAP_BRANCH,
        plan.default_sha,
        plan.files,
        "Bootstrap authority-backed project completion",
    )
    progress_raw = plan.files.get(PROGRESS_PATH)
    if progress_raw is not None:
        contract = _decode_json(progress_raw, "generated_progress_json")
        authority = str(contract.get("authority") or "")
    else:
        existing = client.file(plan.full_name, PROGRESS_PATH, plan.default_branch)
        contract = _decode_json(existing[0], "progress_json") if existing is not None else {}
        authority = str(contract.get("authority") or "")
    action = client.upsert_bootstrap_pr(
        plan.full_name,
        plan.default_branch,
        plan.project_type,
        authority,
    )
    client.close_exception_issue(plan.full_name)
    return Result(identifier, action)


def run(client: GitHubClient, *, apply: bool) -> list[Result]:
    repos = active_repositories(client.repositories())
    plans: list[RepositoryPlan] = []
    results: list[Result] = []
    for repo in repos:
        full_name = repo["full_name"]
        try:
            plans.append(plan_repository(repo, client))
        except (BootstrapClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            detail = exc.detail if isinstance(exc, BootstrapClosed) else ""
            plans.append(
                RepositoryPlan(
                    full_name,
                    bool(repo.get("private")),
                    repo["default_branch"],
                    "",
                    "unknown",
