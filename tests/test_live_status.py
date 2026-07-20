import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_status.py"
SPEC = importlib.util.spec_from_file_location("live_status", MODULE_PATH)
engine = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(engine)

NOW = dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.timezone.utc)


def project(
    name: str,
    *,
    commits: int = 0,
    pushed_at: str = "2026-01-01T00:00:00Z",
    issues=None,
    prs=None,
    private: bool = False,
):
    issues = list(issues or [])
    prs = list(prs or [])
    latest = (
        {
            "sha": "abc1234",
            "message": f"{name} secret commit" if private else f"{name} commit",
            "url": f"https://example.test/{name}/commit",
            "date": pushed_at,
        }
        if commits
        else None
    )
    value = {
        "name": name,
        "full_name": f"owner/{name}",
        "description": f"{name} description",
        "url": f"https://example.test/{name}",
        "updated_at": pushed_at,
        "pushed_at": pushed_at,
        "private": private,
        "open_issues": issues,
        "open_prs": prs,
        "latest_commit": latest,
        "recent_commit_count": commits,
        "status": engine.project_status(issues, prs),
    }
    value["filter_tags"] = engine.project_tags(value)
    return value


def make_data(projects, scanned):
    data = {
        "schema_version": engine.OUTPUT_SCHEMA_VERSION,
        "activity_score_version": engine.ACTIVITY_SCORE_VERSION,
        "view": "public",
        "owner": "owner",
        "generated_at": NOW.isoformat(),
        "scan_state": "complete",
        "scan_health": engine.scan_health_snapshot([]),
        "source_repository_count": scanned,
        "activity_window_days": 30,
        "scanned_candidate_count": scanned,
        "project_count": len(projects),
        "projects": projects,
        "errors": [],
    }
    data["summary"] = engine.summary_for(projects)
    data["priority"] = engine.priority_for(projects)
    return data


class ActivityTests(unittest.TestCase):
    def test_recent_commits_outrank_stale_backlog(self):
        stale_issues = [
            {
                "number": i,
                "title": f"Old {i}",
                "url": "",
                "updated_at": "2025-01-01T00:00:00Z",
                "status_labels": [],
            }
            for i in range(1, 9)
        ]
        stale = project("stale", issues=stale_issues)
        recent = project("recent", commits=3, pushed_at="2026-07-07T09:00:00Z")
        ranked = engine.rank_projects([stale, recent], NOW)
        self.assertEqual(ranked[0]["name"], "recent")
        self.assertGreater(
            ranked[0]["activity_components"]["recent_commits"],
            ranked[1]["activity_components"]["stale_backlog"],
        )

    def test_activity_score_contract_is_loaded_and_versioned(self):
        self.assertEqual(engine.ACTIVITY_SCORE_VERSION, "1.0")
        self.assertEqual(engine.SCORE_CONFIG["points"]["recent_commit"], 30)
        self.assertEqual(engine.SCORE_CONFIG["caps"]["recent_commits"], 20)
        self.assertEqual(engine.WINDOW_DAYS, 30)

    def test_empty_activity_sets_are_supported(self):
        quiet = project("quiet")
        score, components = engine.score(quiet, NOW)
        self.assertIsInstance(score, int)
        self.assertEqual(sum(components.values()), score)
        engine.rank_projects([quiet], NOW)


class SelectionAndPrivacyTests(unittest.TestCase):
    def test_only_five_projects_are_published(self):
        projects = [
            project(
                f"p{i}",
                commits=10 - i,
                pushed_at=f"2026-07-0{max(1, 7-i)}T12:00:00Z",
            )
            for i in range(7)
        ]
        ranked = engine.rank_projects(projects, NOW)
        selected = engine.select_projects(ranked, 5)
        data = make_data(selected, scanned=7)
        self.assertEqual(data["project_count"], 5)
        self.assertEqual(len(data["projects"]), 5)
        self.assertIn("Projects shown</strong><br>5 of 7", engine.render_html(data))
        markdown = engine.render_project_markdown(data)
        self.assertEqual(markdown.count("\n### "), 5)
        self.assertEqual(len(json.loads(json.dumps(data))["projects"]), 5)

    def test_private_details_do_not_leak_any_output(self):
        secret_issue = {
            "number": 99,
            "title": "Secret launch title",
            "url": "https://example.test/secret/issues/99",
            "updated_at": "2026-07-07T10:00:00Z",
            "status_labels": ["next"],
        }
        raw = project(
            "secret-repo-name",
            commits=4,
            pushed_at="2026-07-07T10:00:00Z",
            issues=[secret_issue],
            private=True,
        )
        ranked = engine.rank_projects([raw], NOW)
        selected = engine.select_projects(ranked, 5)
        data = make_data(selected, scanned=1)
        outputs = "\n".join(
            [
                json.dumps(data),
                engine.render_html(data),
                engine.render_project_markdown(data),
                engine.render_home_markdown(data),
            ]
        )
        for forbidden in [
            "secret-repo-name",
            "Secret launch title",
            "secret/issues/99",
            "secret commit",
        ]:
            self.assertNotIn(forbidden, outputs)
        self.assertIn("Private project #1", outputs)
        self.assertEqual(data["priority"], [])

    def test_private_error_redaction(self):
        error = engine.safe_error(
            True,
            "owner/secret-repository",
            "403 https://api.github.com/repos/owner/secret-repository/issues",
        )
        self.assertEqual(error, "Private project scan failed.")
        self.assertNotIn("secret-repository", error)

    def test_rendering_includes_accessibility_controls(self):
        ranked = engine.rank_projects([project("one", commits=1)], NOW)
        data = make_data(engine.select_projects(ranked), scanned=1)
        html = engine.render_html(data)
        self.assertIn("Skip to content", html)
        self.assertIn("aria-pressed='true'", html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("table-wrap", html)


class DiscoveryTests(unittest.TestCase):
    def test_public_fallback_without_project_status_token(self):
        original = engine.PRIVATE_TOKEN
        try:
            engine.PRIVATE_TOKEN = ""
            path, query = engine.discovery_request()
        finally:
            engine.PRIVATE_TOKEN = original
        self.assertEqual(path, f"/users/{engine.OWNER}/repos")
        self.assertEqual(query["type"], "owner")

    def test_authenticated_discovery_includes_all_visibility(self):
        original = engine.PRIVATE_TOKEN
        try:
            engine.PRIVATE_TOKEN = "configured"
            path, query = engine.discovery_request()
        finally:
            engine.PRIVATE_TOKEN = original
        self.assertEqual(path, "/user/repos")
        self.assertEqual(query["visibility"], "all")
        self.assertEqual(query["affiliation"], "owner")

    def test_repository_discovery_uses_bounded_pagination(self):
        original_safe_get = engine.safe_get
        original_max = engine.MAX_REPOS
        calls = []

        def fake_get(path, query):
            calls.append(dict(query))
            page = query["page"]
            count = query["per_page"]
            if page == 1:
                return [
                    {"full_name": f"owner/repo-{index}"}
                    for index in range(count)
                ], None
            return [
                {"full_name": f"owner/repo-{100 + index}"}
                for index in range(count)
            ], None

        try:
            engine.safe_get = fake_get
            engine.MAX_REPOS = 120
            repositories, error = engine.discover_repositories()
        finally:
            engine.safe_get = original_safe_get
            engine.MAX_REPOS = original_max

        self.assertIsNone(error)
        self.assertEqual(len(repositories), 120)
        self.assertEqual([call["page"] for call in calls], [1, 2])
        self.assertEqual([call["per_page"] for call in calls], [100, 20])


if __name__ == "__main__":
    unittest.main()
