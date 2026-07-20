# Exclude controlled automation lanes from human onboarding-PR detection.
AUTOMATION_PROGRESS_BRANCHES = frozenset(
    {
        BOOTSTRAP_BRANCH,
        README_REPAIR_BRANCH,
        CONTRACT_REPAIR_BRANCH,
    }
)


def pending_onboarding_pr(client: GitHubClient, full_name: str, base: str) -> int | None:
    matches: list[int] = []
    for pr in client.open_prs(full_name, base):
        number = pr.get("number")
        if not isinstance(number, int):
            continue
        if pr.get("head", {}).get("ref") in AUTOMATION_PROGRESS_BRANCHES:
            continue
        files = client.pr_files(full_name, number)
        if any(item.get("filename") == PROGRESS_PATH for item in files):
            matches.append(number)
    if len(matches) > 1:
        raise BootstrapClosed("multiple_pending_onboarding_prs")
    return matches[0] if matches else None
