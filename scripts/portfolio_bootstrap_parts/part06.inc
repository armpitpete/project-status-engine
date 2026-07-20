def merge_approved(client: GitHubClient, *, apply: bool) -> list[Result]:
    results: list[Result] = []
    approved_specs = {
        BOOTSTRAP_BRANCH: {
            "title": BOOTSTRAP_PR_TITLE,
            "action": "update",
            "allowed_paths": {README_PATH, PROGRESS_PATH},
        },
        README_REPAIR_BRANCH: {
            "title": README_REPAIR_PR_TITLE,
            "action": "readme_repair",
            "allowed_paths": {README_PATH},
        },
        CONTRACT_REPAIR_BRANCH: {
            "title": CONTRACT_REPAIR_PR_TITLE,
            "action": "contract_repair",
            "allowed_paths": {README_PATH, PROGRESS_PATH},
        },
    }
    for repo in active_repositories(client.repositories()):
        full_name = repo["full_name"]
        base = repo["default_branch"]
        prs = client.open_prs(full_name, base)
        candidates = [
            item
            for item in prs
            if item.get("head", {}).get("ref") in approved_specs
        ]
        if not candidates:
            continue
        if len(candidates) != 1:
            results.append(
                Result(target_id(full_name), "exception", "multiple_approved_automation_prs")
            )
            continue
        pr = candidates[0]
        branch = pr.get("head", {}).get("ref")
        spec = approved_specs.get(branch)
        number = pr.get("number")
        head_sha = pr.get("head", {}).get("sha")
        if spec is None or pr.get("title") != spec["title"] or pr.get("draft"):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_not_approved_shape"))
            continue
        if not isinstance(number, int) or not isinstance(head_sha, str):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_shape"))
            continue
        files = client.pr_files(full_name, number)
        filenames = {item.get("filename") for item in files}
        if not filenames or not filenames.issubset(spec["allowed_paths"]):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_scope"))
            continue
        try:
            expected = plan_repository(repo, client)
        except (BootstrapClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "bootstrap_pr_revalidation"
            results.append(Result(target_id(full_name), "exception", code))
            continue
        if expected.action != spec["action"] or filenames != set(expected.files):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_stale"))
            continue
        exact = True
        for path, desired in expected.files.items():
            current = client.file(full_name, path, head_sha)
            if current is None or current[0] != desired:
                exact = False
                break
        if not exact:
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_content"))
            continue
        if not apply:
            results.append(Result(target_id(full_name), "would_merge"))
            continue
        client.merge_bootstrap_pr(full_name, number, head_sha)
        results.append(Result(target_id(full_name), "merged_pr"))
    for result in results:
        if result.action != "merged_pr":
            print(safe_event(result))
    summary: dict[str, int] = {}
    for result in results:
        summary[result.action] = summary.get(result.action, 0) + 1
    print(json.dumps({"status": "complete", **summary}, sort_keys=True, separators=(",", ":")))
    return results


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--merge-approved", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        client = GitHubClient(TOKEN)
        if args.merge_approved:
            merge_approved(client, apply=True)
        else:
            run(client, apply=args.apply)
    except (BootstrapClosed, ApiFailure) as exc:
        code = exc.code if hasattr(exc, "code") else "closed"
        print(json.dumps({"status": "closed", "code": code}, separators=(",", ":")))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
