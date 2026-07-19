import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import completion_status as completion  # noqa: E402
import dual_status as dual  # noqa: E402

NOW = dt.datetime(2026, 7, 19, 12, 0, tzinfo=dt.timezone.utc)


def progress(authority: str):
    return completion.validate_progress(
        {
            "schema_version": 1,
            "authority": authority,
            "stages": [
                {"id": "work", "label": "Work", "completed": 1, "total": 2, "weight": 100}
            ],
            "overall": {"enabled": True},
        }
    )


def project(name: str, *, private: bool, authority: str):
    value = {
        "name": name,
        "full_name": f"owner/{name}",
        "description": "description",
        "url": f"https://example.test/{name}",
        "updated_at": "2026-07-19T10:00:00Z",
        "pushed_at": "2026-07-19T10:00:00Z",
        "private": private,
        "open_issues": [],
        "open_prs": [],
        "latest_commit": None,
        "recent_commit_count": 1,
        "status": "clear",
        "filter_tags": ["all", "clear"],
        "activity_score": 100,
        "activity_reason": "recent commit activity",
        "activity_components": {"recent_commits": 100},
        "completion": progress(authority),
    }
    return value


class CompletionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.ranked = [
            project("private-project", private=True, authority="docs/SECRET_AUTHORITY.md"),
            project("public-project", private=False, authority="docs/PUBLIC_AUTHORITY.md"),
        ]

    def test_public_view_counts_private_completion_as_redacted(self):
        data = dual.build_public_data(self.ranked, [], NOW)
        self.assertEqual(data["completion_summary"]["valid"], 1)
        self.assertEqual(data["completion_summary"]["redacted"], 1)
        output = dual.render_public_html(data) + completion.render_markdown(data)
        self.assertIn("owner/public-project", output)
        self.assertNotIn("owner/private-project", output)
        self.assertNotIn("SECRET_AUTHORITY", output)

    def test_private_view_preserves_private_completion(self):
        data = dual.build_private_data(self.ranked, [], NOW, limit=2)
        self.assertEqual(data["completion_summary"]["valid"], 2)
        output = completion.render_markdown(data)
        self.assertIn("owner/private-project", output)
        self.assertIn("50.0%", output)

    def test_both_output_trees_receive_completion_report(self):
        original_public = dual.PUBLIC_OUT_DIR
        original_private = dual.PRIVATE_OUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                dual.PUBLIC_OUT_DIR = Path(temp) / "public"
                dual.PRIVATE_OUT_DIR = Path(temp) / "private-build"
                public_data, private_data = dual.build_views(self.ranked, [], NOW)
                dual.write_public_outputs(public_data)
                dual.write_private_outputs(private_data)
                self.assertTrue((dual.PUBLIC_OUT_DIR / "completion-status.md").is_file())
                self.assertTrue((dual.PRIVATE_OUT_DIR / "completion-status.md").is_file())
        finally:
            dual.PUBLIC_OUT_DIR = original_public
            dual.PRIVATE_OUT_DIR = original_private


if __name__ == "__main__":
    unittest.main()
