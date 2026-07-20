import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location("dual_status", SCRIPTS / "dual_status.py")
dual = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(dual)
core = dual.core

NOW = dt.datetime(2026, 7, 7, 12, 0, tzinfo=dt.timezone.utc)


def issue(number: int, title: str, *, label: str | None = None, updated: str = "2026-07-07T10:00:00Z"):
    labels = [] if label is None else [label]
    return {
        "number": number,
        "title": title,
        "url": f"https://example.test/issues/{number}",
        "updated_at": updated,
        "status_labels": labels,
    }


def exception(code: str, detail: str, sha: str):
    return {
        "code": code,
        "project_type": "software",
        "detail": detail,
        "source_sha": sha,
        "source_branch": "automation/project-status-bootstrap-exception",
        "source_path": ".project/bootstrap-exception.json",
        "accepted_evidence": "Explicit completed and total counts are required.",
    }


def project(name: str, score: int, *, private: bool = False, issues=None, prs=None):
    issues = list(issues or [])
    prs = list(prs or [])
    value = {
        "name": name,
        "full_name": f"owner/{name}",
        "description": f"{name} secret description" if private else f"{name} description",
        "url": f"https://example.test/{name}",
        "updated_at": "2026-07-07T10:00:00Z",
        "pushed_at": "2026-07-07T10:00:00Z",
        "private": private,
        "open_issues": issues,
        "open_prs": prs,
        "latest_commit": {
            "sha": "abc1234",
            "message": f"{name} secret commit" if private else f"{name} commit",
            "url": f"https://example.test/{name}/commit/abc1234",
            "date": "2026-07-07T10:00:00Z",
        },
        "recent_commit_count": score,
        "status": core.project_status(issues, prs),
        "activity_score": score * 100,
        "activity_reason": "recent commit activity",
        "activity_components": {"recent_commits": score * 100},
        "authority_exception": None,
    }
    value["filter_tags"] = core.project_tags(value)
    return value


class DualViewTests(unittest.TestCase):
    def setUp(self):
        self.ranked = [
            project("private-alpha", 9, private=True, issues=[issue(1, "Private alpha next", label="next")]),
            project("private-beta", 8, private=True, prs=[issue(2, "Private beta PR")]),
            project("public-gamma", 7, issues=[issue(3, "Public gamma issue")]),
            project("public-delta", 6),
            project("private-epsilon", 5, private=True),
            project("public-zeta", 4),
            project("public-eta", 3),
        ]
        self.ranked[0]["authority_exception"] = exception(
            "no_completion_evidence", "Private alpha authority detail.", "a" * 40
        )
        self.ranked[5]["authority_exception"] = exception(
            "ambiguous_project_type", "Public zeta owner-only detail.", "b" * 40
        )

    def test_public_view_contains_full_pool_and_redacts_private_details(self):
        data = dual.build_public_data(copy.deepcopy(self.ranked), [], NOW)
        self.assertEqual(data["project_count"], 7)
        self.assertEqual(data["scanned_candidate_count"], 7)
        self.assertEqual(len(data["projects"]), 7)
        outputs = "\n".join(
            [
                json.dumps(data),
                dual.render_public_html(data),
                core.render_project_markdown(data),
                core.render_home_markdown(data),
            ]
        )
        for forbidden in [
            "private-alpha",
            "private-beta",
            "private-epsilon",
            "Private alpha next",
            "Private beta PR",
            "secret commit",
            "secret description",
            "authority_exception",
            "Private alpha authority detail",
            "Public zeta owner-only detail",
            "no_completion_evidence",
            "ambiguous_project_type",
        ]:
            self.assertNotIn(forbidden, outputs)
        self.assertIn("Private project #1", outputs)
        self.assertIn("Private project #2", outputs)
        self.assertIn("Private project #5", outputs)
        self.assertIn("All discovered repositories by recent activity.", outputs)

    def test_private_view_contains_exact_real_top_five_and_full_exception_queue(self):
        data = dual.build_private_data(copy.deepcopy(self.ranked), [], NOW, limit=5)
        self.assertEqual(data["project_count"], 5)
        self.assertEqual([item["full_name"] for item in data["projects"]], [
            "owner/private-alpha",
            "owner/private-beta",
            "owner/public-gamma",
            "owner/public-delta",
            "owner/private-epsilon",
        ])
        self.assertEqual(
            [item["full_name"] for item in data["authority_exception_queue"]],
            ["owner/public-zeta", "owner/private-alpha"],
        )
        self.assertEqual(data["authority_exception_summary"]["total"], 2)
        private_html = dual.render_private_html(data)
        self.assertIn("owner/private-alpha", private_html)
        self.assertIn("Private alpha next", private_html)
        self.assertIn("owner/public-zeta", private_html)
        self.assertIn("Public zeta owner-only detail", private_html)
        self.assertNotIn("Private repository details are redacted", private_html)

    def test_private_do_next_uses_only_top_five_and_can_include_private_projects(self):
        outside = project("outside-top-five", 1, issues=[issue(99, "Outside action", label="blocked")])
        ranked = copy.deepcopy(self.ranked[:5] + [outside])
        data = dual.build_private_data(ranked, [], NOW, limit=5)
        priority_text = json.dumps(data["priority"])
        self.assertIn("owner/private-alpha", priority_text)
        self.assertIn("Private alpha next", priority_text)
        self.assertIn("owner/private-beta", priority_text)
        self.assertNotIn("outside-top-five", priority_text)
        self.assertNotIn("Outside action", priority_text)

    def test_public_and_private_views_share_same_ranking_result(self):
        public_data, private_data = dual.build_views(copy.deepcopy(self.ranked), [], NOW)
        self.assertEqual(public_data["projects"][0]["activity_score"], private_data["projects"][0]["activity_score"])
        self.assertEqual(public_data["projects"][4]["activity_score"], private_data["projects"][4]["activity_score"])
        self.assertEqual(public_data["scanned_candidate_count"], private_data["scanned_candidate_count"])

    def test_workflow_never_uploads_private_build_to_pages(self):
        workflow = (ROOT / ".github" / "workflows" / "status.yml").read_text(encoding="utf-8")
        self.assertIn('STATUS_MAX_REPOS: "100"', workflow)
        self.assertIn("PRIVATE_STATUS_OUT_DIR: private-build", workflow)
        self.assertIn("path: public", workflow)
        self.assertNotIn("path: private-build", workflow)
        self.assertNotIn("path: private", workflow)


if __name__ == "__main__":
    unittest.main()
