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


def api_get(path: str, query: dict[str, str | int] | None = None) -> Any:
    if query:
        path = f"{path}?{urllib.parse.urlencode(query)}"
    url = path if path.startswith("http") else f"{API_ROOT}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "project-status-engine", "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code} for {url}: {body[:500]}") from exc


def safe_get(path: str, query: dict[str, str | int] | None = None) -> tuple[Any | None, str | None]:
    try:
        return api_get(path, query), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def label_names(item: dict[str, Any]) -> list[str]:
    return sorted(str(label.get("name", "")) for label in item.get("labels", []) if label.get("name"))


def recognised_labels(item: dict[str, Any]) -> list[str]:
    return [label for label in label_names(item) if label in STATUS_LABELS]


def has_label(item: dict[str, Any], label: str) -> bool:
    return label in item.get("status_labels", [])


def clean_date(value: str | None) -> str:
    return "unknown" if not value else value.replace("T", " ").replace("Z", " UTC")


def issue_from(item: dict[str, Any]) -> dict[str, Any]:
    return {"number": item.get("number"), "title": item.get("title") or "Untitled issue", "url": item.get("html_url") or "", "updated_at": item.get("updated_at") or "", "status_labels": recognised_labels(item)}


def pr_from(item: dict[str, Any]) -> dict[str, Any]:
    return {"number": item.get("number"), "title": item.get("title") or "Untitled PR", "url": item.get("html_url") or "", "updated_at": item.get("updated_at") or "", "draft": bool(item.get("draft")), "status_labels": recognised_labels(item)}


def commit_from(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return {"sha": (item.get("sha") or "")[:7], "message": ((commit.get("message") or "No commit message").splitlines() or [""])[0], "url": item.get("html_url") or "", "date": author.get("date") or ""}


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
    for item in project["open_issues"] + project["open_prs"]:
        tags.update(label for label in item["status_labels"] if label in {"next", "home-pc", "blocked", "review"})
    if project["open_prs"]:
        tags.add("review")
    return sorted(tags)


def activity_score(project: dict[str, Any]) -> int:
    score = {"blocked": 120, "review": 100, "active": 50, "clear": 0}.get(project["status"], 0)
    score += min(len(project["open_prs"]), 3) * 25
    score += min(len(project["open_issues"]), 8) * 6
    for item in project["open_issues"] + project["open_prs"]:
        if has_label(item, "blocked"):
            score += 40
        if has_label(item, "review"):
            score += 30
        if has_label(item, "next"):
            score += 28
        if has_label(item, "home-pc"):
            score += 24
        if has_label(item, "waiting-user"):
            score += 10
        if has_label(item, "safe-to-continue"):
            score += 8
    return score


def activity_reason(project: dict[str, Any]) -> str:
    if project["status"] == "blocked":
        return "blocked"
    if project["open_prs"]:
        return "open PR"
    if any(has_label(issue, "next") for issue in project["open_issues"]):
        return "next label"
    if any(has_label(issue, "home-pc") for issue in project["open_issues"]):
        return "home PC"
    if project["open_issues"]:
        return "open issues"
    return "quiet"


def sort_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for project in projects:
        project["activity_score"] = activity_score(project)
        project["activity_reason"] = activity_reason(project)
    return sorted(projects, key=lambda project: (project["activity_score"], project["updated_at"], project["full_name"]), reverse=True)


def collect() -> dict[str, Any]:
    repos, repo_error = safe_get(f"/users/{OWNER}/repos", {"sort": "updated", "direction": "desc", "per_page": MAX_REPOS})
    errors = [repo_error] if repo_error else []
    projects: list[dict[str, Any]] = []
    for repo in repos or []:
        if repo.get("archived") or repo.get("fork"):
            continue
        full_name = repo.get("full_name")
        if not full_name:
            continue
        time.sleep(0.05)
        issues_raw, issue_error = safe_get(f"/repos/{full_name}/issues", {"state": "open", "per_page": MAX_ITEMS})
        prs_raw, pr_error = safe_get(f"/repos/{full_name}/pulls", {"state": "open", "per_page": MAX_ITEMS})
        commits_raw, commit_error = safe_get(f"/repos/{full_name}/commits", {"per_page": 1})
        errors.extend(f"{full_name}: {error}" for error in (issue_error, pr_error, commit_error) if error)
        issues = [issue_from(item) for item in (issues_raw or []) if not item.get("pull_request")]
        prs = [pr_from(item) for item in (prs_raw or [])]
        commits = [commit_from(item) for item in (commits_raw or [])]
        project = {"name": repo.get("name") or full_name, "full_name": full_name, "description": repo.get("description") or "", "url": repo.get("html_url") or "", "updated_at": repo.get("updated_at") or "", "open_issues": issues, "open_prs": prs, "latest_commit": commits[0] if commits else None, "status": project_status(issues, prs)}
        project["filter_tags"] = project_tags(project)
        projects.append(project)

    projects = sort_projects(projects)
    data = {"owner": OWNER, "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "project_count": len(projects), "projects": projects, "errors": errors}
    data["summary"] = summary_for(projects)
    data["priority"] = priority_for(projects)
    return data


def summary_for(projects: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in STATUS_ORDER}
    label_counts = {label: 0 for label in STATUS_LABELS}
    issues = prs = 0
    for project in projects:
        status_counts[project["status"]] += 1
        issues += len(project["open_issues"])
        prs += len(project["open_prs"])
        for item in project["open_issues"] + project["open_prs"]:
            for label in item["status_labels"]:
                label_counts[label] += 1
    return {"status_counts": status_counts, "label_counts": label_counts, "total_issues": issues, "total_prs": prs, "attention_count": status_counts["blocked"] + status_counts["review"]}


def priority_for(projects: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    candidates = []
    for project in projects:
        if project["open_prs"]:
            pr = project["open_prs"][0]
            candidates.append((1, project["updated_at"], project, pr, "pr", "Open PR needs review or merge decision."))
        chosen = next((issue for issue in project["open_issues"] if any(has_label(issue, label) for label in ("blocked", "review", "next", "home-pc"))), None)
        if not chosen and project["open_issues"]:
            chosen = project["open_issues"][0]
        if chosen:
            candidates.append((0 if project["status"] == "blocked" else 4, chosen.get("updated_at", ""), project, chosen, "issue", "Open issue."))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [{"project": project["full_name"], "project_url": project["url"], "kind": kind, "title": item["title"], "number": item["number"], "url": item["url"], "reason": reason} for _, _, project, item, kind, reason in candidates[:limit]]


def item_link(item: dict[str, Any]) -> str:
    label_html = "" if not item["status_labels"] else " " + " ".join(f"<span class='label'>{esc(label)}</span>" for label in item["status_labels"])
    return f"<li><a href='{esc(item['url'])}'>#{esc(item['number'])} — {esc(item['title'])}</a>{label_html}</li>"


def dots(count: int, maximum: int) -> str:
    base = "".join(f"<span class='heat-dot{' on' if index < min(count, maximum) else ''}'></span>" for index in range(maximum))
    extra = f"<span class='heat-count'>+{count - maximum}</span>" if count > maximum else ""
    return f"<span class='heat-dots'>{base}{extra}</span>"


def css() -> str:
    return "body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f6f8;color:#20262c}header{padding:2rem;background:#20262c;color:white}main{max-width:1100px;margin:auto;padding:1.5rem}a{color:#185abc}.panel,.card{background:white;border:1px solid #d9dde3;border-radius:14px;padding:1rem;margin-bottom:1rem;box-shadow:0 1px 2px #0001}.summary,.visual-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.muted,.heat-count{color:#5e6673;font-size:.9rem}.status,.label,.pill,.filter-chip,.signal-pill{border-radius:999px;padding:.18rem .55rem;background:#edf0f4;font-size:.8rem}.signal-pill{background:#20262c;color:white}.status-review{background:#fff0c2}.status-active{background:#e3f2ff}.status-blocked{background:#ffe2e2}.control-strip{position:sticky;top:0;z-index:5;background:#f5f6f8ee;border:1px solid #d9dde3;border-radius:14px;padding:.6rem;margin:1rem 0}.filter-chip{border:1px solid #d9dde3;background:white;cursor:pointer}.filter-chip.active{background:#20262c;color:white}.priority-list{list-style:none;padding:0;display:grid;gap:.6rem}.priority-item{background:#fbfcfe;border:1px solid #e3e7ed;border-radius:12px;padding:.75rem}.visual-grid{margin:1rem 0}.bar{height:.65rem;border-radius:999px;background:#edf0f4;overflow:hidden}.bar span{display:block;height:100%;background:#20262c}.big-number{font-size:3rem;font-weight:750}.heat-map{width:100%;border-collapse:collapse}.heat-map th,.heat-map td{text-align:left;border-bottom:1px solid #e3e7ed;padding:.55rem}.heat-dot{width:.48rem;height:.48rem;border-radius:999px;background:#edf0f4;display:inline-block;margin-right:.15rem}.heat-dot.on{background:#20262c}.cards{display:grid;gap:.75rem}.compact-card{padding:0}.compact-card summary{cursor:pointer;padding:.85rem 1rem;display:grid;grid-template-columns:1fr auto;gap:.5rem}.project-summary{grid-column:1/-1;display:flex;gap:.5rem;flex-wrap:wrap;color:#5e6673;font-size:.85rem}.project-summary span{background:#f5f6f8;border-radius:999px;padding:.18rem .5rem}.project-detail{border-top:1px solid #e3e7ed;padding:1rem}[hidden]{display:none!important}footer{text-align:center;color:#5e6673;padding:2rem}@media(max-width:620px){main{padding:1rem}.compact-card summary{grid-template-columns:1fr}}"


def filter_buttons(data: dict[str, Any]) -> str:
    def count(tag: str) -> int:
        if tag == "all":
            return data["project_count"]
        if tag == "clear":
            return sum(1 for project in data["projects"] if project["status"] == "clear")
        return sum(1 for project in data["projects"] if tag in project["filter_tags"])
    return "".join(f"<button class='filter-chip{' active' if i == 0 else ''}' data-filter='{tag}'>{label} <strong>{count(tag)}</strong></button>" for i, (tag, label) in enumerate(FILTERS))


def summary_html(data: dict[str, Any]) -> str:
    summary = data["summary"]
    total = max(1, data["project_count"])
    bars = "".join(f"<p>{status} {summary['status_counts'][status]}</p><div class='bar'><span style='width:{max(4, int(summary['status_counts'][status] / total * 100))}%'></span></div>" for status in STATUS_ORDER)
    pills = "".join(f"<span class='pill'><strong>{summary['label_counts'].get(label, 0)}</strong> {label}</span> " for label in ["next", "home-pc", "blocked", "waiting-user", "review", "move-to-new-chat"])
    return f"<section class='visual-grid'><div class='panel'><h2>Project shape</h2>{bars}</div><div class='panel'><h2>Attention map</h2><div class='big-number'>{summary['attention_count']}</div><p>{summary['total_issues']} open issues · {summary['total_prs']} open PRs</p></div><div class='panel'><h2>Status labels</h2>{pills}</div></section>"


def priority_html(data: dict[str, Any]) -> str:
    rows = [f"<li class='priority-item'><strong>{item['kind'].upper()}</strong> <a href='{esc(item['url'])}'>#{esc(item['number'])} — {esc(item['title'])}</a><br><span class='muted'>{esc(item['project'])} · {esc(item['reason'])}</span></li>" for item in data["priority"]]
    return "<ol class='priority-list'>" + "".join(rows or ["<li>No priority items found.</li>"]) + "</ol>"


def heat_map(data: dict[str, Any]) -> str:
    rows = ""
    for project in data["projects"]:
        tags = " ".join(project["filter_tags"])
        status = project["status"]
        rows += f"<tr class='heat-row' data-tags='{esc(tags)}'><td><a href='{esc(project['url'])}'>{esc(project['name'])}</a></td><td>{dots(len(project['open_issues']), 8)} {len(project['open_issues'])}</td><td>{dots(len(project['open_prs']), 3)} {len(project['open_prs'])}</td><td><span class='signal-pill'>{project['activity_score']}</span> {esc(project['activity_reason'])}</td><td><span class='status status-{esc(status)}'>{esc(status)}</span></td></tr>"
    return f"<section class='panel'><h2>Project heat map</h2><p class='muted'>Sorted by automatic signal strength.</p><table class='heat-map'><thead><tr><th>Project</th><th>Issues</th><th>PRs</th><th>Signal</th><th>State</th></tr></thead><tbody>{rows}</tbody></table></section>"


def project_card(project: dict[str, Any]) -> str:
    commit = project.get("latest_commit")
    latest = "No commit found." if not commit else f"{esc(commit['sha'])} — {esc(commit['message'])}"
    issues = "".join(item_link(issue) for issue in project["open_issues"][:MAX_ITEMS]) or "<li>No open issues found.</li>"
    prs = "".join(item_link(pr) for pr in project["open_prs"][:MAX_ITEMS]) or "<li>No open PRs found.</li>"
    tags = " ".join(project["filter_tags"])
    return f"<details class='card compact-card' data-tags='{esc(tags)}'><summary><a href='{esc(project['url'])}'>{esc(project['full_name'])}</a><span class='status status-{esc(project['status'])}'>{esc(project['status'])}</span><div class='project-summary'><span>{len(project['open_issues'])} issues</span><span>{len(project['open_prs'])} PRs</span><span>signal {project['activity_score']}: {esc(project['activity_reason'])}</span><span>{latest}</span></div></summary><div class='project-detail'><p>{esc(project['description'] or 'No repository description.')}</p><p class='muted'>Updated: {esc(clean_date(project['updated_at']))}</p><h3>Open issues</h3><ul>{issues}</ul><h3>Open PRs</h3><ul>{prs}</ul></div></details>"


def project_list(data: dict[str, Any]) -> str:
    cards = "".join(project_card(project) for project in data["projects"])
    return f"<section><h2>Projects <span id='visible-count'>{data['project_count']}</span></h2><p class='muted' id='filter-note'>Showing all projects. Sorted by automatic signal strength.</p><div class='cards'>{cards}</div></section>"


def filter_script() -> str:
    return """<script>(()=>{const b=[...document.querySelectorAll('[data-filter]')],c=[...document.querySelectorAll('.compact-card[data-tags]')],r=[...document.querySelectorAll('.heat-row[data-tags]')],n=document.getElementById('visible-count'),note=document.getElementById('filter-note');function m(e,f){return f==='all'||(e.dataset.tags||'').split(' ').includes(f)}function a(f){let count=0;c.forEach(x=>{let show=m(x,f);x.hidden=!show;if(show)count++});r.forEach(x=>x.hidden=!m(x,f));b.forEach(x=>x.classList.toggle('active',x.dataset.filter===f));if(n)n.textContent=count;if(note)note.textContent=f==='all'?'Showing all projects. Sorted by automatic signal strength.':'Showing '+f+' projects.'}b.forEach(x=>x.onclick=()=>a(x.dataset.filter));a('all')})();</script>"""


def render_html(data: dict[str, Any]) -> str:
    home_items = [(project, issue) for project in data["projects"] for issue in project["open_issues"] if has_label(issue, "home-pc")]
    home = "".join(f"<li><strong>{esc(project['name'])}</strong>: <a href='{esc(issue['url'])}'>#{esc(issue['number'])} — {esc(issue['title'])}</a></li>" for project, issue in home_items) or "<li>No `home-pc` labelled tasks found.</li>"
    errors = "".join(f"<li>{esc(error)}</li>" for error in data["errors"]) or "<li>No scan errors.</li>"
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Project Status Engine</title><style>{css()}</style></head><body><header><h1>Project Status Engine</h1><p>Generated from GitHub data. Do not maintain this by hand.</p></header><main><section class='summary'><div class='panel'><strong>Owner</strong><br>{esc(data['owner'])}</div><div class='panel'><strong>Generated</strong><br>{esc(data['generated_at'])}</div><div class='panel'><strong>Projects scanned</strong><br>{esc(data['project_count'])}</div></section><nav class='control-strip'>{filter_buttons(data)}</nav><section class='panel'><h2>Do Next</h2>{priority_html(data)}</section>{summary_html(data)}{heat_map(data)}<section class='panel'><h2>Home-machine tasks</h2><ul>{home}</ul></section><section class='panel'><h2>Scan notes</h2><ul>{errors}</ul></section>{project_list(data)}</main><footer>Generated automatically. Source of truth: GitHub repositories, issues, PRs, labels, and commits.</footer>{filter_script()}</body></html>"


def render_project_markdown(data: dict[str, Any]) -> str:
    lines = ["# Project Status", "", "Generated automatically from GitHub data. Do not edit this as a manual dashboard.", "", f"Owner: `{data['owner']}`", f"Generated: `{data['generated_at']}`", "", "## Do Next", ""]
    lines.extend(f"- {item['project']} #{item['number']} — {item['title']}: {item['url']}" for item in data.get("priority", []))
    lines.extend(["", "## Projects", ""])
    for project in data["projects"]:
        lines.extend([f"### {project['full_name']}", "", f"Status: `{project['status']}`", f"Signal: `{project['activity_score']}` — {project['activity_reason']}", f"Updated: `{clean_date(project['updated_at'])}`", f"Repo: {project['url']}", ""])
    return "\n".join(lines).strip() + "\n"


def render_home_markdown(data: dict[str, Any]) -> str:
    lines = ["# Home-Machine Tasks", "", "Generated automatically from issues labelled `home-pc`.", ""]
    found = False
    for project in data["projects"]:
        for issue in [item for item in project["open_issues"] if has_label(item, "home-pc")]:
            if not found:
                found = True
            lines.append(f"- {project['full_name']} #{issue['number']} — {issue['title']}: {issue['url']}")
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
    for error in data.get("errors", []):
        print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
