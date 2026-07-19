    def open_prs(self, full_name: str, base: str) -> list[dict[str, Any]]:
        value = self.request(
            "pulls",
            "GET",
            f"/repos/{full_name}/pulls",
            query={"state": "open", "base": base, "per_page": 100},
        )
        return value if isinstance(value, list) else []

    def pr_files(self, full_name: str, number: int) -> list[dict[str, Any]]:
        value = self.request(
            "pr_files", "GET", f"/repos/{full_name}/pulls/{number}/files", query={"per_page": 100}
        )
        return value if isinstance(value, list) else []

    def open_issues(self, full_name: str) -> list[dict[str, Any]]:
        value = self.request(
            "issues", "GET", f"/repos/{full_name}/issues", query={"state": "open", "per_page": 100}
        )
        return [item for item in value if isinstance(item, dict) and "pull_request" not in item] if isinstance(value, list) else []

    def upsert_exception_issue(self, full_name: str, code: str, detail: str) -> None:
        body = (
            "The portfolio bootstrap made no completion or README change because the repository evidence "
            "could not be converted without a human authority decision.\n\n"
            f"- Exception: `{code}`\n"
            f"- Detail: `{detail or 'No single explicit bounded completion record was found.'}`\n\n"
            "Accepted evidence must state completed and total counts in an existing authority/status document. "
            "Activity, file counts, commit counts, percentages without counts, readiness, and publication status "
            "are not treated as completion. Resolve the authority record; the next portfolio run will reassess it."
        )
        existing = next((item for item in self.open_issues(full_name) if item.get("title") == EXCEPTION_ISSUE_TITLE), None)
        if existing and isinstance(existing.get("number"), int):
            self.request(
                "update_issue",
                "PATCH",
                f"/repos/{full_name}/issues/{existing['number']}",
                body={"title": EXCEPTION_ISSUE_TITLE, "body": body, "state": "open"},
            )
        else:
            self.request(
                "create_issue",
                "POST",
                f"/repos/{full_name}/issues",
                body={"title": EXCEPTION_ISSUE_TITLE, "body": body},
            )

    def close_exception_issue(self, full_name: str) -> None:
        for item in self.open_issues(full_name):
            if item.get("title") == EXCEPTION_ISSUE_TITLE and isinstance(item.get("number"), int):
                self.request(
                    "close_issue",
                    "PATCH",
                    f"/repos/{full_name}/issues/{item['number']}",
                    body={"state": "closed", "state_reason": "completed"},
                )

    def write_commit(
        self, full_name: str, branch: str, base_sha: str, files: dict[str, bytes], message: str
    ) -> str:
        base_commit = self.request("git_commit", "GET", f"/repos/{full_name}/git/commits/{base_sha}")
        tree_sha = base_commit.get("tree", {}).get("sha") if isinstance(base_commit, dict) else None
        if not isinstance(tree_sha, str):
            raise BootstrapClosed("base_tree_missing")
        entries = []
        for path, content in sorted(files.items()):
            blob = self.request(
                "create_blob",
                "POST",
                f"/repos/{full_name}/git/blobs",
                body={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
            )
            sha = blob.get("sha") if isinstance(blob, dict) else None
            if not isinstance(sha, str):
                raise BootstrapClosed("blob_sha_missing", path)
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": sha})
        tree = self.request(
            "create_tree",
            "POST",
            f"/repos/{full_name}/git/trees",
            body={"base_tree": tree_sha, "tree": entries},
        )
        new_tree_sha = tree.get("sha") if isinstance(tree, dict) else None
        if not isinstance(new_tree_sha, str):
            raise BootstrapClosed("new_tree_missing")
        commit = self.request(
            "create_commit",
            "POST",
            f"/repos/{full_name}/git/commits",
            body={"message": message, "tree": new_tree_sha, "parents": [base_sha]},
        )
        commit_sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(commit_sha, str):
            raise BootstrapClosed("new_commit_missing")
        branch_ref = self.ref(full_name, branch)
        encoded = urllib.parse.quote(f"heads/{branch}", safe="/")
        if branch_ref is None:
            self.request(
                "create_ref",
                "POST",
                f"/repos/{full_name}/git/refs",
                body={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            )
        else:
            self.request(
                "update_ref",
                "PATCH",
                f"/repos/{full_name}/git/refs/{encoded}",
                body={"sha": commit_sha, "force": True},
            )
        return commit_sha

    def upsert_bootstrap_pr(self, full_name: str, base: str, project_type: str, authority: str) -> str:
        prs = self.open_prs(full_name, base)
        existing = next((pr for pr in prs if pr.get("head", {}).get("ref") == BOOTSTRAP_BRANCH), None)
        body = (
            "## Purpose\n\n"
            "Apply the owner-wide deterministic completion bootstrap. This is not an individual repository rollout.\n\n"
            "## Evidence boundary\n\n"
            f"- project classification: `{project_type}`;\n"
            f"- authority source: `{authority}`;\n"
            "- completed and total counts are copied only from that existing repository record;\n"
            "- overall completion remains disabled;\n"
            "- readiness, release, publication and activity are not inferred.\n\n"
            "## README boundary\n\n"
            "Only the generated completion marker block is added or replaced. Existing human-written README bytes are preserved."
        )
        if existing and isinstance(existing.get("number"), int):
            self.request(
                "update_pr",
                "PATCH",
                f"/repos/{full_name}/pulls/{existing['number']}",
                body={"title": BOOTSTRAP_PR_TITLE, "body": body, "state": "open"},
            )
            return "updated_pr"
        self.request(
            "create_pr",
            "POST",
            f"/repos/{full_name}/pulls",
            body={
                "title": BOOTSTRAP_PR_TITLE,
                "head": BOOTSTRAP_BRANCH,
                "base": base,
                "body": body,
                "draft": False,
            },
        )
        return "opened_pr"

    def merge_bootstrap_pr(self, full_name: str, number: int, head_sha: str) -> None:
        self.request(
            "merge_pr",
            "PUT",
            f"/repos/{full_name}/pulls/{number}/merge",
            body={"sha": head_sha, "merge_method": "merge"},
        )


def active_repositories(repositories: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        owner = repo.get("owner", {}).get("login") if isinstance(repo.get("owner"), dict) else None
        if owner != OWNER:
            continue
        if repo.get("archived") or repo.get("fork") or repo.get("disabled"):
            continue
        if not isinstance(repo.get("full_name"), str) or not isinstance(repo.get("default_branch"), str):
            continue
        result.append(repo)
    return sorted(result, key=lambda item: item["full_name"])


def pending_onboarding_pr(client: GitHubClient, full_name: str, base: str) -> int | None:
    matches: list[int] = []
    for pr in client.open_prs(full_name, base):
        number = pr.get("number")
        if not isinstance(number, int):
            continue
        if pr.get("head", {}).get("ref") == BOOTSTRAP_BRANCH:
            continue
        files = client.pr_files(full_name, number)
        if any(item.get("filename") == PROGRESS_PATH for item in files):
            matches.append(number)
    if len(matches) > 1:
        raise BootstrapClosed("multiple_pending_onboarding_prs")
    return matches[0] if matches else None


def _decode_json(raw: bytes, code: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapClosed(code) from exc


def plan_repository(repo: dict[str, Any], client: GitHubClient) -> RepositoryPlan:
    full_name = repo["full_name"]
    private = bool(repo.get("private"))
