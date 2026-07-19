# Portfolio visibility and exception-report overlay.
# Loaded after the core planner and before the CLI entry point.

EXCEPTION_BRANCH = "automation/project-status-bootstrap-exception"
EXCEPTION_PATH = ".project/bootstrap-exception.json"
MINIMUM_ACTIVE_REPOSITORIES = int(os.getenv("STATUS_MINIMUM_ACTIVE_REPOSITORIES", "49"))


def aggregate_run_report(
    mode: str,
    inventory: int,
    results: list[Result],
    status: str,
    *,
    inventory_sources: dict[str, int] | None = None,
    minimum_inventory: int = 0,
) -> bytes:
    actions: dict[str, int] = {}
    codes: dict[str, int] = {}
    for result in results:
        actions[result.action] = actions.get(result.action, 0) + 1
        if result.code and result.action in {"exception", "failure"}:
            codes[result.code] = codes.get(result.code, 0) + 1
    payload = {
        "schema_version": 1,
        "status": status,
        "mode": mode,
        "source_sha": REPORT_SHA,
        "inventory": inventory,
        "minimum_inventory": minimum_inventory,
        "inventory_sources": dict(sorted((inventory_sources or {}).items())),
        "actions": dict(sorted(actions.items())),
        "codes": dict(sorted(codes.items())),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def merge_repository_inventories(
    authenticated: Iterable[dict[str, Any]], public: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for repository in public:
        if isinstance(repository, dict) and isinstance(repository.get("full_name"), str):
            merged[repository["full_name"]] = repository
    for repository in authenticated:
        if isinstance(repository, dict) and isinstance(repository.get("full_name"), str):
            merged[repository["full_name"]] = repository
    return [merged[name] for name in sorted(merged)]


def _repository_page_set(
    self: GitHubClient, operation: str, path: str, query: dict[str, Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = self.request(
            operation,
            "GET",
            path,
            query={**query, "per_page": 100, "page": page},
        )
        if not isinstance(batch, list):
            raise BootstrapClosed("repository_inventory_shape")
        result.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
        page += 1
    return result


def _repositories(self: GitHubClient) -> list[dict[str, Any]]:
    authenticated = self._repository_page_set(
        "authenticated_repositories",
        "/user/repos",
        {
            "visibility": "all",
            "affiliation": "owner",
            "sort": "full_name",
            "direction": "asc",
        },
    )
    public = self._repository_page_set(
        "public_repositories",
        f"/users/{urllib.parse.quote(OWNER, safe='')}/repos",
        {"type": "owner", "sort": "full_name", "direction": "asc"},
    )
    merged = merge_repository_inventories(authenticated, public)
    self.inventory_counts = {
        "authenticated": len(authenticated),
        "public": len(public),
        "union": len(merged),
    }
    return merged


def _delete_ref(self: GitHubClient, full_name: str, branch: str) -> None:
    if self.ref(full_name, branch) is None:
        return
    encoded = urllib.parse.quote(f"heads/{branch}", safe="/")
    self.request("delete_ref", "DELETE", f"/repos/{full_name}/git/refs/{encoded}")


def _upsert_exception_report(
    self: GitHubClient,
    full_name: str,
    default_sha: str,
    project_type: str,
    code: str,
    detail: str,
) -> None:
    payload = {
        "schema_version": 1,
        "status": "requires_authority",
        "source_sha": default_sha,
        "project_type": project_type,
        "code": code,
        "detail": detail or "No single explicit bounded completion record was found.",
        "accepted_evidence": (
            "An existing repository authority/status document must state both completed "
            "and total counts. Activity, files, commits, percentages without counts, "
            "readiness and publication state are not completion evidence."
        ),
    }
    self.write_commit(
        full_name,
        EXCEPTION_BRANCH,
        default_sha,
        {EXCEPTION_PATH: (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")},
        "Record project completion bootstrap exception",
    )


def _clear_exception_report(self: GitHubClient, full_name: str) -> None:
    self.delete_ref(full_name, EXCEPTION_BRANCH)


GitHubClient._repository_page_set = _repository_page_set
GitHubClient.repositories = _repositories
GitHubClient.delete_ref = _delete_ref
GitHubClient.upsert_exception_report = _upsert_exception_report
GitHubClient.clear_exception_report = _clear_exception_report


def apply_plan(plan: RepositoryPlan, client: GitHubClient, *, apply: bool) -> Result:
    identifier = target_id(plan.full_name)
    if plan.action == "failure":
        return Result(identifier, "failure", plan.exception_code)
    if plan.action == "exception":
        if apply:
            client.upsert_exception_report(
                plan.full_name,
                plan.default_sha,
                plan.project_type,
                plan.exception_code or "closed",
                plan.exception_detail,
            )
        return Result(identifier, "exception", plan.exception_code)
    if plan.action == "pending_onboarding_pr":
        if apply:
            client.clear_exception_report(plan.full_name)
        return Result(identifier, "pending_pr")
    if plan.action == "unchanged":
        if apply:
            client.clear_exception_report(plan.full_name)
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
    client.clear_exception_report(plan.full_name)
    return Result(identifier, action)


def _write_aggregate_report(
    client: GitHubClient, inventory: int, results: list[Result], status: str
) -> None:
    if not REPORT_REPO or not REPORT_SHA:
        raise BootstrapClosed("report_context_missing")
    client.write_commit(
        REPORT_REPO,
        REPORT_BRANCH,
        REPORT_SHA,
        {
            REPORT_PATH: aggregate_run_report(
                "apply",
                inventory,
                results,
                status,
                inventory_sources=getattr(client, "inventory_counts", {}),
                minimum_inventory=MINIMUM_ACTIVE_REPOSITORIES,
            )
        },
        "Record portfolio completion bootstrap report",
    )


def run(client: GitHubClient, *, apply: bool) -> list[Result]:
    repos = active_repositories(client.repositories())
    if not repos:
        raise BootstrapClosed("repository_inventory_empty")
    if MINIMUM_ACTIVE_REPOSITORIES and len(repos) < MINIMUM_ACTIVE_REPOSITORIES:
        results = [Result("", "failure", "repository_inventory_below_minimum")]
        if apply:
            _write_aggregate_report(client, len(repos), results, "failed")
        print(
            json.dumps(
                {
                    "status": "failed",
                    "inventory": len(repos),
                    "minimum_inventory": MINIMUM_ACTIVE_REPOSITORIES,
                    "failure": 1,
                    "code": "repository_inventory_below_minimum",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise BootstrapClosed("repository_inventory_below_minimum")

    plans: list[RepositoryPlan] = []
    results: list[Result] = []
    for repo in repos:
        full_name = repo["full_name"]
        try:
            plans.append(plan_repository(repo, client))
        except ApiFailure as exc:
            plans.append(
                RepositoryPlan(
                    full_name,
                    bool(repo.get("private")),
                    repo["default_branch"],
                    "",
                    "unknown",
                    "failure",
                    {},
                    exc.code,
                    "",
                )
            )
        except BootstrapClosed as exc:
            plans.append(
                RepositoryPlan(
                    full_name,
                    bool(repo.get("private")),
                    repo["default_branch"],
                    "",
                    "unknown",
                    "exception",
                    {},
                    exc.code,
                    exc.detail,
                )
            )
    for plan in plans:
        try:
            result = apply_plan(plan, client, apply=apply)
        except (BootstrapClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            result = Result(target_id(plan.full_name), "failure", code)
        results.append(result)
        if result.action in {
            "exception",
            "failure",
            "opened_pr",
            "updated_pr",
            "would_update",
            "pending_pr",
        }:
            print(safe_event(result))
    failed = has_infrastructure_failures(results)
    status = "failed" if failed else "complete"
    if apply:
        _write_aggregate_report(client, len(repos), results, status)
    summary: dict[str, int] = {"inventory": len(repos)}
    for result in results:
        summary[result.action] = summary.get(result.action, 0) + 1
    print(json.dumps({"status": status, **summary}, sort_keys=True, separators=(",", ":")))
    if failed:
        raise BootstrapClosed("portfolio_infrastructure_failure")
    return results
