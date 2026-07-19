def merge_approved(client: GitHubClient, *, apply: bool) -> list[Result]:
    results: list[Result] = []
    for repo in active_repositories(client.repositories()):
        full_name = repo["full_name"]
        base = repo["default_branch"]
        prs = client.open_prs(full_name, base)
        pr = next((item for item in prs if item.get("head", {}).get("ref") == BOOTSTRAP_BRANCH), None)
        if pr is None:
            continue
        number = pr.get("number")
        head_sha = pr.get("head", {}).get("sha")
        if pr.get("title") != BOOTSTRAP_PR_TITLE or pr.get("draft"):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_not_approved_shape"))
            continue
        if not isinstance(number, int) or not isinstance(head_sha, str):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_shape"))
            continue
        files = client.pr_files(full_name, number)
        filenames = {item.get("filename") for item in files}
        if not filenames or not filenames.issubset({README_PATH, PROGRESS_PATH}):
            results.append(Result(target_id(full_name), "exception", "bootstrap_pr_scope"))
            continue
        try:
            expected = plan_repository(repo, client)
        except (BootstrapClosed, ApiFailure) as exc:
            code = exc.code if hasattr(exc, "code") else "bootstrap_pr_revalidation"
            results.append(Result(target_id(full_name), "exception", code))
            continue
        if expected.action != "update" or filenames != set(expected.files):
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
