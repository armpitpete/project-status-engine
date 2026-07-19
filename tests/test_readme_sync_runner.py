import base64
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import readme_sync as core  # noqa: E402
import readme_sync_runner as runner  # noqa: E402


def completion(percentage=50.0):
    return {
        "configured": True,
        "state": "valid",
        "schema_version": 1,
        "authority": "docs/AUTHORITY.md",
        "overall_enabled": False,
        "overall_percentage": None,
        "stages": [
            {
                "id": "work",
                "label": "Work",
                "completed": 1,
                "total": 2,
                "percentage": percentage,
                "state": "in_progress",
                "weight": None,
                "evidence": "docs/AUTHORITY.md",
            }
        ],
        "source_path": ".project/progress.json",
    }


def empty_readme():
    return (
        b"# Project\n\nHuman text.\n\n"
        + core.START_MARKER
        + b"\n"
        + core.END_MARKER
        + b"\n"
    )


def payload(content):
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(content).decode("ascii"),
        "sha": "blob-sha",
    }


class FakeClient:
    def __init__(self, default_readme, *, sync_readme=None, pr_number=None):
        self.default_readme = default_readme
        self.sync_readme = sync_readme
        self.pr_number = pr_number
        self.calls = []

    def repository(self, full_name):
        self.calls.append(("repository", full_name))
        return {"default_branch": "main", "owner": {"login": "owner"}}

    def file(self, full_name, path, ref):
        self.calls.append(("file", full_name, path, ref))
        if ref == core.SYNC_BRANCH:
            return payload(self.sync_readme)
        return payload(self.default_readme)

    def ref(self, full_name, branch):
        self.calls.append(("ref", full_name, branch))
        if branch == core.SYNC_BRANCH:
            return None if self.sync_readme is None else {"object": {"sha": "sync-sha"}}
        return {"object": {"sha": "main-sha"}}

    def open_pull_requests(self, full_name, owner, branch, base):
        self.calls.append(("open_pull_requests", full_name, owner, branch, base))
        return [] if self.pr_number is None else [{"number": self.pr_number}]

    def create_ref(self, *args):
        self.calls.append(("create_ref", *args))

    def update_ref(self, *args):
        self.calls.append(("update_ref", *args))

    def update_file(self, *args):
        self.calls.append(("update_file", *args))

    def create_pull_request(self, *args):
        self.calls.append(("create_pull_request", *args))

    def update_pull_request(self, *args):
        self.calls.append(("update_pull_request", *args))


class OpenPullRequestIdempotenceTests(unittest.TestCase):
    def target(self):
        return core.Target(
            target_id=core.target_id("owner/repo"),
            full_name="owner/repo",
            private=False,
            completion=completion(),
        )

    def write_calls(self, client):
        writes = {
            "create_ref",
            "update_ref",
            "update_file",
            "create_pull_request",
            "update_pull_request",
        }
        return [call for call in client.calls if call[0] in writes]

    def test_open_pr_with_desired_readme_creates_no_commit(self):
        target = self.target()
        default = empty_readme()
        desired = core.desired_readme(default, target.completion)
        client = FakeClient(default, sync_readme=desired, pr_number=7)

        plan = runner.prepare_target(target, client)
        self.assertEqual(plan.action, "unchanged_pr")
        result = runner.apply_plan(plan, client, apply=True)

        self.assertEqual(result.action, "unchanged_pr")
        self.assertEqual(self.write_calls(client), [])

    def test_open_pr_is_updated_only_when_desired_content_changed(self):
        target = self.target()
        default = empty_readme()
        stale = core.desired_readme(default, completion(percentage=25.0))
        client = FakeClient(default, sync_readme=stale, pr_number=7)

        plan = runner.prepare_target(target, client)
        self.assertEqual(plan.action, "update")
        result = runner.apply_plan(plan, client, apply=True)

        self.assertEqual(result.action, "updated_pr")
        self.assertTrue(any(call[0] == "update_file" for call in client.calls))
        self.assertIn(("update_pull_request", "owner/repo", 7), client.calls)

    def test_default_branch_already_current_remains_noop(self):
        target = self.target()
        default = core.desired_readme(empty_readme(), target.completion)
        client = FakeClient(default)

        plan = runner.prepare_target(target, client)
        self.assertEqual(plan.action, "unchanged")
        result = runner.apply_plan(plan, client, apply=True)

        self.assertEqual(result.action, "unchanged")
        self.assertEqual(self.write_calls(client), [])

    def test_open_pr_without_automation_branch_fails_closed(self):
        target = self.target()
        client = FakeClient(empty_readme(), sync_readme=None, pr_number=7)
        with self.assertRaisesRegex(core.SyncClosed, "open_pr_branch_missing"):
            runner.prepare_target(target, client)
        self.assertEqual(self.write_calls(client), [])


if __name__ == "__main__":
    unittest.main()
