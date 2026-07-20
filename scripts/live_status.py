#!/usr/bin/env python3
"""Shared GitHub scanning, activity ranking and dashboard rendering primitives."""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
ROOT = Path(__file__).resolve().parents[1]
SCORE_CONFIG_PATH = ROOT / "config" / "activity-score.json"
OUTPUT_SCHEMA_VERSION = 1
OWNER = os.getenv("STATUS_OWNER", "armpitpete")
MAX_REPOS = int(os.getenv("STATUS_MAX_REPOS", "30"))
MAX_ITEMS = int(os.getenv("STATUS_MAX_ITEMS", "8"))
PROJECT_LIMIT = int(os.getenv("STATUS_PROJECT_LIMIT", "5"))
PRIVATE_TOKEN = os.getenv("PROJECT_STATUS_TOKEN", "")
TOKEN = PRIVATE_TOKEN or os.getenv("GITHUB_TOKEN", "")
MAX_RETRIES = max(0, int(os.getenv("STATUS_API_RETRIES", "2")))
LABELS = {
    "next",
    "home-pc",
    "blocked",
    "waiting-user",
    "review",
    "safe-to-continue",
    "move-to-new-chat",
}
STATUSES = ["blocked", "review", "active", "clear"]
FILTERS = [
    ("all", "All"),
    ("review", "Review"),
    ("blocked", "Blocked"),
    ("home-pc", "Home PC"),
    ("next", "Next"),
    ("clear", "Clear"),
]


def _load_score_config() -> dict[str, Any]:
    document = json.loads(SCORE_CONFIG_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise RuntimeError("unsupported activity-score schema")
    if not isinstance(document.get("activity_score_version"), str):
        raise RuntimeError("missing activity-score version")
    return document


SCORE_CONFIG = _load_score_config()
ACTIVITY_SCORE_VERSION = SCORE_CONFIG["activity_score_version"]
WINDOW_DAYS = int(
    os.getenv(
        "STATUS_ACTIVITY_WINDOW_DAYS",
        str(SCORE_CONFIG["activity_window_days"]),
    )
)

_SCAN_HEALTH: dict[str, Any] = {}


def reset_scan_health() -> None:
    _SCAN_HEALTH.clear()
    _SCAN_HEALTH.update(
        {
            "request_count": 0,
            "failure_count": 0,
            "rate_limit_remaining": None,
            "rate_limit_limit": None,
            "rate_limit_reset_at": None,
        }
    )


reset_scan_health()


def scan_health_snapshot(errors: list[str] | None = None) -> dict[str, Any]:
    result = dict(_SCAN_HEALTH)
    if errors is not None:
        result["failure_count"] = max(result["failure_count"], len(errors))
    return result


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        value_dt = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value_dt.replace(tzinfo=value_dt.tzinfo or dt.timezone.utc).astimezone(
        dt.timezone.utc
    )


def age_days(value: str | None, now: dt.datetime) -> int | None:
    value_dt = parse_date(value)
    return (
        None
        if value_dt is None
        else max(0, int((now - value_dt).total_seconds() // 86400))
    )


def recency(age: int | None, bands: tuple[tuple[int, int], ...]) -> int:
    if age is None:
        return 0
    return next((points for days, points in bands if age <= days), 0)


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _rate_limit_value(headers: Any, name: str) -> int | None:
    value = headers.get(name) if headers is not None else None
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _update_rate_limit(headers: Any) -> None:
    remaining = _rate_limit_value(headers, "X-RateLimit-Remaining")
    limit = _rate_limit_value(headers, "X-RateLimit-Limit")
    reset = _rate_limit_value(headers, "X-RateLimit-Reset")
    if remaining is not None:
        _SCAN_HEALTH["rate_limit_remaining"] = remaining
    if limit is not None:
        _SCAN_HEALTH["rate_limit_limit"] = limit
    if reset is not None:
        _SCAN_HEALTH["rate_limit_reset_at"] = dt.datetime.fromtimestamp(
            reset, tz=dt.timezone.utc
        ).isoformat()


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

    for attempt in range(MAX_RETRIES + 1):
        _SCAN_HEALTH["request_count"] += 1
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                _update_rate_limit(response.headers)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            _update_rate_limit(exc.headers)
            body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code in {429, 500, 502, 503, 504}
            if retryable and attempt < MAX_RETRIES:
                time.sleep(0.25 * (2**attempt))
                continue
            raise RuntimeError(f"GitHub API error {exc.code}: {body[:300]}") from exc
        except urllib.error.URLError as exc:
            if attempt < MAX_RETRIES:
                time.sleep(0.25 * (2**attempt))
                continue
            raise RuntimeError("GitHub API network error") from exc
    raise RuntimeError("GitHub API retry boundary exhausted")


def safe_get(
    path: str, query: dict[str, str | int] | None = None
) -> tuple[Any | None, str | None]:
    try:
        return api_get(path, query), None
    except Exception as exc:  # noqa: BLE001
        _SCAN_HEALTH["failure_count"] += 1
        return None, str(exc)


def discovery_request() -> tuple[str, dict[str, str | int]]:
    if PRIVATE_TOKEN:
        return "/user/repos", {
            "visibility": "all",
            "affiliation": "owner",
            "sort": "pushed",
            "direction": "desc",
        }
    return f"/users/{OWNER}/repos", {
        "type": "owner",
        "sort": "pushed",
        "direction": "desc",
    }


def discover_repositories() -> tuple[list[dict[str, Any]], str | None]:
    """Discover up to MAX_REPOS repositories using bounded GitHub pagination."""
    if MAX_REPOS <= 0:
        return [], None
    path, base_query = discovery_request()
    repositories: list[dict[str, Any]] = []
    page = 1
    while len(repositories) < MAX_REPOS:
        per_page = min(100, MAX_REPOS - len(repositories))
        query = {**base_query, "per_page": per_page, "page": page}
        payload, error = safe_get(path, query)
        if error:
            return repositories, error
        if not isinstance(payload, list):
            _SCAN_HEALTH["failure_count"] += 1
            return repositories, "GitHub repository discovery returned a non-list payload."
        repositories.extend(payload)
        if len(payload) < per_page:
            break
        page += 1
    return repositories[:MAX_REPOS], None


def status_labels(item: dict[str, Any]) -> list[str]:
    return sorted(
        str(label.get("name"))
        for label in item.get("labels", [])
        if label.get("name") in LABELS
    )


def issue_from(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled issue",
        "url": item.get("html_url") or "",
        "updated_at": item.get("updated_at") or "",
        "status_labels": status_labels(item),
    }


def pr_from(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": item.get("title") or "Untitled PR",
        "url": item.get("html_url") or "",
        "updated_at": item.get("updated_at") or "",
        "draft": bool(item.get("draft")),
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


def has_label(item: dict[str, Any], label: str) -> bool:
    return label in item.get("status_labels", [])


def project_status(
    issues: list[dict[str, Any]], prs: list[dict[str, Any]]
) -> str:
    if any(has_label(issue, "blocked") for issue in issues):
        return "blocked"
    if prs or any(has_label(issue, "review") for issue in issues):
        return "review"
    return "active" if issues else "clear"


def project_tags(project: dict[str, Any]) -> list[str]:
    tags = {"all", project["status"]}
    for item in project["open_issues"] + project["open_prs"]:
        tags.update(
            label
            for label in item["status_labels"]
            if label in {"next", "home-pc", "blocked", "review"}
        )
    if project["open_prs"]:
        tags.add("review")
    return sorted(tags)


def recent_count(items: list[dict[str, Any]], now: dt.datetime) -> int:
    return sum(
        1
        for item in items
        if (age := age_days(item.get("updated_at"), now)) is not None
        and age <= WINDOW_DAYS
    )


def _bands(name: str) -> tuple[tuple[int, int], ...]:
    return tuple((int(days), int(points)) for days, points in SCORE_CONFIG["recency"][name])


def score(
    project: dict[str, Any], now: dt.datetime | None = None
) -> tuple[int, dict[str, int]]:
    """Recent work dominates stale backlog; weights are versioned and explicit."""
    now = now or now_utc()
    caps = SCORE_CONFIG["caps"]
    points = SCORE_CONFIG["points"]
    commit_count = min(int(project.get("recent_commit_count", 0)), int(caps["recent_commits"]))
    recent_prs = min(recent_count(project["open_prs"], now), int(caps["recent_prs"]))
    recent_issues = min(recent_count(project["open_issues"], now), int(caps["recent_issues"]))
    components = {
        "recent_commits": commit_count * int(points["recent_commit"]),
        "push_recency": recency(age_days(project.get("pushed_at"), now), _bands("push")),
        "latest_commit_recency": recency(
            age_days((project.get("latest_commit") or {}).get("date"), now),
            _bands("latest_commit"),
        ),
        "recent_pr_updates": recent_prs * int(points["recent_pr_update"]),
        "recent_issue_updates": recent_issues * int(points["recent_issue_update"]),
        "open_pr_attention": min(len(project["open_prs"]), int(caps["open_prs"]))
        * int(points["open_pr_attention"]),
        "stale_backlog": min(len(project["open_issues"]), int(caps["stale_backlog"])),
        "workflow_labels": 0,
    }
    weights = points["workflow_labels"]
    for item in project["open_issues"] + project["open_prs"]:
        components["workflow_labels"] += sum(
            int(label_points)
            for label, label_points in weights.items()
            if has_label(item, label)
        )
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


def rank_projects(
    projects: list[dict[str, Any]], now: dt.datetime | None = None
) -> list[dict[str, Any]]:
    now = now or now_utc()
    for project in projects:
        project["activity_score"], project["activity_components"] = score(project, now)
        project["activity_reason"] = activity_reason(project, now)
    return sorted(
        projects,
        key=lambda project: (
            project["activity_score"],
            project.get("pushed_at", ""),
            project["full_name"],
        ),
        reverse=True,
    )


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


def select_projects(
    ranked: list[dict[str, Any]], limit: int = PROJECT_LIMIT
) -> list[dict[str, Any]]:
    return [
        public_project(project, rank)
        for rank, project in enumerate(ranked[: max(0, limit)], 1)
    ]


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
    return {
        "status_counts": status_counts,
        "label_counts": label_counts,
        "total_issues": issues,
        "total_prs": prs,
        "attention_count": status_counts["blocked"] + status_counts["review"],
    }


def priority_for(
    projects: list[dict[str, Any]], limit: int = 5
) -> list[dict[str, Any]]:
    candidates = []
    for project in projects:
        if project.get("private"):
            continue
        if project["open_prs"]:
            candidates.append(
                (
                    1,
                    project["open_prs"][0],
                    project,
                    "pr",
                    "Open PR needs review or merge decision.",
                )
            )
        chosen = next(
            (
                issue
                for issue in project["open_issues"]
                if any(
                    has_label(issue, label)
                    for label in ("blocked", "review", "next", "home-pc")
                )
            ),
            project["open_issues"][0] if project["open_issues"] else None,
        )
        if chosen:
            candidates.append(
                (
                    0 if project["status"] == "blocked" else 4,
                    chosen,
                    project,
                    "issue",
                    "Open issue.",
                )
            )
    candidates.sort(key=lambda row: (row[0], row[1].get("updated_at", "")))
    return [
        {
            "project": project["full_name"],
            "kind": kind,
            "title": item["title"],
            "number": item["number"],
            "url": item["url"],
            "reason": reason,
        }
        for _, item, project, kind, reason in candidates[:limit]
    ]


def css() -> str:
    return """
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#20262c;background:#f5f6f8;line-height:1.5}
*{box-sizing:border-box}body{margin:0}a{color:#185abc;text-underline-offset:.15em}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #6b46c1;outline-offset:3px}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;background:#fff;padding:.75rem;z-index:10}header{padding:1.5rem 2rem;background:#20262c;color:#fff}header h1{margin:.1rem 0}.site-nav{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}.site-nav a{color:#fff;border:1px solid #ffffff66;border-radius:.5rem;padding:.35rem .6rem;text-decoration:none}.site-nav a[aria-current='page']{background:#fff;color:#20262c}main{max-width:1100px;margin:auto;padding:1.25rem}.panel,.card{background:#fff;border:1px solid #d9dde3;border-radius:.75rem;padding:1rem;margin-bottom:1rem}.summary,.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem}.muted{color:#5e6673;font-size:.92rem}.status,.pill,.filter{border-radius:999px;padding:.2rem .55rem;background:#edf0f4;font-size:.82rem}.control{position:sticky;top:0;background:#f5f6f8ee;padding:.6rem 0;margin:1rem 0;z-index:2}.filter{border:1px solid #c8ced7;background:#fff;cursor:pointer;margin:.2rem}.filter.active{background:#20262c;color:#fff}.bar{height:.65rem;border-radius:999px;background:#edf0f4;overflow:hidden}.bar span{display:block;height:100%;background:#20262c}.table-wrap{overflow-x:auto}.heat{width:100%;border-collapse:collapse;min-width:600px}.heat th,.heat td{text-align:left;border-bottom:1px solid #e3e7ed;padding:.55rem}.cards{display:grid;gap:.75rem}.card{padding:0}.card summary{cursor:pointer;padding:1rem}.detail{border-top:1px solid #e3e7ed;padding:1rem}.compact-list{display:grid;gap:.65rem}.compact-item{display:flex;justify-content:space-between;gap:1rem;padding:.7rem;border-bottom:1px solid #e3e7ed}.health-ok{font-weight:700}.health-partial{font-weight:700;color:#8a3b12}[hidden]{display:none!important}footer{text-align:center;color:#5e6673;padding:2rem}@media(max-width:640px){header{padding:1.1rem}main{padding:.8rem}.compact-item{display:block}.control{position:static}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
""".strip()


def name_html(project: dict[str, Any]) -> str:
    label = esc(project["full_name"])
    return (
        f"<a href='{esc(project['url'])}'>{label}</a>"
        if project.get("url")
        else f"<span>{label}</span>"
    )


def filters_html(data: dict[str, Any]) -> str:
    def count(tag: str) -> int:
        return (
            data["project_count"]
            if tag == "all"
            else sum(1 for project in data["projects"] if tag in project["filter_tags"])
        )

    return "".join(
        f"<button type='button' class='filter{' active' if index == 0 else ''}' "
        f"data-filter='{tag}' aria-pressed='{'true' if index == 0 else 'false'}'>"
        f"{label} <strong>{count(tag)}</strong></button>"
        for index, (tag, label) in enumerate(FILTERS)
    )


def priority_html(data: dict[str, Any]) -> str:
    rows = "".join(
        f"<li><strong>{esc(item['project'])}</strong>: "
        f"<a href='{esc(item['url'])}'>#{item['number']} — {esc(item['title'])}</a></li>"
        for item in data["priority"]
    )
    return f"<ul>{rows or '<li>No priority items found.</li>'}</ul>"


def summary_html(data: dict[str, Any]) -> str:
    summary = data["summary"]
    total = max(1, data["project_count"])
    bars = "".join(
        f"<p>{status} {summary['status_counts'][status]}</p>"
        f"<div class='bar' aria-label='{status}: {summary['status_counts'][status]} of {total}'>"
        f"<span style='width:{int(summary['status_counts'][status] / total * 100)}%'></span></div>"
        for status in STATUSES
    )
    return (
        "<section class='grid'><div class='panel'><h2>Project shape</h2>"
        f"{bars}</div><div class='panel'><h2>Attention</h2>"
        f"<p>{summary['total_issues']} issues · {summary['total_prs']} PRs</p></div></section>"
    )


def health_html(data: dict[str, Any]) -> str:
    health = data.get("scan_health") or {}
    state = data.get("scan_state", "partial")
    css_class = "health-ok" if state == "complete" else "health-partial"
    remaining = health.get("rate_limit_remaining")
    limit = health.get("rate_limit_limit")
    rate = "unknown" if remaining is None else f"{remaining} of {limit or '?'} remaining"
    return (
        "<section class='panel'><h2>Data health</h2>"
        f"<p class='{css_class}'>Scan: {esc(state)}</p>"
        f"<p>Generated: <time datetime='{esc(data['generated_at'])}'>{esc(data['generated_at'])}</time></p>"
        f"<p>Repositories: {data.get('source_repository_count', data.get('scanned_candidate_count', 0))}; "
        f"requests: {health.get('request_count', 0)}; failures: {health.get('failure_count', 0)}; "
        f"API rate limit: {esc(rate)}.</p></section>"
    )


def heat_html(data: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr class='heat-row' data-tags='{' '.join(project['filter_tags'])}'>"
        f"<td>{name_html(project)}</td><td>{project['activity_score']}</td>"
        f"<td>{esc(project['activity_reason'])}</td><td>{project['status']}</td></tr>"
        for project in data["projects"]
    )
    return (
        "<section class='panel'><h2>Project heat map</h2>"
        "<p class='muted'>Repositories ordered by recent activity.</p>"
        "<div class='table-wrap'><table class='heat'><thead><tr><th>Project</th>"
        "<th>Signal</th><th>Reason</th><th>State</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def card_html(project: dict[str, Any]) -> str:
    if project.get("private"):
        detail = "<p>Private repository details are redacted.</p>"
    else:
        issues = "".join(
            f"<li><a href='{esc(item['url'])}'>#{item['number']} — {esc(item['title'])}</a></li>"
            for item in project["open_issues"]
        ) or "<li>No open issues.</li>"
        prs = "".join(
            f"<li><a href='{esc(item['url'])}'>#{item['number']} — {esc(item['title'])}</a></li>"
            for item in project["open_prs"]
        ) or "<li>No open PRs.</li>"
        detail = (
            f"<p>{esc(project['description'] or 'No repository description.')}</p>"
            f"<h3>Open issues</h3><ul>{issues}</ul><h3>Open PRs</h3><ul>{prs}</ul>"
        )
    return (
        f"<details class='card project-card' data-tags='{' '.join(project['filter_tags'])}'>"
        f"<summary>{name_html(project)} <span class='pill'>rank {project['rank']}</span> "
        f"<span class='pill'>signal {project['activity_score']}</span> "
        f"<span class='muted'>{esc(project['activity_reason'])}</span></summary>"
        f"<div class='detail'>{detail}</div></details>"
    )


def script() -> str:
    return """<script>(()=>{const b=[...document.querySelectorAll('[data-filter]')],c=[...document.querySelectorAll('.project-card')],r=[...document.querySelectorAll('.heat-row')];function ok(e,f){return f==='all'||(e.dataset.tags||'').split(' ').includes(f)}function apply(f){c.forEach(x=>x.hidden=!ok(x,f));r.forEach(x=>x.hidden=!ok(x,f));b.forEach(x=>{const a=x.dataset.filter===f;x.classList.toggle('active',a);x.setAttribute('aria-pressed',String(a))})}b.forEach(x=>x.onclick=()=>apply(x.dataset.filter));apply('all')})();</script>"""


def render_html(data: dict[str, Any]) -> str:
    cards = "".join(card_html(project) for project in data["projects"])
    errors = "".join(f"<li>{esc(error)}</li>" for error in data["errors"]) or "<li>No scan errors.</li>"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Project Status Engine</title><style>{css()}</style></head><body>"
        "<a class='skip' href='#content'>Skip to content</a>"
        "<header><h1>Project Status Engine</h1><p>Repository activity and authority-backed completion.</p></header>"
        "<main id='content'><section class='summary'>"
        f"<div class='panel'><strong>Generated</strong><br>{esc(data['generated_at'])}</div>"
        f"<div class='panel'><strong>Projects shown</strong><br>{data['project_count']} of {data['scanned_candidate_count']} candidates</div>"
        "</section>"
        f"{health_html(data)}<nav class='control' aria-label='Project filters'>{filters_html(data)}</nav>"
        f"<section class='panel'><h2>Do Next</h2>{priority_html(data)}</section>"
        f"{summary_html(data)}{heat_html(data)}"
        f"<section><h2>Projects</h2><div class='cards'>{cards}</div></section>"
        f"<section class='panel'><h2>Scan notes</h2><ul>{errors}</ul></section></main>"
        f"<footer>Generated automatically from GitHub activity using score contract {esc(ACTIVITY_SCORE_VERSION)}.</footer>"
        f"{script()}</body></html>"
    )


def render_project_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Project Status",
        "",
        f"Generated: `{data['generated_at']}`",
        f"Scan state: `{data.get('scan_state', 'unknown')}`",
        f"Showing: `{data['project_count']}` of `{data['scanned_candidate_count']}` candidates",
        "",
        "## Projects",
        "",
    ]
    for project in data["projects"]:
        lines += [
            f"### {project['full_name']}",
            "",
            f"Rank: `{project['rank']}`",
            f"Signal: `{project['activity_score']}` — {project['activity_reason']}",
            "",
        ]
    return "\n".join(lines).strip() + "\n"


def render_home_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Home-Machine Tasks",
        "",
        "Generated from public project issues labelled `home-pc`.",
        "",
    ]
    found = False
    for project in data["projects"]:
        if project.get("private"):
            continue
        for item in project["open_issues"]:
            if has_label(item, "home-pc"):
                found = True
                lines.append(
                    f"- {project['full_name']} #{item['number']} — {item['title']}: {item['url']}"
                )
    if not found:
        lines.append("No public `home-pc` labelled tasks found.")
    return "\n".join(lines).strip() + "\n"
