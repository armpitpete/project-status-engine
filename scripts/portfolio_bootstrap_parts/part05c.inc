# Identity-free portfolio authority registry and primary exception taxonomy.
# Loaded after the portfolio visibility overlay and before the CLI entry point.
from pathlib import Path

AUTHORITY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "portfolio-authority-registry.json"
)
EXPECTED_PRIMARY_EXCEPTION_CODES = (
    "missing_completion_contract",
    "missing_authoritative_source",
    "missing_readme_marker",
    "ambiguous_project_type",
    "contradictory_evidence",
    "no_completion_evidence",
    "inactive_repository_candidate",
)
EXPECTED_CLASSIFICATION_PRIORITY = (
    "inactive_repository_candidate",
    "contradictory_evidence",
    "missing_completion_contract",
    "missing_readme_marker",
    "ambiguous_project_type",
    "missing_authoritative_source",
    "no_completion_evidence",
)
EXPECTED_SOURCE_GROUPS = {
    "contradictory_evidence",
    "missing_completion_contract",
    "missing_readme_marker",
}


def load_authority_registry(path: Path = AUTHORITY_REGISTRY_PATH) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapClosed("authority_registry_unreadable") from exc
    if not isinstance(document, dict):
        raise BootstrapClosed("authority_registry_shape")
    expected_fields = {
        "schema_version",
        "registry_type",
        "repository_identity_mode",
        "primary_exception_codes",
        "classification_priority",
        "ambiguous_project_types",
        "source_code_groups",
    }
    if set(document) != expected_fields:
        raise BootstrapClosed("authority_registry_fields")
    if document.get("schema_version") != 1:
        raise BootstrapClosed("authority_registry_version")
    if document.get("registry_type") != "portfolio-authority-policy":
        raise BootstrapClosed("authority_registry_type")
    if document.get("repository_identity_mode") != "dynamic-owner-inventory":
        raise BootstrapClosed("authority_registry_identity_mode")
    primary = document.get("primary_exception_codes")
    if not isinstance(primary, list) or tuple(primary) != EXPECTED_PRIMARY_EXCEPTION_CODES:
        raise BootstrapClosed("authority_registry_primary_codes")
    priority = document.get("classification_priority")
    if not isinstance(priority, list) or tuple(priority) != EXPECTED_CLASSIFICATION_PRIORITY:
        raise BootstrapClosed("authority_registry_priority")
    ambiguous = document.get("ambiguous_project_types")
    if not isinstance(ambiguous, list) or not ambiguous or any(
        not isinstance(value, str) or not value for value in ambiguous
    ):
        raise BootstrapClosed("authority_registry_ambiguous_types")
    groups = document.get("source_code_groups")
    if not isinstance(groups, dict) or set(groups) != EXPECTED_SOURCE_GROUPS:
        raise BootstrapClosed("authority_registry_source_groups")
    seen: set[str] = set()
    for primary_code, source_codes in groups.items():
        if primary_code not in EXPECTED_PRIMARY_EXCEPTION_CODES:
            raise BootstrapClosed("authority_registry_source_primary")
        if not isinstance(source_codes, list) or not source_codes:
            raise BootstrapClosed("authority_registry_source_codes")
        for source_code in source_codes:
            if not isinstance(source_code, str) or not source_code or source_code in seen:
                raise BootstrapClosed("authority_registry_source_code")
            seen.add(source_code)
    return document


AUTHORITY_REGISTRY = load_authority_registry()
PRIMARY_EXCEPTION_CODES = tuple(AUTHORITY_REGISTRY["primary_exception_codes"])
PRIMARY_EXCEPTION_CODE_SET = frozenset(PRIMARY_EXCEPTION_CODES)
AMBIGUOUS_PROJECT_TYPES = frozenset(AUTHORITY_REGISTRY["ambiguous_project_types"])
SOURCE_CODE_GROUPS = {
    primary: frozenset(source_codes)
    for primary, source_codes in AUTHORITY_REGISTRY["source_code_groups"].items()
}


def classify_primary_exception(
    raw_code: str,
    *,
    has_contract: bool,
    authority_paths: Iterable[str],
    project_type: str,
    inactive: bool = False,
) -> str:
    """Return one registered primary exception from existing bootstrap evidence only."""
    if inactive:
        return "inactive_repository_candidate"
    for primary_code in (
        "contradictory_evidence",
        "missing_completion_contract",
        "missing_readme_marker",
    ):
        if raw_code in SOURCE_CODE_GROUPS[primary_code]:
            return primary_code
    if project_type in AMBIGUOUS_PROJECT_TYPES:
        return "ambiguous_project_type"
    if not has_contract and raw_code == "insufficient_authority":
        if not tuple(authority_paths):
            return "missing_authoritative_source"
        return "no_completion_evidence"
    raise BootstrapClosed("exception_taxonomy_unclassified", raw_code)


_legacy_plan_repository = plan_repository


def plan_repository(repo: dict[str, Any], client: GitHubClient) -> RepositoryPlan:
    plan = _legacy_plan_repository(repo, client)

    # A pending reviewed onboarding PR remains authoritative and is never reclassified.
    if plan.action == "pending_onboarding_pr":
        return plan

    # Refuse to construct a new contract when generic evidence cannot identify one
    # project type. Existing valid contracts and README-only repairs remain untouched.
    if (
        plan.action == "update"
        and PROGRESS_PATH in plan.files
        and plan.project_type in AMBIGUOUS_PROJECT_TYPES
    ):
        return RepositoryPlan(
            plan.full_name,
            plan.private,
            plan.default_branch,
            plan.default_sha,
            plan.project_type,
            "exception",
            {},
            "ambiguous_project_type",
            "Repository evidence identifies more than one project type or no project type.",
            plan.pending_pr_number,
        )

    if plan.action != "exception":
        return plan

    raw_code = plan.exception_code or ""
    authority_paths: tuple[str, ...] = ()
    has_contract = raw_code.startswith("progress_") or raw_code == "progress_json"
    if raw_code == "insufficient_authority":
        tree = client.tree(plan.full_name, plan.default_sha)
        paths = [
            item.get("path")
            for item in tree
            if item.get("type") == "blob" and isinstance(item.get("path"), str)
        ]
        authority_paths = tuple(authority_candidates(paths))

    primary_code = classify_primary_exception(
        raw_code,
        has_contract=has_contract,
        authority_paths=authority_paths,
        project_type=plan.project_type,
    )
    return RepositoryPlan(
        plan.full_name,
        plan.private,
        plan.default_branch,
        plan.default_sha,
        plan.project_type,
        plan.action,
        plan.files,
        primary_code,
        plan.exception_detail,
        plan.pending_pr_number,
    )


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
    exceptions = {code: 0 for code in PRIMARY_EXCEPTION_CODES}
    failures: dict[str, int] = {}
    for result in results:
        actions[result.action] = actions.get(result.action, 0) + 1
        if result.action == "exception":
            if result.code not in PRIMARY_EXCEPTION_CODE_SET:
                raise BootstrapClosed("exception_code_not_primary", result.code or "")
            exceptions[result.code] += 1
        elif result.action == "failure" and result.code:
            failures[result.code] = failures.get(result.code, 0) + 1
    payload = {
        "schema_version": 2,
        "registry_schema_version": AUTHORITY_REGISTRY["schema_version"],
        "status": status,
        "mode": mode,
        "source_sha": REPORT_SHA,
        "inventory": inventory,
        "minimum_inventory": minimum_inventory,
        "inventory_sources": dict(sorted((inventory_sources or {}).items())),
        "actions": dict(sorted(actions.items())),
        "exceptions": exceptions,
        "failures": dict(sorted(failures.items())),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _upsert_exception_report(
    self: GitHubClient,
    full_name: str,
    default_sha: str,
    project_type: str,
    code: str,
    detail: str,
) -> None:
    if code not in PRIMARY_EXCEPTION_CODE_SET:
        raise BootstrapClosed("exception_code_not_primary", code)
    payload = {
        "schema_version": 2,
        "status": "requires_authority",
        "source_sha": default_sha,
        "project_type": project_type,
        "code": code,
        "registry": "config/portfolio-authority-registry.json",
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
        "Record classified project completion bootstrap exception",
    )


GitHubClient.upsert_exception_report = _upsert_exception_report


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
        except (BootstrapClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "closed"
            plans.append(
                RepositoryPlan(
                    full_name,
                    bool(repo.get("private")),
                    repo["default_branch"],
                    "",
                    "unknown",
                    "failure",
                    {},
                    code,
                    "",
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
