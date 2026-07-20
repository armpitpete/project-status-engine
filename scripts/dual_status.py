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

import authority_exception_details as exception_details
import authority_exceptions as exceptions
import completion_status as completion
import live_status as core

PUBLIC_OUT_DIR = Path(os.getenv("STATUS_OUT_DIR", "public"))
PRIVATE_OUT_DIR = Path(os.getenv("PRIVATE_STATUS_OUT_DIR", "private-build"))


def collect_ranked() -> tuple[list[dict[str, Any]], list[str], dt.datetime]:
    """Collect once, then rank once. Every output derives from this result."""
    core.reset_scan_health()
    now = core.now_utc()
    repos, repo_error = core.discover_repositories()
    errors = [repo_error] if repo_error else []
    projects: list[dict[str, Any]] = []
    since = (now - dt.timedelta(days=core.WINDOW_DAYS)).isoformat()

    for repo in repos:
        if repo.get("archived") or repo.get("fork") or not repo.get("full_name"):
            continue
        name = repo["full_name"]
        private = bool(repo.get("private"))
        time.sleep(0.05)
        issues_raw, issue_error = core.safe_get(
            f"/repos/{name}/issues",
            {
                "state": "open",
                "sort": "updated",
                "direction": "desc",
                "per_page": core.MAX_ITEMS,
            },
        )
        prs_raw, pr_error = core.safe_get(
            f"/repos/{name}/pulls",
            {
                "state": "open",
                "sort": "updated",
                "direction": "desc",
                "per_page": core.MAX_ITEMS,
            },
        )
        latest_raw, latest_error = core.safe_get(
            f"/repos/{name}/commits", {"per_page": 1}
        )
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

        issues = [
            core.issue_from(item)
            for item in (issues_raw or [])
            if not item.get("pull_request")
        ]
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
    health = core.scan_health_snapshot(errors)
    data = {
        "schema_version": core.OUTPUT_SCHEMA_VERSION,
        "activity_score_version": core.ACTIVITY_SCORE_VERSION,
        "view": view,
        "owner": core.OWNER,
        "generated_at": now.isoformat(),
        "scan_state": "partial" if errors else "complete",
        "scan_health": health,
        "source_repository_count": ranked_count,
        "activity_window_days": core.WINDOW_DAYS,
        "scanned_candidate_count": ranked_count,
        "project_count": len(projects),
        "projects": projects,
        "errors": errors,
    }
    data["summary"] = core.summary_for(projects)
    data["completion_summary"] = completion.summary_for(
        projects, include_private=view == "private"
    )
    return data


def build_public_data(
    ranked: list[dict[str, Any]], errors: list[str], now: dt.datetime
) -> dict[str, Any]:
    """Public view contains every ranked candidate without owner-only authority data."""
    projects = [
        core.public_project(project, rank) for rank, project in enumerate(ranked, 1)
    ]
    for project in projects:
        project.pop("authority_exception", None)
    data = base_data(projects, len(ranked), errors, now, "public")
    data["priority"] = core.priority_for(projects)
    return data


def owner_priority(
    projects: list[dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    """Action list for the owner view; private projects are allowed."""
    candidates: list[
        tuple[int, str, dict[str, Any], dict[str, Any], str, str]
    ] = []
    for project in projects:
        if project["open_prs"]:
            item = project["open_prs"][0]
            candidates.append(
                (
                    1,
                    item.get("updated_at", ""),
                    project,
                    item,
                    "pr",
                    "Open PR needs review or merge decision.",
                )
            )
        chosen = next(
            (
                issue
                for issue in project["open_issues"]
                if any(
                    core.has_label(issue, label)
                    for label in ("blocked", "review", "next", "home-pc")
                )
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

    candidates.sort(key=lambda row: (row[0], row[1]))
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
    """Owner view contains the top repositories plus the full exception queue."""
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


def _nav(current: str) -> str:
    links = [
        ("index.html", "Overview", "overview"),
        ("projects.html", "Projects", "projects"),
        ("completion.html", "Completion", "completion"),
        ("exceptions.html", "Exceptions", "exceptions"),
        ("operations.html", "Operations", "operations"),
    ]
    return "<nav class='site-nav' aria-label='Owner dashboard'>" + "".join(
        f"<a href='{href}'{' aria-current=\"page\"' if key == current else ''}>{label}</a>"
        for href, label, key in links
    ) + "</nav>"


def _page(title: str, subtitle: str, current: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{core.esc(title)} · Project Status Engine</title>"
        f"<style>{core.css()}</style></head><body>"
        "<a class='skip' href='#content'>Skip to content</a>"
        f"<header><h1>{core.esc(title)}</h1><p>{core.esc(subtitle)}</p>{_nav(current)}</header>"
        f"<main id='content'>{body}</main>"
        f"<footer>Generated automatically from GitHub activity using score contract {core.esc(core.ACTIVITY_SCORE_VERSION)}.</footer>"
        "</body></html>"
    )


def _exception_summary_html(data: dict[str, Any]) -> str:
    summary = data.get("authority_exception_summary") or {}
    total = int(summary.get("total", 0))
    decisions = int(summary.get("owner_decision_required", 0))
    counts = summary.get("counts") or {}
    rows = "".join(
        f"<div class='compact-item'><span>{core.esc(code.replace('_', ' '))}</span><strong>{count}</strong></div>"
        for code, count in counts.items()
        if count
    ) or "<p>No completion-authority exceptions are currently recorded.</p>"
    return (
        "<section class='panel'><h2>Authority exceptions</h2>"
        f"<p><strong>{total}</strong> total; <strong>{decisions}</strong> require an owner decision.</p>"
        f"<div class='compact-list'>{rows}</div>"
        "<p><a href='exceptions.html'>Open the complete exception queue and resolution details</a>.</p></section>"
    )


def render_public_html(data: dict[str, Any]) -> str:
    html_text = core.render_html(data).replace(
        "Repository activity and authority-backed completion.",
        "Public all-repository activity and authority-backed completion.",
    )
    return html_text.replace("</main>", f"{completion.render_html(data)}</main>", 1)


def render_private_html(data: dict[str, Any]) -> str:
    body = (
        f"{core.health_html(data)}"
        f"<section class='panel'><h2>Do Next</h2>{core.priority_html(data)}</section>"
        f"{core.summary_html(data)}{core.heat_html(data)}{_exception_summary_html(data)}"
    )
    return _page(
        "Project Status Engine",
        "Private owner overview for the five busiest repositories.",
        "overview",
        body,
    )


def render_private_projects_html(data: dict[str, Any]) -> str:
    cards = "".join(core.card_html(project) for project in data["projects"])
    body = (
        f"{core.health_html(data)}"
        f"<nav class='control' aria-label='Project filters'>{core.filters_html(data)}</nav>"
        f"{core.heat_html(data)}"
        f"<section><h2>Project detail</h2><div class='cards'>{cards}</div></section>"
        f"{core.script()}"
    )
    return _page(
        "Projects",
        "Detailed top-five issue, pull-request and activity context.",
        "projects",
        body,
    )


def render_private_completion_html(data: dict[str, Any]) -> str:
    return _page(
        "Completion",
        "Authority-backed completion for the current private top five.",
        "completion",
        completion.render_html(data),
    )


def render_private_exceptions_html(data: dict[str, Any]) -> str:
    body = exceptions.render_html(data) + exception_details.render_html(data)
    body += (
        "<section class='panel'><h2>Resolution templates</h2>"
        "<p><a href='authority-resolution-templates.md'>Open the generated owner-decision templates</a>.</p></section>"
    )
    return _page(
        "Authority Exceptions",
        "Complete owner-only exception queue and bounded evidence details.",
        "exceptions",
        body,
    )


def render_private_operations_html(data: dict[str, Any]) -> str:
    errors = "".join(
        f"<li>{core.esc(error)}</li>" for error in data.get("errors", [])
    ) or "<li>No scan errors.</li>"
    body = (
        f"{core.health_html(data)}"
        "<section class='panel'><h2>Generated files</h2><ul>"
        "<li><a href='status.json'>Private machine-readable status</a></li>"
        "<li><a href='project-status.md'>Project activity report</a></li>"
        "<li><a href='completion-status.md'>Completion report</a></li>"
        "<li><a href='authority-exceptions.md'>Authority exception report</a></li>"
        "<li><a href='home-pc-tasks.md'>Home-machine tasks</a></li>"
        "</ul></section>"
        f"<section class='panel'><h2>Scan notes</h2><ul>{errors}</ul></section>"
    )
    return _page(
        "Operations",
        "Freshness, scan health and generated owner reports.",
        "operations",
        body,
    )


def owner_home_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Home-Machine Tasks",
        "",
        "Generated from top-five owner dashboard issues labelled `home-pc`.",
        "",
    ]
    found = False
    for project in data["projects"]:
        for item in project["open_issues"]:
            if core.has_label(item, "home-pc"):
                found = True
                lines.append(
                    f"- {project['full_name']} #{item['number']} — {item['title']}: {item['url']}"
                )
    if not found:
        lines.append("No `home-pc` labelled tasks found in the private top five.")
    return "\n".join(lines).strip() + "\n"


def write_public_outputs(data: dict[str, Any]) -> None:
    PUBLIC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_OUT_DIR / "status.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (PUBLIC_OUT_DIR / "index.html").write_text(
        render_public_html(data), encoding="utf-8"
    )
    (PUBLIC_OUT_DIR / "project-status.md").write_text(
        core.render_project_markdown(data), encoding="utf-8"
    )
    (PUBLIC_OUT_DIR / "completion-status.md").write_text(
        completion.render_markdown(data), encoding="utf-8"
    )
    (PUBLIC_OUT_DIR / "home-pc-tasks.md").write_text(
        core.render_home_markdown(data), encoding="utf-8"
    )


def write_private_outputs(data: dict[str, Any]) -> None:
    PRIVATE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (PRIVATE_OUT_DIR / "status.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    pages = {
        "index.html": render_private_html(data),
        "projects.html": render_private_projects_html(data),
        "completion.html": render_private_completion_html(data),
        "exceptions.html": render_private_exceptions_html(data),
        "operations.html": render_private_operations_html(data),
    }
    for filename, text in pages.items():
        (PRIVATE_OUT_DIR / filename).write_text(text, encoding="utf-8")
    (PRIVATE_OUT_DIR / "project-status.md").write_text(
        core.render_project_markdown(data), encoding="utf-8"
    )
    (PRIVATE_OUT_DIR / "completion-status.md").write_text(
        completion.render_markdown(data), encoding="utf-8"
    )
    exception_markdown = (
        exceptions.render_markdown(data)
        + "\n"
        + exception_details.render_markdown(data)
    )
    (PRIVATE_OUT_DIR / "authority-exceptions.md").write_text(
        exception_markdown, encoding="utf-8"
    )
    (PRIVATE_OUT_DIR / "authority-resolution-templates.md").write_text(
        exceptions.render_resolution_templates(data), encoding="utf-8"
    )
    (PRIVATE_OUT_DIR / "home-pc-tasks.md").write_text(
        owner_home_markdown(data), encoding="utf-8"
    )


def build_views(
    ranked: list[dict[str, Any]], errors: list[str], now: dt.datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    return build_public_data(ranked, errors, now), build_private_data(
        ranked, errors, now
    )


def main() -> int:
    ranked, errors, now = collect_ranked()
    public_data, private_data = build_views(ranked, errors, now)
    write_public_outputs(public_data)
    write_private_outputs(private_data)
    print(
        f"Generated public view for {public_data['project_count']} repositories and "
        f"private top {private_data['project_count']} from "
        f"{public_data['scanned_candidate_count']} candidates."
    )
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
