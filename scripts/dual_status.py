#!/usr/bin/env python3
"""Build public and private project-status views from one GitHub scan."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import authority_exceptions as exceptions
import completion_status as completion
import live_status as core

PUBLIC_OUT_DIR = Path(os.getenv("STATUS_OUT_DIR", "public"))
PRIVATE_OUT_DIR = Path(os.getenv("PRIVATE_STATUS_OUT_DIR", "private-build"))


def collect_ranked() -> tuple[list[dict[str, Any]], list[str], dt.datetime]:
    """Collect once, then rank once. Both views are derived from this result."""
    now = core.now_utc()
    path, query = core.discovery_request()
    repos, repo_error = core.safe_get(path, query)
    errors = [repo_error] if repo_error else []
    projects: list[dict[str, Any]] = []
    since = (now - dt.timedelta(days=core.WINDOW_DAYS)).isoformat()

    for repo in repos or []:
        if repo.get("archived") or repo.get("fork") or not repo.get("full_name"):
            continue
        name = repo["full_name"]
        private = bool(repo.get("private"))
        time.sleep(0.05)
        issues_raw, issue_error = core.safe_get(
            f"/repos/{name}/issues",
            {"state": "open", "sort": "updated", "direction": "desc", "per_page": core.MAX_ITEMS},
        )
        prs_raw, pr_error = core.safe_get(
            f"/repos/{name}/pulls",
            {"state": "open", "sort": "updated", "direction": "desc", "per_page": core.MAX_ITEMS},
        )
        latest_raw, latest_error = core.safe_get(f"/repos/{name}/commits", {"per_page": 1})
        recent_raw, recent_error = core.safe_get(
            f"/repos/{name}/commits",
            {"author": core.OWNER, "since": since, "per_page": 100},
        )
        progress, progress_error = completion.fetch_repository_progress(name, core.api_get)
        authority_exception, exception_error = exceptions.fetch_repository_exception(
            name, core.api_get
        )
        for error in (
            issue_error,
            pr_error,
            latest_error,
            recent_error,
            progress_error,
            exception_error,
        ):
            if error:
                errors.append(core.safe_error(private, name, error))

        issues = [core.issue_from(item) for item in (issues_raw or []) if not item.get("pull_request")]
        prs = [core.pr_from(item) for item in (prs_raw or [])]
        latest = [core.commit_from(item) for item in (latest_raw or [])]
        project = {
            "name": repo.get("name") or name,
            "full_name": name,
            "description": repo.get("description") or "",
            "url": repo.get("html_url") or "",
            "updated_at": repo.get("updated_at") or "",
            "pushed_at": repo.get("pushed_at") or "",
            "private": private,
            "open_issues": issues,
            "open_prs": prs,
            "latest_commit": latest[0] if latest else None,
            "recent_commit_count": len(recent_raw or []),
            "status": core.project_status(issues, prs),
            "completion": progress,
            "authority_exception": authority_exception,
        }
        project["filter_tags"] = core.project_tags(project)
        projects.append(project)

    return core.rank_projects(projects, now), errors, now


def base_data(
    projects: list[dict[str, Any]],
    ranked_count: int,
    errors: list[str],
    now: dt.datetime,
    view: str,
) -> dict[str, Any]:
    data = {
        "view": view,
        "owner": core.OWNER,
        "generated_at": now.isoformat(),
        "activity_window_days": core.WINDOW_DAYS,
        "scanned_candidate_count": ranked_count,
        "project_count": len(projects),
        "projects": projects,
        "errors": errors,
    }
    data["summary"] = core.summary_for(projects)
    data["completion_summary"] = completion.summary_for(projects, include_private=view == "private")
    return data


def build_public_data(
    ranked: list[dict[str, Any]], errors: list[str], now: dt.datetime
) -> dict[str, Any]:
    """Public view contains every ranked candidate without authority-exception data."""
    projects = [core.public_project(project, rank) for rank, project in enumerate(ranked, 1)]
    for project in projects:
        project.pop("authority_exception", None)
    data = base_data(projects, len(ranked), errors, now, "public")
    data["priority"] = core.priority_for(projects)
    return data


def owner_priority(projects: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    """Action list for the owner view; private projects are allowed."""
    candidates: list[tuple[int, str, dict[str, Any], dict[str, Any], str, str]] = []
    for project in projects:
        if project["open_prs"]:
            item = project["open_prs"][0]
            candidates.append(
                (1, item.get("updated_at", ""), project, item, "pr", "Open PR needs review or merge decision.")
            )
        chosen = next(
            (
                issue
                for issue in project["open_issues"]
                if any(core.has_label(issue, label) for label in ("blocked", "review", "next", "home-pc"))
            ),
            project["open_issues"][0] if project["open_issues"] else None,
        )
        if chosen:
            candidates.append(
                (
                    0 if project["status"] == "blocked" else 4,
                    chosen.get("updated_at", ""),
                    project,
                    chosen,
                    "issue",
                    "Open issue.",
                )
            )

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=False)
    return [
        {
            "project": project["full_name"],
            "kind": kind,
            "title": item["title"],
            "number": item["number"],
            "url": item["url"],
            "reason": reason,
        }
        for _, _, project, item, kind, reason in candidates[:limit]
    ]


def build_private_data(
    ranked: list[dict[str, Any]],
    errors: list[str],
    now: dt.datetime,
    limit: int | None = None,
) -> dict[str, Any]:
    """Owner view contains the top repositories plus the full private exception queue."""
    limit = core.PROJECT_LIMIT if limit is None else limit
    projects: list[dict[str, Any]] = []
    for rank, project in enumerate(ranked[: max(0, limit)], 1):
        item = copy.deepcopy(project)
        item["rank"] = rank
        projects.append(item)
    data = base_data(projects, len(ranked), errors, now, "private")
    data["priority"] = owner_priority(projects)
    queue = exceptions.queue_for(ranked)
    data["authority_exception_queue"] = queue
    data["authority_exception_summary"] = exceptions.summary_for(queue)
    return data


def _inject_completion(html_text: str, data: dict[str, Any]) -> str:
    section = completion.render_html(data)
    marker = "</main>"
    return html_text.replace(marker, f"{section}{marker}", 1)


def _inject_authority_exceptions(html_text: str, data: dict[str, Any]) -> str:
    section = exceptions.render_html(data)
    marker = "</main>"
    return html_text.replace(marker, f"{section}{marker}", 1)


def render_public_html(data: dict[str, Any]) -> str:
    html_text = (
        core.render_html(data)
        .replace(
            "Live top-five activity view generated from GitHub.",
            "Public all-repository activity and completion surface generated from GitHub.",
        )
        .replace("Top five by recent activity.", "All discovered repositories by recent activity.")
    )
    return _inject_completion(html_text, data)


def render_private_html(data: dict[str, Any]) -> str:
    render_data = copy.deepcopy(data)
    for project in render_data["projects"]:
        project["private"] = False
    html_text = (
        core.render_html(render_data)
        .replace(
            "Live top-five activity view generated from GitHub.",
            "Private owner dashboard for the five busiest repositories.",
        )
        .replace("public issues", "issues")
        .replace("public PRs", "PRs")
        .replace("No public priority items found.", "No priority items found.")
    )
    return _inject_authority_exceptions(_inject_completion(html_text, data), data)


def owner_home_markdown(data: dict[str, Any]) -> str:
    lines = ["# Home-Machine Tasks", "", "Generated from top-five owner dashboard issues labelled `home-pc`.", ""]
    found = False
    for project in data["projects"]:
        for item in project["open_issues"]:
            if core.has_label(item, "home-pc"):
                found = True
                lines.append(f"- {project['full_name']} #{item['number']} — {item['title']}: {item['url']}")
    if not found:
        lines.append("No `home-pc` labelled tasks found in the private top five.")
    return "\n".join(lines).strip() + "\n"


def write_public_outputs(data: dict[str, Any]) -> None:
    PUBLIC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_OUT_DIR / "status.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (PUBLIC_OUT_DIR / "index.html").write_text(render_public_html(data), encoding="utf-8")
    (PUBLIC_OUT_DIR / "project-status.md").write_text(core.render_project_markdown(data), encoding="utf-8")
    (PUBLIC_OUT_DIR / "completion-status.md").write_text(completion.render_markdown(data), encoding="utf-8")
    (PUBLIC_OUT_DIR / "home-pc-tasks.md").write_text(core.render_home_markdown(data), encoding="utf-8")


def write_private_outputs(data: dict[str, Any]) -> None:
    PRIVATE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (PRIVATE_OUT_DIR / "status.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (PRIVATE_OUT_DIR / "index.html").write_text(render_private_html(data), encoding="utf-8")
    (PRIVATE_OUT_DIR / "project-status.md").write_text(core.render_project_markdown(data), encoding="utf-8")
    (PRIVATE_OUT_DIR / "completion-status.md").write_text(completion.render_markdown(data), encoding="utf-8")
    (PRIVATE_OUT_DIR / "authority-exceptions.md").write_text(exceptions.render_markdown(data), encoding="utf-8")
    (PRIVATE_OUT_DIR / "home-pc-tasks.md").write_text(owner_home_markdown(data), encoding="utf-8")


def build_views(
    ranked: list[dict[str, Any]], errors: list[str], now: dt.datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_public_data(ranked, errors, now), build_private_data(ranked, errors, now)


def main() -> int:
    ranked, errors, now = collect_ranked()
    public_data, private_data = build_views(ranked, errors, now)
    write_public_outputs(public_data)
    write_private_outputs(private_data)
    print(
        f"Generated public view for {public_data['project_count']} repositories and private top "
        f"{private_data['project_count']} from {public_data['scanned_candidate_count']} candidates."
    )
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
