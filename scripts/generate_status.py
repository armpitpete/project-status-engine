#!/usr/bin/env python3
"""Generate a static project status site from GitHub data.

GitHub is the source of truth. Generated files are outputs, not manual records.
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
STATUS_LABELS = {"next", "home-pc", "blocked", "waiting-user", "review", "safe-to-continue", "move-to-new-chat"}
STATUS_ORDER = ["blocked", "review", "active", "clear"]
FILTERS = [("all", "All"), ("review", "Review"), ("blocked", "Blocked"), ("home-pc", "Home PC"), ("next", "Next"), ("clear", "Clear")]


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


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
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {body[:500]}") from exc


def safe_get(path: str, query: dict[str, str | int] | None = None) -> tuple[Any | None, str | None]:
    try:
        return api_get(path, query), None
    except Exception as exc:  # noqa: BLE001 - record the failure in generated output
        return None, str(exc)


def labels(item: dict[str, Any]) -> list[str]:
    raw = item.get("labels") or []
    return sorted(str(label.get("name", "")) for label in raw if label.get("name"))


def status_labels(item: dict[str, Any]) -> list[str]:
    return [label for label in labels(item) if label in STATUS_LABELS]


def has_label(item: dict[str, Any], label: str) -> bool:
    return label in item.get("status_labels", [])


def display_date(value: str | None) -> str:
    return "unknown" if not value else value.replace("T", " ").replace("Z", " UTC")


def issue_from(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled issue",
        "url": item.get("html_url") or "",
        "updated_at": item.get("updated_at") or "",
        "labels": labels(item),
        "status_labels": status_labels(item),
    }


def pr_from(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled PR",
        "url": item.get("html_url") or "",
        "updated_at": item.get("updated_at") or "",
        "draft": bool(item.get("draft")),
        "labels": labels(item),
        "status_labels": status_labels(item),
    }


def commit_from(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "sha": (item.get("sha") or "")[:7],
        "message": ((commit.get("message") or "No commit message").splitlines() or [""])[0],
        "url": item.get("html_url") or "",
        "date": author.get("date") or "",
    }


def project_status(issues: list[dict[str, Any]], prs: list[dict[str, Any]]) -> str:
    if any(has_label(issue, "blocked") for issue in issues):
        return "blocked"
    if prs or any(has_label(issue, "review") for issue in issues):
        return "review"
    if issues:
        return "active"
    return "clear"


def project_tags(project: dict[str, Any]) -> list[str]:
    tags = {"all", project["status"]}
    for issue in project["open_issues"]:
        tags.update(label for label in issue["status_labels"] if label in {"next", "home-pc", "blocked", "review"})
    for pr in project["open_prs"]:
        tags.add("review")
        tags.update(label for label in pr["status_labels"] if label in {"next", "home-pc", "blocked", "review"})
    return sorted(tags)


def collect() -> dict[str, Any]:
    errors: list[str] = []
    repos_raw, err = safe_get(f"/users/{OWNER}/repos", {"sort": "updated", "direction": "desc", "per_page": MAX_REPOS})
    if err:
        errors.append(err)
        repos_raw = []

    projects: list[dict[str, Any]] = []
    for repo in repos_raw or []:
        if repo.get("archived") or repo.get("fork"):
            continue
        full_name = repo.get("full_name")
        if not full_name:
            continue

        time.sleep(0.05)
        issues_raw, issue_err = safe_get(f"/repos/{full_name}/issues", {"state": "open", "per_page": MAX_ITEMS})
        prs_raw, pr_err = safe_get(f"/repos/{full_name}/pulls", {"state": "open", "per_page": MAX_ITEMS})
        commits_raw, commit_err = safe_get(f"/repos/{full_name}/commits", {"per_page": 1})
        for scan_err in (issue_err, pr_err, commit_err):
            if scan_err:
                errors.append(f"{full_name}: {scan_err}")

        issues = [issue_from(item) for item in (issues_raw or []) if not item.get("pull_request")]
        prs = [pr_from(item) for item in (prs_raw or [])]
        commits = [commit_from(item) for item in (commits_raw or [])]
        project = {
            "name": repo.get("name") or full_name,
            "full_name": full_name,
            "description": repo.get("description") or "",
            "url": repo.get("html_url") or "",
            "updated_at": repo.get("updated_at") or "",
            "open_issues": issues,
            "open_prs": prs,
            "latest_commit": commits[0] if commits else None,
            "status": project_status(issues, prs),
        }
        project["filter_tags"] = project_tags(project)
        projects.append(project)

    data = {"owner": OWNER, "generated_at": now_utc(), "project_count": len(projects), "projects": projects, "errors": errors}
    data["summary"] = summary_for(projects)
    data["priority"] = priority_for(projects)
    return data


def summary_for(projects: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in STATUS_ORDER}
    label_counts = {label: 0 for label in sorted(STATUS_LABELS)}
    issue_count = pr_count = 0
    for project in projects:
        status_counts[project["status"]] = status_counts.get(project["status"], 0) + 1
        issue_count += len(project["open_issues"])
        pr_count += len(project["open_prs"])
        for item in project["open_issues"] + project["open_prs"]:
            for label in item["status_labels"]:
                label_counts[label] = label_counts.get(label, 0) + 1
    return {
        "status_counts": status_counts,
        "label_counts": label_counts,
        "total_issues": issue_count,
        "total_prs": pr_count,
        "attention_count": status_counts.get("blocked", 0) + status_counts.get("review", 0),
    }


def rank(project: dict[str, Any], item: dict[str, Any] | None, kind: str) -> tuple[int, str]:
    if project["status"] == "blocked":
        return (0, project["updated_at"])
    if kind == "pr" or project["status"] == "review":
        return (1, project["updated_at"])
    if item and has_label(item, "next"):
        return (2, item.get("updated_at", ""))
    if item and has_label(item, "home-pc"):
        return (3, item.get("updated_at", ""))
    if project["status"] == "active":
        return (4, project["updated_at"])
    return (5, project["updated_at"])


def priority_for(projects: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for project in projects:
        if project["open_prs"]:
            pr = project["open_prs"][0]
            candidates.append({"project": project["full_name"], "project_url": project["url"], "kind": "pr", "title": pr["title"], "number": pr["number"], "url": pr["url"], "reason": "Open PR needs review or merge decision.", "rank": rank(project, pr, "pr")})
        selected = None
        reason = None
        for label, label_reason in (("blocked", "Blocked item needs clearing."), ("review", "Issue is marked for review."), ("next", "Issue is marked as next."), ("home-pc", "Issue needs the home machine.")):
            selected = next((issue for issue in project["open_issues"] if has_label(issue, label)), None)
            if selected:
                reason = label_reason
                break
        if not selected and project["open_issues"]:
            selected = project["open_issues"][0]
            reason = "Recent open issue."
        if selected:
            candidates.append({"project": project["full_name"], "project_url": project["url"], "kind": "issue", "title": selected["title"], "number": selected["number"], "url": selected["url"], "reason": reason or "Open issue.", "rank": rank(project, selected, "issue")})
    candidates.sort(key=lambda item: (item["rank"][0], item["rank"][1]))
    return candidates[:limit]


def item_link(item: dict[str, Any]) -> str:
    label_html = "" if not item["status_labels"] else " " + " ".join(f"<span class='label'>{esc(label)}</span>" for label in item["status_labels"])
    return f"<li><a href='{esc(item['url'])}'>#{esc(item['number'])} — {esc(item['title'])}</a>{label_html}</li>"


def count_bar(label: str, value: int, total: int) -> str:
    width = 0 if total <= 0 else max(4, int((value / total) * 100))
    return f"<div class='bar-row'><div class='bar-label'>{esc(label)}</div><div class='bar-track'><div class='bar-fill' style='width:{width}%'></div></div><div class='bar-value'>{esc(value)}</div></div>"


def filter_count(data: dict[str, Any], tag: str) -> int:
    if tag == "all":
        return int(data["project_count"])
    if tag == "clear":
        return sum(1 for project in data["projects"] if project["status"] == "clear")
    return sum(1 for project in data["projects"] if tag in project["filter_tags"])


def filter_buttons(data: dict[str, Any]) -> str:
    return "\n".join(
        f"<button class='filter-chip{' active' if index == 0 else ''}' type='button' data-filter='{tag}' aria-pressed='{'true' if index == 0 else 'false'}'>{label} <strong>{filter_count(data, tag)}</strong></button>"
        for index, (tag, label) in enumerate(FILTERS)
    )


def summary_html(data: dict[str, Any]) -> str:
    summary = data["summary"]
    total = max(1, data["project_count"])
    bars = "\n".join(count_bar(status, int(summary["status_counts"].get(status, 0)), total) for status in STATUS_ORDER)
    label_pills = "\n".join(f"<span class='metric-pill'><strong>{summary['label_counts'].get(label, 0)}</strong>{label}</span>" for label in ["next", "home-pc", "blocked", "waiting-user", "review", "move-to-new-chat"])
    return f"""
<section class="visual-grid">
  <div class="panel visual-panel"><h2>Project shape</h2><p class="muted">Automatic count by current status.</p>{bars}</div>
  <div class="panel visual-panel attention-panel"><h2>Attention map</h2><div class="big-number">{esc(summary['attention_count'])}</div><p>Projects need review or are blocked.</p><div class="mini-metrics"><span><strong>{esc(summary['total_issues'])}</strong> open issues</span><span><strong>{esc(summary['total_prs'])}</strong> open PRs</span></div></div>
  <div class="panel visual-panel"><h2>Status labels</h2><p class="muted">Counts from recognised labels.</p><div class="metric-pills">{label_pills}</div></div>
</section>
"""


def priority_html(data: dict[str, Any]) -> str:
    rows = []
    for item in data.get("priority", []):
        marker = "PR" if item["kind"] == "pr" else "Issue"
        rows.append(f"<li class='priority-item'><div class='priority-main'><span class='priority-kind'>{marker}</span><a href='{esc(item['url'])}'>#{esc(item['number'])} — {esc(item['title'])}</a></div><div class='priority-meta'><a href='{esc(item['project_url'])}'>{esc(item['project'])}</a><span>{esc(item['reason'])}</span></div></li>")
    return "<ol><li>No priority items found.</li></ol>" if not rows else "<ol class='priority-list'>" + "\n".join(rows) + "</ol>"


def dots(count: int, maximum: int) -> str:
    spans = "".join(f"<span class='heat-dot{' on' if index < min(count, maximum) else ''}'></span>" for index in range(maximum))
    overflow = f"<span class='heat-overflow'>+{count - maximum}</span>" if count > maximum else ""
    return f"<span class='heat-dots'>{spans}{overflow}</span>"


def heat_map(data: dict[str, Any]) -> str:
    rows = []
    for project in data["projects"]:
        tags = " ".join(project["filter_tags"])
        issue_count = len(project["open_issues"])
        pr_count = len(project["open_prs"])
        status = project["status"]
        rows.append(f"<tr class='heat-row' data-tags='{esc(tags)}'><td><a href='{esc(project['url'])}'>{esc(project['name'])}</a></td><td>{dots(issue_count, 8)} <span class='heat-count'>{issue_count}</span></td><td>{dots(pr_count, 3)} <span class='heat-count'>{pr_count}</span></td><td><span class='status heat-status status-{esc(status)}'>{esc(status)}</span></td></tr>")
    return f"""
<section class="panel heat-map-panel">
  <h2>Project heat map</h2>
  <p class="muted">Quick visual scan of issues, PRs, and state.</p>
  <div class="table-wrap"><table class="heat-map"><thead><tr><th>Project</th><th>Issues</th><th>PRs</th><th>State</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
</section>
"""


def project_summary(project: dict[str, Any]) -> str:
    commit = project.get("latest_commit")
    latest = "No commit found." if not commit else f"{esc(commit['sha'])} — {esc(commit['message'])}"
    return f"<div class='project-summary'><span>{len(project['open_issues'])} issues</span><span>{len(project['open_prs'])} PRs</span><span>{latest}</span></div>"


def project_card(project: dict[str, Any]) -> str:
    issues = "\n".join(item_link(issue) for issue in project["open_issues"][:MAX_ITEMS]) or "<li>No open issues found.</li>"
    prs = "\n".join(item_link(pr) for pr in project["open_prs"][:MAX_ITEMS]) or "<li>No open PRs found.</li>"
    commit = project.get("latest_commit")
    latest = "No commit found." if not commit else f"<a href='{esc(commit['url'])}'>{esc(commit['sha'])}</a> — {esc(commit['message'])}"
    tags = " ".join(project["filter_tags"])
    return f"""
<details class="card compact-card status-{esc(project['status'])}" data-tags="{esc(tags)}">
  <summary><span class="project-title"><a href="{esc(project['url'])}">{esc(project['full_name'])}</a></span><span class="status">{esc(project['status'])}</span>{project_summary(project)}</summary>
  <div class="project-detail"><p>{esc(project['description'] or 'No repository description.')}</p><p class="muted">Updated: {esc(display_date(project['updated_at']))}</p><h3>Open issues</h3><ul>{issues}</ul><h3>Open PRs</h3><ul>{prs}</ul><h3>Latest commit</h3><p>{latest}</p></div>
</details>
"""


def project_list(data: dict[str, Any]) -> str:
    cards = "\n".join(project_card(project) for project in data["projects"])
    return f"<section id='projects' class='project-group'><h2>Projects <span class='group-count' id='visible-count'>{data['project_count']}</span></h2><p class='muted' id='filter-note'>Showing all projects.</p><div class='cards compact-cards' id='project-list'>{cards}</div></section>"


def filter_script() -> str:
    return """
<script>
(function () {
  const buttons = Array.from(document.querySelectorAll('[data-filter]'));
  const cards = Array.from(document.querySelectorAll('.compact-card[data-tags]'));
  const rows = Array.from(document.querySelectorAll('.heat-row[data-tags]'));
  const visibleCount = document.getElementById('visible-count');
  const filterNote = document.getElementById('filter-note');
  function matches(el, filter) { return filter === 'all' || (el.dataset.tags || '').split(' ').includes(filter); }
  function labelFor(filter) {
    const button = buttons.find((item) => item.dataset.filter === filter);
    return button ? button.textContent.replace(/\s+\d+$/, '').trim() : filter;
  }
  function applyFilter(filter) {
    let count = 0;
    cards.forEach((card) => { const show = matches(card, filter); card.hidden = !show; if (show) count += 1; });
    rows.forEach((row) => { row.hidden = !matches(row, filter); });
    buttons.forEach((button) => {
      const active = button.dataset.filter === filter;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    if (visibleCount) visibleCount.textContent = String(count);
    if (filterNote) filterNote.textContent = filter === 'all' ? 'Showing all projects.' : 'Showing ' + labelFor(filter).toLowerCase() + ' projects.';
  }
  buttons.forEach((button) => button.addEventListener('click', () => applyFilter(button.dataset.filter || 'all')));
  applyFilter('all');
})();
</script>
"""


def css() -> str:
    return """
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f6f8;color:#20262c}header{padding:2rem;background:#20262c;color:white}main{max-width:1100px;margin:0 auto;padding:1.5rem}a{color:#185abc}.summary,.visual-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem;margin-bottom:1rem}.panel,.card{background:white;border:1px solid #d9dde3;border-radius:14px;padding:1rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}.cards{display:grid;gap:.75rem}h1,h2,h3{margin-top:0}h2{font-size:1.05rem}h3{font-size:.95rem;margin-bottom:.25rem}ul{padding-left:1.25rem}li{margin:.25rem 0}.muted{color:#5e6673;font-size:.92rem}.status,.label,.priority-kind,.metric-pill,.group-count{display:inline-block;border-radius:999px;padding:.15rem .5rem;background:#edf0f4;font-size:.78rem}.status-blocked .status,.heat-status.status-blocked{background:#ffe2e2}.status-review .status,.heat-status.status-review{background:#fff0c2}.status-active .status,.heat-status.status-active{background:#e3f2ff}.heat-status.status-clear{background:#edf0f4}.control-strip{position:sticky;top:0;z-index:5;margin:-.25rem 0 1rem;padding:.6rem;background:rgba(245,246,248,.94);backdrop-filter:blur(8px);border:1px solid #d9dde3;border-radius:14px}.filter-chips{display:flex;flex-wrap:wrap;gap:.5rem}.filter-chip{border:1px solid #d9dde3;border-radius:999px;padding:.35rem .65rem;background:white;color:#20262c;cursor:pointer;font:inherit}.filter-chip:hover,.filter-chip:focus,.filter-chip.active{border-color:#20262c;background:#20262c;color:white}.priority-list{list-style:none;padding:0;display:grid;gap:.65rem}.priority-item{margin:0;padding:.75rem;border:1px solid #e3e7ed;border-radius:12px;background:#fbfcfe}.priority-main{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap}.priority-meta{color:#5e6673;font-size:.9rem;display:flex;gap:.6rem;flex-wrap:wrap;margin-top:.3rem}.priority-kind{background:#20262c;color:white}.visual-panel{min-height:175px}.attention-panel{display:flex;flex-direction:column;justify-content:space-between}.bar-row{display:grid;grid-template-columns:4.5rem 1fr 2rem;gap:.5rem;align-items:center;margin:.55rem 0}.bar-label,.bar-value{font-size:.85rem;color:#5e6673}.bar-track{height:.7rem;border-radius:999px;background:#edf0f4;overflow:hidden}.bar-fill{height:100%;border-radius:999px;background:#20262c}.big-number{font-size:3.6rem;line-height:1;font-weight:750;color:#20262c}.mini-metrics,.metric-pills{display:flex;flex-wrap:wrap;gap:.5rem}.mini-metrics span{border:1px solid #e3e7ed;border-radius:10px;padding:.45rem .6rem;background:#fbfcfe}.metric-pill{display:inline-flex;gap:.35rem;align-items:center}.heat-map-panel{margin:1rem 0}.table-wrap{overflow-x:auto}.heat-map{width:100%;border-collapse:collapse;font-size:.92rem}.heat-map th,.heat-map td{text-align:left;border-bottom:1px solid #e3e7ed;padding:.55rem .35rem;vertical-align:middle}.heat-map th{color:#5e6673;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}.heat-dots{display:inline-flex;gap:.15rem;align-items:center;min-width:4.8rem}.heat-dot{width:.48rem;height:.48rem;border-radius:999px;background:#edf0f4;display:inline-block}.heat-dot.on{background:#20262c}.heat-count,.heat-overflow{color:#5e6673;font-size:.82rem;margin-left:.25rem}.project-group{scroll-margin-top:4rem;margin-top:1.25rem}.compact-card{padding:0;overflow:hidden}.compact-card summary{cursor:pointer;list-style:none;padding:.85rem 1rem;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:.5rem;align-items:center}.compact-card summary::-webkit-details-marker{display:none}.compact-card summary::before{content:'＋';color:#5e6673;margin-right:.4rem}.compact-card[open] summary::before{content:'−'}.project-title{font-weight:700;overflow-wrap:anywhere}.project-summary{grid-column:1/-1;display:flex;gap:.55rem;flex-wrap:wrap;color:#5e6673;font-size:.85rem}.project-summary span{background:#f5f6f8;border-radius:999px;padding:.18rem .5rem}.project-detail{border-top:1px solid #e3e7ed;padding:1rem}[hidden]{display:none!important}footer{color:#5e6673;padding:1rem 2rem 2rem;text-align:center}@media(max-width:620px){header{padding:1.25rem}main{padding:1rem}.compact-card summary{grid-template-columns:1fr}.bar-row{grid-template-columns:4rem 1fr 1.5rem}}
"""


def render_html(data: dict[str, Any]) -> str:
    home_items = [(project, issue) for project in data["projects"] for issue in project["open_issues"] if "home-pc" in issue["status_labels"]]
    home_html = "\n".join(f"<li><strong>{esc(project['name'])}</strong>: <a href='{esc(issue['url'])}'>#{esc(issue['number'])} — {esc(issue['title'])}</a></li>" for project, issue in home_items) or "<li>No `home-pc` labelled tasks found.</li>"
    errors_html = "\n".join(f"<li>{esc(error)}</li>" for error in data.get("errors", [])) or "<li>No scan errors.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Project Status Engine</title><style>{css()}</style></head>
<body><header><h1>Project Status Engine</h1><p>Generated from GitHub data. Do not maintain this by hand.</p></header><main>
<section class="summary"><div class="panel"><strong>Owner</strong><br>{esc(data['owner'])}</div><div class="panel"><strong>Generated</strong><br>{esc(data['generated_at'])}</div><div class="panel"><strong>Projects scanned</strong><br>{esc(data['project_count'])}</div></section>
<nav class="control-strip" aria-label="Project filters"><div class="filter-chips">{filter_buttons(data)}</div></nav>
<section class="panel"><h2>Do Next</h2><p class="muted">Automatic priority list from PRs, issues, labels, and recency.</p>{priority_html(data)}</section>
{summary_html(data)}
{heat_map(data)}
<section class="panel"><h2>Home-machine tasks</h2><ul>{home_html}</ul></section>
<section class="panel"><h2>Scan notes</h2><ul>{errors_html}</ul></section>
{project_list(data)}
</main><footer>Generated automatically. Source of truth: GitHub repositories, issues, PRs, labels, and commits.</footer>{filter_script()}</body></html>
"""


def render_project_markdown(data: dict[str, Any]) -> str:
    lines = ["# Project Status", "", "Generated automatically from GitHub data. Do not edit this as a manual dashboard.", "", f"Owner: `{data['owner']}`", f"Generated: `{data['generated_at']}`", "", "## Do Next", ""]
    if data.get("priority"):
        for item in data["priority"]:
            lines.append(f"- {item['project']} #{item['number']} — {item['title']}: {item['url']}")
    else:
        lines.append("- No priority items found.")
    lines.extend(["", "## Projects", ""])
    for project in data["projects"]:
        lines.extend([f"### {project['full_name']}", "", f"Status: `{project['status']}`", f"Updated: `{display_date(project.get('updated_at'))}`", f"Repo: {project['url']}", "", "#### Open issues"])
        lines.extend(f"- #{issue['number']} — {issue['title']}{'' if not issue['status_labels'] else ' [' + ' '.join(issue['status_labels']) + ']'}: {issue['url']}" for issue in project["open_issues"]) if project["open_issues"] else lines.append("- None found.")
        lines.extend(["", "#### Open PRs"])
        lines.extend(f"- #{pr['number']} — {pr['title']}{' [draft]' if pr.get('draft') else ''}{'' if not pr['status_labels'] else ' [' + ' '.join(pr['status_labels']) + ']'}: {pr['url']}" for pr in project["open_prs"]) if project["open_prs"] else lines.append("- None found.")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_home_markdown(data: dict[str, Any]) -> str:
    lines = ["# Home-Machine Tasks", "", "Generated automatically from issues labelled `home-pc`.", ""]
    found = False
    for project in data["projects"]:
        home_issues = [issue for issue in project["open_issues"] if "home-pc" in issue["status_labels"]]
        if not home_issues:
            continue
        found = True
        lines.extend([f"## {project['full_name']}", ""])
        lines.extend(f"- #{issue['number']} — {issue['title']}: {issue['url']}" for issue in home_issues)
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
