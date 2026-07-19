import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import completion_status as completion  # noqa: E402
import dual_status as dual  # noqa: E402
import internal_completion as internal  # noqa: E402

NOW = dt.datetime(2026, 7, 19, 12, 0, tzinfo=dt.timezone.utc)


def progress(authority: str, completed: int = 1, total: int = 2):
    return completion.validate_progress(
        {
            "schema_version": 1,
            "authority": authority,
            "stages": [
                {
                    "id": "work",
                    "label": "Work",
                    "completed": completed,
                    "total": total,
                }
            ],
            "overall": {"enabled": False},
        }
    )


def project(index: int, *, private: bool):
    name = f"private-project-{index}" if private else f"public-project-{index}"
    authority = f"docs/SECRET_AUTHORITY_{index}.md" if private else f"docs/PUBLIC_AUTHORITY_{index}.md"
    return {
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
        "activity_score": 100 - index,
        "activity_reason": "recent commit activity",
        "activity_components": {"recent_commits": 100 - index},
        "completion": progress(authority),
    }


class InternalCompletionTests(unittest.TestCase):
    def setUp(self):
        self.ranked = [project(0, private=False)] + [
            project(index, private=True) for index in range(1, 6)
        ]

    def test_internal_dataset_contains_every_repository_unredacted(self):
        data = internal.build_data(self.ranked, [], NOW)
        self.assertEqual(data["view"], "internal-owner-completion")
        self.assertEqual(data["repository_count"], 6)
        self.assertEqual(data["completion_summary"]["valid"], 6)

        by_name = {item["full_name"]: item for item in data["repositories"]}
        private_record = by_name["owner/private-project-5"]
        self.assertTrue(private_record["private"])
        self.assertEqual(
            private_record["completion"]["authority"],
            "docs/SECRET_AUTHORITY_5.md",
        )
        self.assertEqual(private_record["completion"]["stages"][0]["percentage"], 50.0)
        self.assertEqual(
            set(private_record),
            {"name", "full_name", "private", "url", "completion"},
        )

    def test_existing_private_dashboard_remains_top_five(self):
        private_data = dual.build_private_data(self.ranked, [], NOW, limit=5)
        internal_data = internal.build_data(self.ranked, [], NOW)
        self.assertEqual(private_data["project_count"], 5)
        self.assertEqual(internal_data["repository_count"], 6)
        self.assertNotIn(
            "owner/private-project-5",
            {item["full_name"] for item in private_data["projects"]},
        )
        self.assertIn(
            "owner/private-project-5",
            {item["full_name"] for item in internal_data["repositories"]},
        )

    def test_internal_output_is_separate_and_private_data_never_leaks_publicly(self):
        original_public = dual.PUBLIC_OUT_DIR
        original_private = dual.PRIVATE_OUT_DIR
        original_internal = internal.INTERNAL_OUT_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                dual.PUBLIC_OUT_DIR = root / "public"
                dual.PRIVATE_OUT_DIR = root / "private-build"
                internal.INTERNAL_OUT_DIR = root / "internal-build"

                public_data, private_data = dual.build_views(self.ranked, [], NOW)
                internal_data = internal.build_data(self.ranked, [], NOW)
                dual.write_public_outputs(public_data)
                dual.write_private_outputs(private_data)
                target = internal.write_output(internal_data)

                self.assertEqual(target, root / "internal-build" / "completion-status.json")
                self.assertTrue(target.is_file())
                self.assertFalse((root / "public" / "internal-build").exists())
                self.assertFalse((root / "public" / "completion-status.json").exists())

                public_text = "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in (root / "public").rglob("*")
                    if path.is_file()
                )
                self.assertNotIn("owner/private-project-1", public_text)
                self.assertNotIn("SECRET_AUTHORITY_1", public_text)
                self.assertIn("Private project #", public_text)

                written = json.loads(target.read_text(encoding="utf-8"))
                internal_text = json.dumps(written)
                self.assertIn("owner/private-project-1", internal_text)
                self.assertIn("SECRET_AUTHORITY_1", internal_text)
        finally:
            dual.PUBLIC_OUT_DIR = original_public
            dual.PRIVATE_OUT_DIR = original_private
            internal.INTERNAL_OUT_DIR = original_internal


if __name__ == "__main__":
    unittest.main()
