#!/usr/bin/env python3
"""Generate the live, private-safe top-five project status board."""
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
PROJECT_LIMIT = int(os.getenv("STATUS_PROJECT_LIMIT", "5"))
WINDOW_DAYS = int(os.getenv("STATUS_ACTIVITY_WINDOW_DAYS", "30"))
PRIVATE_TOKEN = os.getenv("PROJECT_STATUS_TOKEN", "")
TOKEN = PRIVATE_TOKEN or os.getenv("GITHUB_TOKEN", "")
OUT_DIR = Path(os.getenv("STATUS_OUT_DIR", "public"))
LABELS = {"next", "home-pc", "blocked", "waiting-user", "review", "safe-to-continue", "move-to-new-chat"}
STATUSES = ["blocked", "review", "active", "clear"]
FILTERS = [("all", "All"), ("review", "Review"), ("blocked", "Blocked"), ("home-pc", "Home PC"), ("next", "Next"), ("clear", "Clear")]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        value_dt = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value_dt.replace(tzinfo=value_dt.tzinfo or dt.timezone.utc).astimezone(dt.timezone.utc)


def age_days(value: str | None, now: dt.datetime) -> int | None:
    value_dt = parse_date(value)
    return None if value_dt is None else max(0, int((now - value_dt).total_seconds() // 86400))


def recency(age: int | None, bands: tuple[tuple[int, int], ...]) -> int:
    if age is None:
        return 0
    return next((points for days, points in bands if age <= days), 0)


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
        raise RuntimeError(f"GitHub API error {exc.code}: {body[:300]}") from exc


def safe_get(path: str, query: dict[str, str | int] | None = None) -> tuple[Any | None, str | None]:
    try:
        return api_get(path, query), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def discovery_request() -> tuple[str, dict[str, str | int]]:
    if PRIVATE_TOKEN:
        return "/user/repos", {"visibility": "all", "affiliation": "owner", "sort": "pushed", "direction": "desc", "per_page": MAX_REPOS}
    return f"/users/{OWNER}/repos", {"type": "owner", "sort": "pushed", "direction": "desc", "per_page": MAX_REPOS}


def status_labels(item: dict[str, Any]) -> list[str]:
    return sorted(str(label.get("name")) for label in item.get("labels", []) if label.get("name") in LABELS)


def issue_from(item: dict[str, Any]) -> dict[str, Any]:
    return {"number": item.get("number"), "title": item.get("title") or "Untitled issue", "url": item.get("html_url") or "", "updated_at": item.get("updated_at") or "", "status_labels": status_labels(item)}


def pr_from(item: dict[str, Any]) -> dict[str, Any]:
    return {"number": item.get("number"), "title": item.get("title") or "Untitled PR", "url": item.get("html_url") or "", "updated_at": item.get("updated_at") or "", "draft": bool(item.get("draft")), "status_labels": status_labels(item)}


def commit_from(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return {"sha": (item.get("sha") or "")[:7], "message": ((commit.get("message") or "No commit message").splitlines() or [""])[0], "url": item.get("html_url") or "", "date": author.get("date") or ""}


def has_label(item: dict[str, Any], label: str) -> bool:
    return label in item.get("status_labels", [])


def project_status(issues: list[dict[str, Any]], prs: list[dict[str, Any]]) -> str:
    if any(has_label(issue, "blocked") for issue in issues):
        return "blocked"
    if prs or any(has_label(issue, "review") for issue in issues):
        return "review"
    return "active" if issues else "clear"


def project_tags(project: dict[str, Any]) -> list[str]:
    tags = {"all", project["status"]}
    for item in project["open_issues"] + project["open_prs"]:
        tags.update(label for label in item["status_labels"] if label in {"next", "home-pc", "blocked", "review"})
    if project["open_prs"]:
        tags.add("review")
    return sorted(tags)


def recent_count(items: list[dict[str, Any]], now: dt.datetime) -> int:
    return sum(1 for item in items if (age := age_days(item.get("updated_at"), now)) is not None and age <= WINDOW_DAYS)


def score(project: dict[str, Any], now: dt.datetime | None = None) -> tuple[int, dict[str, int]]:
    """Recent work dominates stale backlog; weights are explicit and deterministic."""
    now = now or now_utc()
    commit_count = min(int(project.get("recent_commit_count", 0)), 20)
    recent_prs = min(recent_count(project["open_prs"], now), 5)
    recent_issues = min(recent_count(project["open_issues"], now), 10)
    components = {
        "recent_commits": commit_count * 30,
        "push_recency": recency(age_days(project.get("pushed_at"), now), ((1, 120), (3, 90), (7, 60), (14, 35), (30, 15))),
        "latest_commit_recency": recency(age_days((project.get("latest_commit") or {}).get("date"), now), ((1, 80), (3, 60), (7, 40), (14, 20), (30, 10))),
        "recent_pr_updates": recent_prs * 20,
        "recent_issue_updates": recent_issues * 8,
        "open_pr_attention": min(len(project["open_prs"]), 3) * 12,
        "stale_backlog": min(len(project["open_issues"]), 8),
        "workflow_labels": 0,
    }
    weights = {"blocked": 18, "review": 15, "next": 12, "home-pc": 8, "waiting-user": 4, "safe-to-continue": 2}
    for item in project["open_issues"] + project["open_prs"]:
        components["workflow_labels"] += sum(points for label, points in weights.items() if has_label(item, label))
    return sum(components.values()), components


def activity_reason(project: dict[str, Any], now: dt.datetime | None = None) -> str:
    now = now or now_utc()
    if int(project.get("recent_commit_count", 0)) > 0:
        return "recent commit activity"
    if (age := age_days(project.get("pushed_at"), now)) is not None and age <= 7:
        return "recent repository activity"
    if recent_count(project["open_prs"], now):
        return "recent pull request activity"
    if recent_count(project["open_issues"], now):
        return "recent issue activity"
    if project["open_prs"]:
        return "open pull request"
    if project["open_issues"]:
        return "open issue backlog"
    return "quiet"


def rank_projects(projects: list[dict[str, Any]], now: dt.datetime | None = None) -> list[dict[str, Any]]:
    now = now or now_utc()
    for project in projects:
        project["activity_score"], project["activity_components"] = score(project, now)
        project["activity_reason"] = activity_reason(project, now)
    return sorted(projects, key=lambda p: (p["activity_score"], p.get("pushed_at", ""), p["full_name"]), reverse=True)


def safe_error(private: bool, name: str, error: str) -> str:
    return "Private project scan failed." if private else f"{name}: {error}"


def public_project(project: dict[str, Any], rank: int) -> dict[str, Any]:
    if not project.get("private"):
        result = dict(project)
        result["rank"] = rank
        return result
    return {
        "rank": rank,
        "name": f"Private project #{rank}",
        "full_name": f"Private project #{rank}",
        "description": "Private repository activity is redacted.",
        "url": "",
        "updated_at": "",
        "pushed_at": "",
        "private": True,
        "open_issues": [],
        "open_prs": [],
        "latest_commit": None,
        "recent_commit_count": 0,
        "status": "active",
        "filter_tags": ["active", "all"],
        "activity_score": project["activity_score"],
        "activity_reason": project["activity_reason"],
        "activity_components": {"aggregate_activity": project["activity_score"]},
    }


def select_projects(ranked: list[dict[str, Any]], limit: int = PROJECT_LIMIT) -> list[dict[str, Any]]:
    return [public_project(project, rank) for rank, project in enumerate(ranked[:max(0, limit)], 1)]


def collect() -> dict[str, Any]:
    now = now_utc()
    path, query = discovery_request()
    repos, repo_error = safe_get(path, query)
    errors = [repo_error] if repo_error else []
    projects: list[dict[str, Any]] = []
    since = (now - dt.timedelta(days=WINDOW_DAYS)).isoformat()

    for repo in repos or []:
        if repo.get("archived") or repo.get("fork") or not repo.get("full_name"):
            continue
        name = repo["full_name"]
        private = bool(repo.get("private"))
        time.sleep(0.05)
        issues_raw, issue_error = safe_get(f"/repos/{name}/issues", {"state": "open", "sort": "updated", "direction": "desc", "per_page": MAX_ITEMS})
        prs_raw, pr_error = safe_get(f"/repos/{name}/pulls", {"state": "open", "sort": "updated", "direction": "desc", "per_page": MAX_ITEMS})
        latest_raw, latest_error = safe_get(f"/repos/{name}/commits", {"per_page": 1})
        recent_raw, recent_error = safe_get(f"/repos/{name}/commits", {"author": OWNER, "since": since, "per_page": 100})
        for error in (issue_error, pr_error, latest_error, recent_error):
            if error:
                errors.append(safe_error(private, name, error))
        issues = [issue_from(item) for item in (issues_raw or []) if not item.get("pull_request")]
        prs = [pr_from(item) for item in (prs_raw or [])]
        latest = [commit_from(item) for item in (latest_raw or [])]
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
            "status": project_status(issues, prs),
        }
        project["filter_tags"] = project_tags(project)
        projects.append(project)

    ranked = rank_projects(projects, now)
    selected = select_projects(ranked)
    data = {
        "owner": OWNER,
        "generated_at": now.isoformat(),
        "activity_window_days": WINDOW_DAYS,
        "scanned_candidate_count": len(ranked),
        "project_count": len(selected),
        "projects": selected,
        "errors": errors,
    }
    data["summary"] = summary_for(selected)
    data["priority"] = priority_for(selected)
    return data


def summary_for(projects: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {status: 0 for status in STATUSES}
    label_counts = {label: 0 for label in LABELS}
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
        if project.get("private"):
            continue
        if project["open_prs"]:
            candidates.append((1, project["open_prs"][0], project, "pr", "Open PR needs review or merge decision."))
        chosen = next((issue for issue in project["open_issues"] if any(has_label(issue, label) for label in ("blocked", "review", "next", "home-pc"))), project["open_issues"][0] if project["open_issues"] else None)
        if chosen:
            candidates.append((0 if project["status"] == "blocked" else 4, chosen, project, "issue", "Open issue."))
    candidates.sort(key=lambda row: (row[0], row[1].get("updated_at", "")))
    return [{"project": project["full_name"], "kind": kind, "title": item["title"], "number": item["number"], "url": item["url"], "reason": reason} for _, item, project, kind, reason in candidates[:limit]]


def css() -> str:
    return "body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f6f8;color:#20262c}header{padding:2rem;background:#20262c;color:#fff}main{max-width:1100px;margin:auto;padding:1.5rem}a{color:#185abc}.panel,.card{background:#fff;border:1px solid #d9dde3;border-radius:14px;padding:1rem;margin-bottom:1rem}.summary,.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1rem}.muted{color:#5e6673;font-size:.9rem}.status,.pill,.filter{border-radius:999px;padding:.2rem .55rem;background:#edf0f4;font-size:.82rem}.control{position:sticky;top:0;background:#f5f6f8ee;padding:.6rem;margin:1rem 0}.filter{border:1px solid #d9dde3;background:#fff;cursor:pointer}.filter.active{background:#20262c;color:#fff}.bar{height:.65rem;border-radius:999px;background:#edf0f4;overflow:hidden}.bar span{display:block;height:100%;background:#20262c}.heat{width:100%;border-collapse:collapse}.heat th,.heat td{text-align:left;border-bottom:1px solid #e3e7ed;padding:.55rem}.cards{display:grid;gap:.75rem}.card{padding:0}.card summary{cursor:pointer;padding:1rem}.detail{border-top:1px solid #e3e7ed;padding:1rem}[hidden]{display:none!important}footer{text-align:center;color:#5e6673;padding:2rem}"


def name_html(project: dict[str, Any]) -> str:
    label = esc(project["full_name"])
    return f"<a href='{esc(project['url'])}'>{label}</a>" if project.get("url") else f"<span>{label}</span>"


def filters_html(data: dict[str, Any]) -> str:
    def count(tag: str) -> int:
        return data["project_count"] if tag == "all" else sum(1 for project in data["projects"] if tag in project["filter_tags"])
    return "".join(f"<button class='filter{' active' if i == 0 else ''}' data-filter='{tag}'>{label} <strong>{count(tag)}</strong></button>" for i, (tag, label) in enumerate(FILTERS))


def priority_html(data: dict[str, Any]) -> str:
    rows = "".join(f"<li><strong>{esc(item['project'])}</strong>: <a href='{esc(item['url'])}'>#{item['number']} — {esc(item['title'])}</a></li>" for item in data["priority"])
    return f"<ul>{rows or '<li>No public priority items found.</li>'}</ul>"


def summary_html(data: dict[str, Any]) -> str:
    summary = data["summary"]
    total = max(1, data["project_count"])
    bars = "".join(f"<p>{status} {summary['status_counts'][status]}</p><div class='bar'><span style='width:{int(summary['status_counts'][status] / total * 100)}%'></span></div>" for status in STATUSES)
    return f"<section class='grid'><div class='panel'><h2>Project shape</h2>{bars}</div><div class='panel'><h2>Attention</h2><p>{summary['total_issues']} public issues · {summary['total_prs']} public PRs</p></div></section>"


def heat_html(data: dict[str, Any]) -> str:
    rows = "".join(f"<tr class='heat-row' data-tags='{' '.join(project['filter_tags'])}'><td>{name_html(project)}</td><td>{project['activity_score']}</td><td>{esc(project['activity_reason'])}</td><td>{project['status']}</td></tr>" for project in data["projects"])
    return f"<section class='panel'><h2>Project heat map</h2><p class='muted'>Top five by recent activity.</p><table class='heat'><thead><tr><th>Project</th><th>Signal</th><th>Reason</th><th>State</th></tr></thead><tbody>{rows}</tbody></table></section>"


def card_html(project: dict[str, Any]) -> str:
    if project.get("private"):
        detail = "<p>Private repository details are redacted.</p>"
    else:
        issues = "".join(f"<li><a href='{esc(item['url'])}'>#{item['number']} — {esc(item['title'])}</a></li>" for item in project["open_issues"]) or "<li>No open issues.</li>"
        prs = "".join(f"<li><a href='{esc(item['url'])}'>#{item['number']} — {esc(item['title'])}</a></li>" for item in project["open_prs"]) or "<li>No open PRs.</li>"
        detail = f"<p>{esc(project['description'] or 'No repository description.')}</p><h3>Open issues</h3><ul>{issues}</ul><h3>Open PRs</h3><ul>{prs}</ul>"
    return f"<details class='card project-card' data-tags='{' '.join(project['filter_tags'])}'><summary>{name_html(project)} <span class='pill'>rank {project['rank']}</span> <span class='pill'>signal {project['activity_score']}</span> <span class='muted'>{esc(project['activity_reason'])}</span></summary><div class='detail'>{detail}</div></details>"


def script() -> str:
    return """<script>(()=>{const b=[...document.querySelectorAll('[data-filter]')],c=[...document.querySelectorAll('.project-card')],r=[...document.querySelectorAll('.heat-row')];function ok(e,f){return f==='all'||(e.dataset.tags||'').split(' ').includes(f)}function apply(f){c.forEach(x=>x.hidden=!ok(x,f));r.forEach(x=>x.hidden=!ok(x,f));b.forEach(x=>x.classList.toggle('active',x.dataset.filter===f))}b.forEach(x=>x.onclick=()=>apply(x.dataset.filter));apply('all')})();</script>"""


def render_html(data: dict[str, Any]) -> str:
    cards = "".join(card_html(project) for project in data["projects"])
    errors = "".join(f"<li>{esc(error)}</li>" for error in data["errors"]) or "<li>No scan errors.</li>"
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Project Status Engine</title><style>{css()}</style></head><body><header><h1>Project Status Engine</h1><p>Live top-five activity view generated from GitHub.</p></header><main><section class='summary'><div class='panel'><strong>Generated</strong><br>{esc(data['generated_at'])}</div><div class='panel'><strong>Projects shown</strong><br>{data['project_count']} of {data['scanned_candidate_count']} candidates</div></section><nav class='control'>{filters_html(data)}</nav><section class='panel'><h2>Do Next</h2>{priority_html(data)}</section>{summary_html(data)}{heat_html(data)}<section><h2>Projects</h2><div class='cards'>{cards}</div></section><section class='panel'><h2>Scan notes</h2><ul>{errors}</ul></section></main><footer>Generated automatically from GitHub activity.</footer>{script()}</body></html>"


def render_project_markdown(data: dict[str, Any]) -> str:
    lines = ["# Project Status", "", f"Generated: `{data['generated_at']}`", f"Showing: `{data['project_count']}` of `{data['scanned_candidate_count']}` candidates", "", "## Projects", ""]
    for project in data["projects"]:
        lines += [f"### {project['full_name']}", "", f"Rank: `{project['rank']}`", f"Signal: `{project['activity_score']}` — {project['activity_reason']}", ""]
    return "\n".join(lines).strip() + "\n"


def render_home_markdown(data: dict[str, Any]) -> str:
    lines = ["# Home-Machine Tasks", "", "Generated from public selected-project issues labelled `home-pc`.", ""]
    found = False
    for project in data["projects"]:
        if project.get("private"):
            continue
        for item in project["open_issues"]:
            if has_label(item, "home-pc"):
                found = True
                lines.append(f"- {project['full_name']} #{item['number']} — {item['title']}: {item['url']}")
    if not found:
        lines.append("No public `home-pc` labelled tasks found.")
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
    print(f"Generated {data['project_count']} projects from {data['scanned_candidate_count']} candidates.")
    for error in data["errors"]:
        print(f"- {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
