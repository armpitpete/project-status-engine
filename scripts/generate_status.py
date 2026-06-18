#!/usr/bin/env python3
"""Generate a static project status site from GitHub repository data.

The source of truth is GitHub itself: repositories, issues, pull requests,
labels, and recent commits. Generated files are outputs, not manual records.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
OWNER = os.getenv("STATUS_OWNER", "armpitpete")
MAX_REPOS = int(os.getenv("STATUS_MAX_REPOS", "30"))
MAX_ITEMS = int(os.getenv("STATUS_MAX_ITEMS", "8"))
TOKEN = os.getenv("PROJECT_STATUS_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
OUT_DIR = Path(os.getenv("STATUS_OUT_DIR", "public"))

STATUS_LABELS = {
    "next",
    "home-pc",
    "blocked",
    "waiting-user",
    "review",
    "safe-to-continue",
    "move-to-new-chat",
}

STATUS_ORDER = ["blocked", "review", "active", "clear"]


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def api_get(path: str, query: dict[str, str | int] | None = None) -> Any:
    if query:
        path = f"{path}?{urllib.parse.urlencode(query)}"
    url = path if path.startswith("http") else f"{API_ROOT}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "project-status-engine",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {body[:500]}") from exc


def safe_api_get(path: str, query: dict[str, str | int] | None = None) -> tuple[Any | None, str | None]:
    try:
        return api_get(path, query), None
    except Exception as exc:  # noqa: BLE001 - failure should be recorded in output
        return None, str(exc)


def iso_to_display(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.replace("T", " ").replace("Z", " UTC")


def label_names(item: dict[str, Any]) -> list[str]:
    labels = item.get("labels") or []
    return sorted(str(label.get("name", "")) for label in labels if label.get("name"))


def has_status_label(item: dict[str, Any], name: str) -> bool:
    return name in item.get("status_labels", [])


def extract_issue(item: dict[str, Any]) -> dict[str, Any]:
    labels = label_names(item)
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled issue",
        "url": item.get("html_url") or "",
        "updated_at": item.get("updated_at"),
        "labels": labels,
        "status_labels": [label for label in labels if label in STATUS_LABELS],
    }


def extract_pr(item: dict[str, Any]) -> dict[str, Any]:
    labels = label_names(item)
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled PR",
        "url": item.get("html_url") or "",
        "updated_at": item.get("updated_at"),
        "draft": bool(item.get("draft")),
        "labels": labels,
        "status_labels": [label for label in labels if label in STATUS_LABELS],
    }


def extract_commit(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") or {}
    message = (commit.get("message") or "").splitlines()[0]
    author = commit.get("author") or {}
    return {
        "sha": (item.get("sha") or "")[:7],
        "message": message or "No commit message",
        "url": item.get("html_url") or "",
        "date": author.get("date"),
    }


def project_status(issues: list[dict[str, Any]], pulls: list[dict[str, Any]]) -> str:
    if any(has_status_label(issue, "blocked") for issue in issues):
        return "blocked"
    if pulls or any(has_status_label(issue, "review") for issue in issues):
        return "review"
    if issues:
        return "active"
    return "clear"


def project_filter_tags(project: dict[str, Any]) -> list[str]:
    tags = {"all", project["status"]}
    for issue in project["open_issues"]:
        for label in issue.get("status_labels", []):
            if label in {"next", "home-pc", "blocked", "review"}:
                tags.add(label)
    for pr in project["open_prs"]:
        tags.add("review")
        for label in pr.get("status_labels", []):
            if label in {"next", "home-pc", "blocked", "review"}:
                tags.add(label)
    return sorted(tags)


def collect() -> dict[str, Any]:
    generated_at = now_utc()
    errors: list[str] = []
    repos_raw, repos_error = safe_api_get(
        f"/users/{OWNER}/repos",
        {"sort": "updated", "direction": "desc", "per_page": MAX_REPOS},
    )
    if repos_error:
        errors.append(repos_error)
        repos_raw = []

    projects: list[dict[str, Any]] = []
    for repo in repos_raw or []:
        if repo.get("archived") or repo.get("fork"):
            continue
        full_name = repo.get("full_name")
        if not full_name:
            continue

        time.sleep(0.05)
        issues_raw, issue_error = safe_api_get(
            f"/repos/{full_name}/issues",
            {"state": "open", "per_page": MAX_ITEMS},
        )
        pulls_raw, pull_error = safe_api_get(
            f"/repos/{full_name}/pulls",
            {"state": "open", "per_page": MAX_ITEMS},
        )
        commits_raw, commit_error = safe_api_get(
            f"/repos/{full_name}/commits",
            {"per_page": 1},
        )

        for err in (issue_error, pull_error, commit_error):
            if err:
                errors.append(f"{full_name}: {err}")

        issues = [
            extract_issue(item)
            for item in (issues_raw or [])
            if not item.get("pull_request")
        ]
        pulls = [extract_pr(item) for item in (pulls_raw or [])]
        commits = [extract_commit(item) for item in (commits_raw or [])]

        status = project_status(issues, pulls)
        project = {
            "name": repo.get("name"),
            "full_name": full_name,
            "description": repo.get("description") or "",
            "url": repo.get("html_url") or "",
            "updated_at": repo.get("updated_at"),
            "status": status,
            "open_issues": issues,
            "open_prs": pulls,
            "latest_commit": commits[0] if commits else None,
        }
        project["filter_tags"] = project_filter_tags(project)
        projects.append(project)

    data = {
        "owner": OWNER,
        "generated_at": generated_at,
        "project_count": len(projects),
        "projects": projects,
        "errors": errors,
    }
    data["summary"] = build_summary(projects)
    data["priority"] = build_priority(projects, limit=5)
    return data


def build_summary(projects: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in STATUS_ORDER}
    label_counts = {label: 0 for label in sorted(STATUS_LABELS)}
    total_issues = 0
    total_prs = 0

    for project in projects:
        status_counts[project["status"]] = status_counts.get(project["status"], 0) + 1
        total_prs += len(project["open_prs"])
        total_issues += len(project["open_issues"])
        for issue in project["open_issues"]:
            for label in issue["status_labels"]:
                label_counts[label] = label_counts.get(label, 0) + 1
        for pr in project["open_prs"]:
            for label in pr["status_labels"]:
                label_counts[label] = label_counts.get(label, 0) + 1

    attention_count = status_counts.get("blocked", 0) + status_counts.get("review", 0)
    return {
        "status_counts": status_counts,
        "label_counts": label_counts,
        "total_issues": total_issues,
        "total_prs": total_prs,
        "attention_count": attention_count,
    }


def priority_rank(project: dict[str, Any], item: dict[str, Any] | None, kind: str) -> tuple[int, str]:
    if project["status"] == "blocked":
        return (0, project.get("updated_at") or "")
    if kind == "pr" or project["status"] == "review":
        return (1, project.get("updated_at") or "")
    if item and has_status_label(item, "next"):
        return (2, item.get("updated_at") or "")
    if item and has_status_label(item, "home-pc"):
        return (3, item.get("updated_at") or "")
    if project["status"] == "active":
        return (4, project.get("updated_at") or "")
    return (5, project.get("updated_at") or "")


def build_priority(projects: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    for project in projects:
        if project["open_prs"]:
            pr = project["open_prs"][0]
            candidates.append(
                {
                    "project": project["full_name"],
                    "project_url": project["url"],
                    "kind": "pr",
                    "title": pr["title"],
                    "number": pr["number"],
                    "url": pr["url"],
                    "reason": "Open PR needs review or merge decision.",
                    "rank": priority_rank(project, pr, "pr"),
                }
            )

        selected_issue = None
        reason = None
        for label, label_reason in (
            ("blocked", "Blocked item needs clearing."),
            ("review", "Issue is marked for review."),
            ("next", "Issue is marked as next."),
            ("home-pc", "Issue needs the home machine."),
        ):
            selected_issue = next(
                (issue for issue in project["open_issues"] if has_status_label(issue, label)),
                None,
            )
            if selected_issue:
                reason = label_reason
                break

        if not selected_issue and project["open_issues"]:
            selected_issue = project["open_issues"][0]
            reason = "Recent open issue."

        if selected_issue:
            candidates.append(
                {
                    "project": project["full_name"],
                    "project_url": project["url"],
                    "kind": "issue",
                    "title": selected_issue["title"],
                    "number": selected_issue["number"],
                    "url": selected_issue["url"],
                    "reason": reason or "Open issue.",
                    "rank": priority_rank(project, selected_issue, "issue"),
                }
            )

    candidates.sort(key=lambda item: (item["rank"][0], item["rank"][1]), reverse=False)
    return candidates[:limit]


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def issue_link(item: dict[str, Any]) -> str:
    labels = item.get("status_labels") or item.get("labels") or []
    label_text = "" if not labels else " " + " ".join(f"<span class='label'>{esc(label)}</span>" for label in labels)
    return f"<li><a href='{esc(item['url'])}'>#{esc(item['number'])} — {esc(item['title'])}</a>{label_text}</li>"


def render_count_bar(label: str, value: int, total: int) -> str:
    width = 0 if total <= 0 else max(4, int((value / total) * 100))
    return f"""
<div class="bar-row">
  <div class="bar-label">{esc(label)}</div>
  <div class="bar-track"><div class="bar-fill" style="width: {width}%"></div></div>
  <div class="bar-value">{esc(value)}</div>
</div>
"""


def render_summary_graphics(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    status_counts = summary.get("status_counts") or {}
    total_projects = max(1, data.get("project_count", 0))
    bars = "\n".join(
        render_count_bar(status, int(status_counts.get(status, 0)), total_projects)
        for status in STATUS_ORDER
    )

    labels = summary.get("label_counts") or {}
    useful_labels = ["next", "home-pc", "blocked", "waiting-user", "review", "move-to-new-chat"]
    label_pills = "\n".join(
        f"<span class='metric-pill'><strong>{esc(labels.get(label, 0))}</strong>{esc(label)}</span>"
        for label in useful_labels
    )

    return f"""
<section class="visual-grid">
  <div class="panel visual-panel">
    <h2>Project shape</h2>
    <p class="muted">Automatic count by current status.</p>
    {bars}
  </div>
  <div class="panel visual-panel attention-panel">
    <h2>Attention map</h2>
    <div class="big-number">{esc(summary.get('attention_count', 0))}</div>
    <p>Projects need review or are blocked.</p>
    <div class="mini-metrics">
      <span><strong>{esc(summary.get('total_issues', 0))}</strong> open issues</span>
      <span><strong>{esc(summary.get('total_prs', 0))}</strong> open PRs</span>
    </div>
  </div>
  <div class="panel visual-panel">
    <h2>Status labels</h2>
    <p class="muted">Counts from recognised labels.</p>
    <div class="metric-pills">{label_pills}</div>
  </div>
</section>
"""


def render_priority(data: dict[str, Any]) -> str:
    items = data.get("priority") or []
    if not items:
        return "<ol><li>No priority items found.</li></ol>"

    rows = []
    for item in items:
        marker = "PR" if item["kind"] == "pr" else "Issue"
        rows.append(
            f"""
<li class="priority-item">
  <div class="priority-main">
    <span class="priority-kind">{esc(marker)}</span>
    <a href="{esc(item['url'])}">#{esc(item['number'])} — {esc(item['title'])}</a>
  </div>
  <div class="priority-meta">
    <a href="{esc(item['project_url'])}">{esc(item['project'])}</a>
    <span>{esc(item['reason'])}</span>
  </div>
</li>
"""
        )
    return "<ol class='priority-list'>" + "\n".join(rows) + "</ol>"


def render_filter_links(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    labels = summary.get("label_counts") or {}
    status_counts = summary.get("status_counts") or {}
    filters = [
        ("projects", "All", data.get("project_count", 0)),
        ("filter-review", "Review", status_counts.get("review", 0) + labels.get("review", 0)),
        ("filter-blocked", "Blocked", status_counts.get("blocked", 0) + labels.get("blocked", 0)),
        ("filter-home-pc", "Home PC", labels.get("home-pc", 0)),
        ("filter-next", "Next", labels.get("next", 0)),
        ("filter-clear", "Clear", status_counts.get("clear", 0)),
    ]
    return "\n".join(
        f"<a class='filter-chip' href='#{esc(anchor)}'>{esc(label)} <strong>{esc(count)}</strong></a>"
        for anchor, label, count in filters
    )


def render_project_summary(project: dict[str, Any]) -> str:
    latest = project.get("latest_commit")
    latest_text = "No commit found."
    if latest:
        latest_text = f"{esc(latest['sha'])} — {esc(latest['message'])}"
    return f"""
<div class="project-summary">
  <span>{esc(len(project['open_issues']))} issues</span>
  <span>{esc(len(project['open_prs']))} PRs</span>
  <span>{latest_text}</span>
</div>
"""


def render_project_card(project: dict[str, Any], open_by_default: bool = False) -> str:
    issues = project["open_issues"]
    prs = project["open_prs"]
    issues_html = "\n".join(issue_link(issue) for issue in issues[:MAX_ITEMS]) or "<li>No open issues found.</li>"
    prs_html = "\n".join(issue_link(pr) for pr in prs[:MAX_ITEMS]) or "<li>No open PRs found.</li>"
    commit = project.get("latest_commit")
    commit_html = "No commit found."
    if commit:
        commit_html = f"<a href='{esc(commit['url'])}'>{esc(commit['sha'])}</a> — {esc(commit['message'])}"

    open_attr = " open" if open_by_default else ""
    tags = " ".join(f"tag-{tag}" for tag in project.get("filter_tags", []))
    return f"""
<details class="card compact-card status-{esc(project['status'])} {esc(tags)}"{open_attr}>
  <summary>
    <span class="project-title"><a href="{esc(project['url'])}">{esc(project['full_name'])}</a></span>
    <span class="status">{esc(project['status'])}</span>
    {render_project_summary(project)}
  </summary>
  <div class="project-detail">
    <p>{esc(project.get('description') or 'No repository description.')}</p>
    <p class="muted">Updated: {esc(iso_to_display(project.get('updated_at')))}</p>
    <h3>Open issues</h3>
    <ul>{issues_html}</ul>
    <h3>Open PRs</h3>
    <ul>{prs_html}</ul>
    <h3>Latest commit</h3>
    <p>{commit_html}</p>
  </div>
</details>
"""


def render_project_section(title: str, anchor: str, projects: list[dict[str, Any]]) -> str:
    if not projects:
        return f"""
<section id="{esc(anchor)}" class="project-group panel">
  <h2>{esc(title)}</h2>
  <p class="muted">No matching projects.</p>
</section>
"""
    cards = "\n".join(render_project_card(project) for project in projects)
    return f"""
<section id="{esc(anchor)}" class="project-group">
  <h2>{esc(title)} <span class="group-count">{esc(len(projects))}</span></h2>
  <div class="cards compact-cards">
    {cards}
  </div>
</section>
"""


def projects_with_tag(data: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    return [project for project in data["projects"] if tag in project.get("filter_tags", [])]


def render_project_groups(data: dict[str, Any]) -> str:
    groups = [
        ("All projects", "projects", data["projects"]),
        ("Needs review", "filter-review", projects_with_tag(data, "review")),
        ("Blocked", "filter-blocked", projects_with_tag(data, "blocked")),
        ("Home PC", "filter-home-pc", projects_with_tag(data, "home-pc")),
        ("Next", "filter-next", projects_with_tag(data, "next")),
        ("Clear", "filter-clear", [project for project in data["projects"] if project["status"] == "clear"]),
    ]
    return "\n".join(render_project_section(title, anchor, projects) for title, anchor, projects in groups)


def render_html(data: dict[str, Any]) -> str:
    home_items = []
    for project in data["projects"]:
        home = [issue for issue in project["open_issues"] if "home-pc" in issue.get("status_labels", [])]
        for issue in home:
            home_items.append((project, issue))

    home_html = "\n".join(
        f"<li><strong>{esc(project['name'])}</strong>: <a href='{esc(issue['url'])}'>#{esc(issue['number'])} — {esc(issue['title'])}</a></li>"
        for project, issue in home_items
    ) or "<li>No `home-pc` labelled tasks found.</li>"

    errors_html = "\n".join(f"<li>{esc(error)}</li>" for error in data.get("errors", [])) or "<li>No scan errors.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project Status Engine</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: #f5f6f8; color: #20262c; }}
    header {{ padding: 2rem; background: #20262c; color: white; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem; }}
    a {{ color: #185abc; }}
    .summary, .visual-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
    .panel, .card {{ background: white; border: 1px solid #d9dde3; border-radius: 14px; padding: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
    .cards {{ display: grid; gap: 0.75rem; }}
    h1, h2, h3 {{ margin-top: 0; }}
    h2 {{ font-size: 1.05rem; }}
    h3 {{ font-size: 0.95rem; margin-bottom: 0.25rem; }}
    ul {{ padding-left: 1.25rem; }}
    li {{ margin: 0.25rem 0; }}
    .muted {{ color: #5e6673; font-size: 0.92rem; }}
    .status, .label, .priority-kind, .metric-pill, .group-count {{ display: inline-block; border-radius: 999px; padding: 0.15rem 0.5rem; background: #edf0f4; font-size: 0.78rem; }}
    .status-blocked .status {{ background: #ffe2e2; }}
    .status-review .status {{ background: #fff0c2; }}
    .status-active .status {{ background: #e3f2ff; }}
    .control-strip {{ position: sticky; top: 0; z-index: 5; margin: -0.25rem 0 1rem; padding: 0.6rem; background: rgba(245,246,248,0.94); backdrop-filter: blur(8px); border: 1px solid #d9dde3; border-radius: 14px; }}
    .filter-chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
    .filter-chip {{ text-decoration: none; border: 1px solid #d9dde3; border-radius: 999px; padding: 0.35rem 0.65rem; background: white; color: #20262c; }}
    .filter-chip:hover, .filter-chip:focus {{ border-color: #20262c; }}
    .priority-list {{ list-style: none; padding: 0; display: grid; gap: 0.65rem; }}
    .priority-item {{ margin: 0; padding: 0.75rem; border: 1px solid #e3e7ed; border-radius: 12px; background: #fbfcfe; }}
    .priority-main {{ display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; }}
    .priority-meta {{ color: #5e6673; font-size: 0.9rem; display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.3rem; }}
    .priority-kind {{ background: #20262c; color: white; }}
    .visual-panel {{ min-height: 175px; }}
    .attention-panel {{ display: flex; flex-direction: column; justify-content: space-between; }}
    .bar-row {{ display: grid; grid-template-columns: 4.5rem 1fr 2rem; gap: 0.5rem; align-items: center; margin: 0.55rem 0; }}
    .bar-label, .bar-value {{ font-size: 0.85rem; color: #5e6673; }}
    .bar-track {{ height: 0.7rem; border-radius: 999px; background: #edf0f4; overflow: hidden; }}
    .bar-fill {{ height: 100%; border-radius: 999px; background: #20262c; }}
    .big-number {{ font-size: 3.6rem; line-height: 1; font-weight: 750; color: #20262c; }}
    .mini-metrics, .metric-pills {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
    .mini-metrics span {{ border: 1px solid #e3e7ed; border-radius: 10px; padding: 0.45rem 0.6rem; background: #fbfcfe; }}
    .metric-pill {{ display: inline-flex; gap: 0.35rem; align-items: center; }}
    .project-group {{ scroll-margin-top: 4rem; margin-top: 1.25rem; }}
    .compact-card {{ padding: 0; overflow: hidden; }}
    .compact-card summary {{ cursor: pointer; list-style: none; padding: 0.85rem 1rem; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem; align-items: center; }}
    .compact-card summary::-webkit-details-marker {{ display: none; }}
    .compact-card summary::before {{ content: "＋"; color: #5e6673; margin-right: 0.4rem; }}
    .compact-card[open] summary::before {{ content: "−"; }}
    .project-title {{ font-weight: 700; overflow-wrap: anywhere; }}
    .project-summary {{ grid-column: 1 / -1; display: flex; gap: 0.55rem; flex-wrap: wrap; color: #5e6673; font-size: 0.85rem; }}
    .project-summary span {{ background: #f5f6f8; border-radius: 999px; padding: 0.18rem 0.5rem; }}
    .project-detail {{ border-top: 1px solid #e3e7ed; padding: 1rem; }}
    footer {{ color: #5e6673; padding: 1rem 2rem 2rem; text-align: center; }}
    @media (max-width: 620px) {{
      header {{ padding: 1.25rem; }}
      main {{ padding: 1rem; }}
      .compact-card summary {{ grid-template-columns: 1fr; }}
      .bar-row {{ grid-template-columns: 4rem 1fr 1.5rem; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Project Status Engine</h1>
    <p>Generated from GitHub data. Do not maintain this by hand.</p>
  </header>
  <main>
    <section class="summary">
      <div class="panel"><strong>Owner</strong><br>{esc(data['owner'])}</div>
      <div class="panel"><strong>Generated</strong><br>{esc(data['generated_at'])}</div>
      <div class="panel"><strong>Projects scanned</strong><br>{esc(data['project_count'])}</div>
    </section>

    <nav class="control-strip" aria-label="Project filters">
      <div class="filter-chips">{render_filter_links(data)}</div>
    </nav>

    <section class="panel">
      <h2>Do Next</h2>
      <p class="muted">Automatic priority list from PRs, issues, labels, and recency.</p>
      {render_priority(data)}
    </section>

    {render_summary_graphics(data)}

    <section class="panel">
      <h2>Home-machine tasks</h2>
      <ul>{home_html}</ul>
    </section>

    <section class="panel">
      <h2>Scan notes</h2>
      <ul>{errors_html}</ul>
    </section>

    {render_project_groups(data)}
  </main>
  <footer>Generated automatically. Source of truth: GitHub repositories, issues, PRs, labels, and commits.</footer>
</body>
</html>
"""


def render_project_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Project Status",
        "",
        "Generated automatically from GitHub data. Do not edit this as a manual dashboard.",
        "",
        f"Owner: `{data['owner']}`",
        f"Generated: `{data['generated_at']}`",
        "",
        "## Do Next",
        "",
    ]

    if data.get("priority"):
        for item in data["priority"]:
            lines.append(f"- {item['project']} #{item['number']} — {item['title']}: {item['url']}")
    else:
        lines.append("- No priority items found.")

    lines.extend(["", "## Projects", ""])
    for project in data["projects"]:
        lines.extend(
            [
                f"### {project['full_name']}",
                "",
                f"Status: `{project['status']}`",
                f"Updated: `{iso_to_display(project.get('updated_at'))}`",
                f"Repo: {project['url']}",
                "",
                "#### Open issues",
            ]
        )
        if project["open_issues"]:
            for issue in project["open_issues"]:
                label_text = "" if not issue["status_labels"] else f" [{' '.join(issue['status_labels'])}]"
                lines.append(f"- #{issue['number']} — {issue['title']}{label_text}: {issue['url']}")
        else:
            lines.append("- None found.")
        lines.extend(["", "#### Open PRs"])
        if project["open_prs"]:
            for pr in project["open_prs"]:
                label_text = "" if not pr["status_labels"] else f" [{' '.join(pr['status_labels'])}]"
                draft = " [draft]" if pr.get("draft") else ""
                lines.append(f"- #{pr['number']} — {pr['title']}{draft}{label_text}: {pr['url']}")
        else:
            lines.append("- None found.")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_home_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Home-Machine Tasks",
        "",
        "Generated automatically from issues labelled `home-pc`.",
        "",
    ]
    found = False
    for project in data["projects"]:
        home_issues = [issue for issue in project["open_issues"] if "home-pc" in issue.get("status_labels", [])]
        if not home_issues:
            continue
        found = True
        lines.extend([f"## {project['full_name']}", ""])
        for issue in home_issues:
            lines.append(f"- #{issue['number']} — {issue['title']}: {issue['url']}")
        lines.append("")
    if not found:
        lines.append("No `home-pc` labelled tasks found.")
    return "\n".join(lines).strip() + "\n"


def write_outputs(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "status.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "index.html").write_text(render_html(data), encoding="utf-8")
    (OUT_DIR / "project-status.md").write_text(render_project_markdown(data), encoding="utf-8")
    (OUT_DIR / "home-pc-tasks.md").write_text(render_home_markdown(data), encoding="utf-8")


def main() -> int:
    data = collect()
    write_outputs(data)
    print(f"Generated status for {data['project_count']} projects in {OUT_DIR}")
    if data.get("errors"):
        print("Scan completed with recorded errors:", file=sys.stderr)
        for error in data["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
