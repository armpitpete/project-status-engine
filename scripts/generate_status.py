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


def has_label(item: dict[str, Any], name: str) -> bool:
    return name in label_names(item)


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

        status = "clear"
        if any(any(label == "blocked" for label in issue["status_labels"]) for issue in issues):
            status = "blocked"
        elif pulls:
            status = "review"
        elif issues:
            status = "active"

        projects.append(
            {
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
        )

    return {
        "owner": OWNER,
        "generated_at": generated_at,
        "project_count": len(projects),
        "projects": projects,
        "errors": errors,
    }


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def issue_link(item: dict[str, Any]) -> str:
    labels = item.get("status_labels") or item.get("labels") or []
    label_text = "" if not labels else " " + " ".join(f"<span class='label'>{esc(label)}</span>" for label in labels)
    return f"<li><a href='{esc(item['url'])}'>#{esc(item['number'])} — {esc(item['title'])}</a>{label_text}</li>"


def render_html(data: dict[str, Any]) -> str:
    project_cards = []
    home_items = []

    for project in data["projects"]:
        issues = project["open_issues"]
        prs = project["open_prs"]
        home = [issue for issue in issues if "home-pc" in issue.get("status_labels", [])]
        for issue in home:
            home_items.append((project, issue))

        issues_html = "\n".join(issue_link(issue) for issue in issues[:MAX_ITEMS]) or "<li>No open issues found.</li>"
        prs_html = "\n".join(issue_link(pr) for pr in prs[:MAX_ITEMS]) or "<li>No open PRs found.</li>"
        commit = project.get("latest_commit")
        commit_html = "No commit found."
        if commit:
            commit_html = f"<a href='{esc(commit['url'])}'>{esc(commit['sha'])}</a> — {esc(commit['message'])}"

        project_cards.append(
            f"""
<section class="card status-{esc(project['status'])}">
  <div class="card-top">
    <h2><a href="{esc(project['url'])}">{esc(project['full_name'])}</a></h2>
    <span class="status">{esc(project['status'])}</span>
  </div>
  <p>{esc(project.get('description') or 'No repository description.')}</p>
  <p class="muted">Updated: {esc(iso_to_display(project.get('updated_at')))}</p>
  <h3>Open issues</h3>
  <ul>{issues_html}</ul>
  <h3>Open PRs</h3>
  <ul>{prs_html}</ul>
  <h3>Latest commit</h3>
  <p>{commit_html}</p>
</section>
"""
        )

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
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
    .panel, .card {{ background: white; border: 1px solid #d9dde3; border-radius: 14px; padding: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
    .cards {{ display: grid; gap: 1rem; }}
    .card-top {{ display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; }}
    h1, h2, h3 {{ margin-top: 0; }}
    h2 {{ font-size: 1.05rem; }}
    h3 {{ font-size: 0.95rem; margin-bottom: 0.25rem; }}
    ul {{ padding-left: 1.25rem; }}
    li {{ margin: 0.25rem 0; }}
    .muted {{ color: #5e6673; font-size: 0.92rem; }}
    .status, .label {{ display: inline-block; border-radius: 999px; padding: 0.15rem 0.5rem; background: #edf0f4; font-size: 0.78rem; }}
    .status-blocked .status {{ background: #ffe2e2; }}
    .status-review .status {{ background: #fff0c2; }}
    .status-active .status {{ background: #e3f2ff; }}
    footer {{ color: #5e6673; padding: 1rem 2rem 2rem; text-align: center; }}
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

    <section class="panel">
      <h2>Home-machine tasks</h2>
      <ul>{home_html}</ul>
    </section>

    <section class="panel">
      <h2>Scan notes</h2>
      <ul>{errors_html}</ul>
    </section>

    <section class="cards">
      {''.join(project_cards)}
    </section>
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
    ]
    for project in data["projects"]:
        lines.extend(
            [
                f"## {project['full_name']}",
                "",
                f"Status: `{project['status']}`",
                f"Updated: `{iso_to_display(project.get('updated_at'))}`",
                f"Repo: {project['url']}",
                "",
                "### Open issues",
            ]
        )
        if project["open_issues"]:
            for issue in project["open_issues"]:
                label_text = "" if not issue["status_labels"] else f" [{' '.join(issue['status_labels'])}]"
                lines.append(f"- #{issue['number']} — {issue['title']}{label_text}: {issue['url']}")
        else:
            lines.append("- None found.")
        lines.extend(["", "### Open PRs"])
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
