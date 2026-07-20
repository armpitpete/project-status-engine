# Authority-backed completion-contract repair lane.
# Loaded after README repair routing and before merge-approved CLI handling.
CONTRACT_REPAIR_BRANCH = "automation/project-status-contract-repair"
CONTRACT_REPAIR_PR_TITLE = "Repair authority-backed project completion contract"


def _stage_signature(stages: Iterable[EvidenceStage]) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (_slug(stage.label), stage.completed, stage.total)
        for stage in stages
    )


def _best_effort_contract_authority(raw: bytes) -> str:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(document, dict):
        return ""
    authority = document.get("authority")
    return authority.strip() if isinstance(authority, str) else ""


def _unreadable_contract_plan(
    repo: dict[str, Any], client: GitHubClient, detail: str
) -> RepositoryPlan:
    full_name = repo["full_name"]
    default_branch = repo["default_branch"]
    ref = client.ref(full_name, default_branch)
    default_sha = ref.get("object", {}).get("sha") if isinstance(ref, dict) else None
    if not isinstance(default_sha, str):
        raise BootstrapClosed("default_sha_missing")
    tree = client.tree(full_name, default_sha)
    paths = [
        item.get("path")
        for item in tree
        if item.get("type") == "blob" and isinstance(item.get("path"), str)
    ]
    return RepositoryPlan(
        full_name,
        bool(repo.get("private")),
        default_branch,
        default_sha,
        classify_project(repo, paths),
        "exception",
        {},
        "missing_completion_contract",
        detail,
    )


def contract_repair_evidence(
    plan: RepositoryPlan,
    client: GitHubClient,
) -> tuple[str, list[EvidenceStage]] | None:
    """Find explicit bounded evidence without deriving values from the invalid contract."""
    progress_file = client.file(plan.full_name, PROGRESS_PATH, plan.default_branch)
    if progress_file is None:
        return None
    raw_progress, _ = progress_file
    preferred = _best_effort_contract_authority(raw_progress)

    tree = client.tree(plan.full_name, plan.default_sha)
    paths = [
        item.get("path")
        for item in tree
        if item.get("type") == "blob" and isinstance(item.get("path"), str)
    ]
    available = set(paths)
    if preferred:
        candidate_paths = [preferred] if preferred in available and preferred != PROGRESS_PATH else []
    else:
        candidate_paths = [path for path in authority_candidates(paths) if path != PROGRESS_PATH]

    candidates: list[tuple[str, list[EvidenceStage]]] = []
    contradiction: BootstrapClosed | None = None
    for path in candidate_paths:
        item = next((entry for entry in tree if entry.get("path") == path), None)
        size = item.get("size") if isinstance(item, dict) else None
        if isinstance(size, int) and size > MAX_AUTHORITY_BYTES:
            continue
        value = client.file(plan.full_name, path, plan.default_branch)
        if value is None:
            continue
        raw, _ = value
        try:
            text = raw.decode("utf-8")
            stages = extract_stages(text, path)
        except UnicodeDecodeError:
            continue
        except BootstrapClosed as exc:
            contradiction = exc
            break
        if stages:
            candidates.append((path, stages))
            if preferred:
                break

    if contradiction is not None:
        raise BootstrapClosed("contract_repair_contradictory_evidence", contradiction.detail)
    if not candidates:
        return None

    first_signature = _stage_signature(candidates[0][1])
    if any(_stage_signature(stages) != first_signature for _, stages in candidates[1:]):
        raise BootstrapClosed(
            "contract_repair_contradictory_evidence",
            ",".join(path for path, _ in candidates),
        )
    return candidates[0]


def _plan_contract_repair(
    plan: RepositoryPlan, client: GitHubClient
) -> RepositoryPlan:
    if plan.action != "exception" or plan.exception_code != "missing_completion_contract":
        return plan
    if not plan.default_sha:
        return plan
    if plan.project_type in AMBIGUOUS_PROJECT_TYPES:
        return RepositoryPlan(
            plan.full_name,
            plan.private,
            plan.default_branch,
            plan.default_sha,
            plan.project_type,
            "exception",
            {},
            "ambiguous_project_type",
            "A replacement completion contract cannot be constructed until the project type is explicit.",
            plan.pending_pr_number,
        )

    try:
        evidence = contract_repair_evidence(plan, client)
    except BootstrapClosed as exc:
        if exc.code == "contract_repair_contradictory_evidence":
            return RepositoryPlan(
                plan.full_name,
                plan.private,
                plan.default_branch,
                plan.default_sha,
                plan.project_type,
                "exception",
                {},
                "contradictory_evidence",
                exc.detail,
                plan.pending_pr_number,
            )
        raise
    if evidence is None:
        return plan

    authority, stages = evidence
    contract = build_contract(plan.project_type, authority, stages)
    view = validate_progress(contract)
    readme_file = client.file(plan.full_name, README_PATH, plan.default_branch)
    readme = readme_file[0] if readme_file is not None else None
    try:
        desired = desired_readme(readme, view)
    except BootstrapClosed as exc:
        if exc.code in SOURCE_CODE_GROUPS["missing_readme_marker"]:
            return RepositoryPlan(
                plan.full_name,
                plan.private,
                plan.default_branch,
                plan.default_sha,
                plan.project_type,
                "exception",
                {},
                "missing_readme_marker",
                "README marker structure blocks an atomic completion-contract repair.",
                plan.pending_pr_number,
            )
        raise

    files = {
        PROGRESS_PATH: (json.dumps(contract, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    }
    if readme != desired:
        files[README_PATH] = desired
    return RepositoryPlan(
        plan.full_name,
        plan.private,
        plan.default_branch,
        plan.default_sha,
        plan.project_type,
        "contract_repair",
        files,
        pending_pr_number=plan.pending_pr_number,
    )


_readme_lane_plan_repository = plan_repository


def plan_repository(repo: dict[str, Any], client: GitHubClient) -> RepositoryPlan:
    try:
        plan = _readme_lane_plan_repository(repo, client)
    except BootstrapClosed as exc:
        if exc.code != "progress_json":
            raise
        plan = _unreadable_contract_plan(
            repo,
            client,
            "Existing .project/progress.json is not valid UTF-8 JSON.",
        )
    return _plan_contract_repair(plan, client)


def _upsert_contract_repair_pr(
    self: GitHubClient,
    full_name: str,
    base: str,
    project_type: str,
    authority: str,
) -> str:
    prs = self.open_prs(full_name, base)
    existing = next(
        (pr for pr in prs if pr.get("head", {}).get("ref") == CONTRACT_REPAIR_BRANCH),
        None,
    )
    body = (
        "## Purpose\n\n"
        "Replace an invalid machine-readable completion contract using only explicit completed-and-total evidence already recorded in repository authority.\n\n"
        "## Evidence boundary\n\n"
        f"- project classification: `{project_type}`;\n"
        f"- authority source: `{authority}`;\n"
        "- stage labels, completed counts and totals are copied only from that authority;\n"
        "- weights are not invented or preserved from an invalid contract;\n"
        "- overall completion remains disabled;\n"
        "- readiness, release, publication and activity are not inferred.\n\n"
        "## File boundary\n\n"
        "The pull request must replace `.project/progress.json` and may update only the generated completion block in `README.md`. Unsafe README marker structures and contradictory authority evidence remain unresolved exceptions."
    )
    if existing and isinstance(existing.get("number"), int):
        self.request(
            "update_contract_repair_pr",
            "PATCH",
            f"/repos/{full_name}/pulls/{existing['number']}",
            body={"title": CONTRACT_REPAIR_PR_TITLE, "body": body, "state": "open"},
        )
        return "updated_pr"
    self.request(
        "create_contract_repair_pr",
        "POST",
        f"/repos/{full_name}/pulls",
        body={
            "title": CONTRACT_REPAIR_PR_TITLE,
            "head": CONTRACT_REPAIR_BRANCH,
            "base": base,
            "body": body,
            "draft": False,
        },
    )
    return "opened_pr"


GitHubClient.upsert_contract_repair_pr = _upsert_contract_repair_pr


_readme_lane_apply_plan = apply_plan


def apply_plan(plan: RepositoryPlan, client: GitHubClient, *, apply: bool) -> Result:
    if plan.action != "contract_repair":
        return _readme_lane_apply_plan(plan, client, apply=apply)
    identifier = target_id(plan.full_name)
    if PROGRESS_PATH not in plan.files or not set(plan.files).issubset({PROGRESS_PATH, README_PATH}):
        raise BootstrapClosed("contract_repair_scope")
    if not apply:
        return Result(identifier, "would_update")

    contract = _decode_json(plan.files[PROGRESS_PATH], "generated_progress_json")
    view = validate_progress(contract)
    authority = str(view.get("authority") or "")
    client.write_commit(
        plan.full_name,
        CONTRACT_REPAIR_BRANCH,
        plan.default_sha,
        plan.files,
        "Repair authority-backed project completion contract",
    )
    action = client.upsert_contract_repair_pr(
        plan.full_name,
        plan.default_branch,
        plan.project_type,
        authority,
    )
    client.clear_exception_report(plan.full_name)
    return Result(identifier, action)
