import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_bootstrap as subject


def contract():
    return {
        "schema_version": 1,
        "authority": "STATUS.md",
        "project_type": "software",
        "stages": [
            {
                "id": "delivery",
                "label": "Delivery",
                "completed": 1,
                "total": 2,
                "evidence": "STATUS.md#L3",
            }
        ],
        "overall": {"enabled": False},
    }


def repository():
    return {
        "full_name": "armpitpete/example",
        "private": False,
        "default_branch": "main",
        "description": "A software utility",
        "topics": [],
        "owner": {"login": "armpitpete"},
        "archived": False,
        "fork": False,
        "disabled": False,
    }


class PlanningClient:
    def __init__(self, readme=b"# Project\n"):
        self.readme = readme
        self.calls = []
        self.head_readme = None
        self.repair_pr = False

    def ref(self, full_name, branch):
        return {"object": {"sha": "a" * 40}}

    def tree(self, full_name, sha):
        return [
            {"path": "README.md", "type": "blob", "size": len(self.readme)},
            {"path": "package.json", "type": "blob", "size": 2},
            {"path": ".project/progress.json", "type": "blob", "size": 128},
        ]

    def open_prs(self, full_name, base):
        if not self.repair_pr:
            return []
        return [
            {
                "number": 9,
                "title": subject.README_REPAIR_PR_TITLE,
                "draft": False,
                "head": {
                    "ref": subject.README_REPAIR_BRANCH,
                    "sha": "b" * 40,
                },
            }
        ]

    def pr_files(self, full_name, number):
        return [{"filename": "README.md"}]

    def file(self, full_name, path, ref):
        if path == subject.PROGRESS_PATH:
            return json.dumps(contract()).encode("utf-8"), "progress-sha"
        if path == subject.README_PATH:
            if ref == "b" * 40 and self.head_readme is not None:
                return self.head_readme, "head-readme-sha"
            return self.readme, "readme-sha"
        return None

    def write_commit(self, full_name, branch, base_sha, files, message):
        self.calls.append(("write", full_name, branch, base_sha, set(files), message))
        self.head_readme = files[subject.README_PATH]
        return "b" * 40

    def upsert_readme_repair_pr(self, full_name, base, project_type, authority):
        self.calls.append(("upsert", full_name, base, project_type, authority))
        return "opened_pr"

    def clear_exception_report(self, full_name):
        self.calls.append(("clear", full_name))

    def repositories(self):
        return [repository()]

    def merge_bootstrap_pr(self, full_name, number, head_sha):
        self.calls.append(("merge", full_name, number, head_sha))


class ReadmeMarkerRepairTests(unittest.TestCase):
    def test_marker_state_accepts_only_absent_or_one_ordered_pair(self):
        self.assertEqual(subject.readme_marker_state(b"# Project\n"), "absent")
        valid = (
            subject.START_MARKER
            + b"\nold\n"
            + subject.END_MARKER
            + b"\n"
        )
        self.assertEqual(subject.readme_marker_state(valid), "valid")
        with self.assertRaisesRegex(subject.BootstrapClosed, "readme_markers"):
            subject.readme_marker_state(subject.START_MARKER + subject.START_MARKER)
        with self.assertRaisesRegex(subject.BootstrapClosed, "readme_marker_order"):
            subject.readme_marker_state(
                subject.END_MARKER + b"\n" + subject.START_MARKER
            )

    def test_existing_contract_with_absent_markers_enters_readme_only_lane(self):
        client = PlanningClient()
        plan = subject.plan_repository(repository(), client)
        self.assertEqual(plan.action, "readme_repair")
        self.assertEqual(set(plan.files), {subject.README_PATH})
        self.assertTrue(plan.files[subject.README_PATH].startswith(client.readme))
        self.assertNotIn(subject.PROGRESS_PATH, plan.files)

    def test_valid_marker_interior_update_enters_readme_only_lane(self):
        old = (
            b"# Project\n\n"
            + subject.START_MARKER
            + b"\nold generated text\n"
            + subject.END_MARKER
            + b"\nTail\n"
        )
        plan = subject.plan_repository(repository(), PlanningClient(old))
        self.assertEqual(plan.action, "readme_repair")
        desired = plan.files[subject.README_PATH]
        self.assertTrue(desired.startswith(b"# Project\n\n" + subject.START_MARKER))
        self.assertTrue(desired.endswith(subject.END_MARKER + b"\nTail\n"))

    def test_duplicate_or_reversed_markers_remain_primary_exception(self):
        duplicate = (
            subject.START_MARKER
            + b"\n"
            + subject.START_MARKER
            + b"\n"
            + subject.END_MARKER
        )
        reversed_pair = subject.END_MARKER + b"\n" + subject.START_MARKER
        for readme in (duplicate, reversed_pair):
            with self.subTest(readme=readme):
                plan = subject.plan_repository(repository(), PlanningClient(readme))
                self.assertEqual(plan.action, "exception")
                self.assertEqual(plan.exception_code, "missing_readme_marker")
                self.assertEqual(plan.files, {})

    def test_apply_uses_dedicated_branch_and_readme_only_scope(self):
        client = PlanningClient()
        plan = subject.plan_repository(repository(), client)
        result = subject.apply_plan(plan, client, apply=True)
        self.assertEqual(result.action, "opened_pr")
        write = next(call for call in client.calls if call[0] == "write")
        self.assertEqual(write[2], subject.README_REPAIR_BRANCH)
        self.assertEqual(write[4], {subject.README_PATH})
        self.assertNotIn(subject.PROGRESS_PATH, write[4])
        self.assertIn(
            ("upsert", "armpitpete/example", "main", "software", "STATUS.md"),
            client.calls,
        )

    def test_merge_approved_revalidates_exact_readme_repair(self):
        client = PlanningClient()
        expected = subject.plan_repository(repository(), client)
        client.head_readme = expected.files[subject.README_PATH]
        client.repair_pr = True
        results = subject.merge_approved(client, apply=True)
        self.assertEqual([(item.action, item.code) for item in results], [("merged_pr", None)])
        self.assertIn(
            ("merge", "armpitpete/example", 9, "b" * 40),
            client.calls,
        )


if __name__ == "__main__":
    unittest.main()
