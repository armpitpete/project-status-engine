import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import readme_sync as sync  # noqa: E402


def completion(authority="docs/AUTHORITY.md", percentage=50.0):
    return {
        "configured": True,
        "state": "valid",
        "schema_version": 1,
        "authority": authority,
        "overall_enabled": False,
        "overall_percentage": None,
        "stages": [
            {
                "id": "work",
                "label": "Work",
                "completed": 1,
                "total": 3,
                "percentage": percentage,
                "state": "in_progress",
                "weight": None,
                "evidence": authority,
            }
        ],
        "source_path": ".project/progress.json",
    }


def record(name, *, private=False, value=None):
    return {
        "name": name.rsplit("/", 1)[-1],
        "full_name": name,
        "private": private,
        "url": f"https://example.test/{name}",
        "completion": value if value is not None else completion(),
    }


def readme_bytes(newline=b"\n", inner=b"old generated"):
    return (
        b"# Title" + newline
        + b"" + newline
        + b"Human prose \xe2\x80\x94 unchanged." + newline
        + sync.START_MARKER + newline
        + inner + newline
        + sync.END_MARKER + newline
        + b"" + newline
        + b"Human tail." + newline
    )


class FakeClient:
    def __init__(self, repositories):
        self.repositories = repositories
        self.calls = []

    def repository(self, full_name):
        self.calls.append(("repository", full_name))
        value = self.repositories[full_name]
        return {
            "default_branch": value.get("default_branch", "main"),
            "owner": {"login": full_name.split("/", 1)[0]},
        }

    def file(self, full_name, path, ref):
        self.calls.append(("file", full_name, path, ref))
        raw = self.repositories[full_name]["readme"]
        return {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
            "sha": "blob-sha",
        }

    def ref(self, full_name, branch):
        self.calls.append(("ref", full_name, branch))
        if branch == sync.SYNC_BRANCH:
            return self.repositories[full_name].get("sync_ref")
        return {"object": {"sha": "main-sha"}}

    def open_pull_requests(self, full_name, owner, branch, base):
        self.calls.append(("open_pull_requests", full_name, owner, branch, base))
        number = self.repositories[full_name].get("pr")
        return [] if number is None else [{"number": number}]

    def create_ref(self, full_name, branch, sha):
        self.calls.append(("create_ref", full_name, branch, sha))

    def update_ref(self, full_name, branch, sha):
        self.calls.append(("update_ref", full_name, branch, sha))

    def update_file(self, full_name, path, branch, content, source_sha):
        self.calls.append(
            ("update_file", full_name, path, branch, content, source_sha)
        )
        return {"commit": {"sha": "commit-sha"}}

    def create_pull_request(self, full_name, branch, base):
        self.calls.append(("create_pull_request", full_name, branch, base))

    def update_pull_request(self, full_name, number):
        self.calls.append(("update_pull_request", full_name, number))


class ReadmeReplacementTests(unittest.TestCase):
    def test_replaces_only_generated_bytes_with_lf(self):
        source = readme_bytes()
        generated = sync.render_generated_section(completion(), b"\n")
        result = sync.replace_generated_section(source, generated)
        source_prefix = source.split(sync.START_MARKER, 1)[0] + sync.START_MARKER
        source_suffix = sync.END_MARKER + source.split(sync.END_MARKER, 1)[1]
        self.assertEqual(result[: len(source_prefix)], source_prefix)
        self.assertEqual(result[-len(source_suffix) :], source_suffix)
        self.assertIn(b"**50.0%**", result)

    def test_preserves_crlf_and_non_ascii_human_text(self):
        source = readme_bytes(b"\r\n")
        result = sync.desired_readme(source, completion())
        self.assertIn(b"Human prose \xe2\x80\x94 unchanged.\r\n", result)
        self.assertNotIn(b"\n", result.replace(b"\r\n", b""))

    def test_missing_or_duplicate_markers_fail_closed(self):
        with self.assertRaisesRegex(sync.SyncClosed, "readme_markers"):
            sync.desired_readme(b"# No markers\n", completion())
        duplicate = readme_bytes() + sync.START_MARKER
        with self.assertRaisesRegex(sync.SyncClosed, "readme_markers"):
            sync.desired_readme(duplicate, completion())

    def test_percentage_is_consumed_not_recalculated(self):
        result = sync.desired_readme(readme_bytes(), completion(percentage=77.7))
        self.assertIn(b"`1/3` \xe2\x80\x94 **77.7%**", result)
        self.assertNotIn(b"33.3%", result)


class DatasetTests(unittest.TestCase):
    def write_inputs(self, records, hashes):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        dataset = root / "completion-status.json"
        allowlist = root / "allowlist.json"
        dataset.write_text(
            json.dumps(
                {
                    "view": "internal-owner-completion",
                    "repositories": records,
                }
            ),
            encoding="utf-8",
        )
        allowlist.write_text(
            json.dumps({"schema_version": 1, "target_hashes": hashes}),
            encoding="utf-8",
        )
        return temp, dataset, allowlist

    def test_selects_only_opaque_allowlisted_targets(self):
        names = ["owner/a", "owner/b", "owner/c", "owner/not-pilot"]
        hashes = [sync.target_id(name) for name in names[:3]]
        temp, dataset, allowlist = self.write_inputs(
            [record(name, private=name != "owner/c") for name in names], hashes
        )
        self.addCleanup(temp.cleanup)
        targets = sync.load_targets(dataset, allowlist)
        self.assertEqual({target.full_name for target in targets}, set(names[:3]))
        allowlist_text = allowlist.read_text(encoding="utf-8")
        for name in names:
            self.assertNotIn(name, allowlist_text)

    def test_invalid_or_missing_authority_closes_before_api_use(self):
        name = "owner/private"
        value = completion()
        value["authority"] = ""
        temp, dataset, allowlist = self.write_inputs(
            [record(name, private=True, value=value)], [sync.target_id(name)]
        )
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(sync.SyncClosed, "completion_authority_missing"):
            sync.load_targets(dataset, allowlist)

    def test_missing_pilot_closes(self):
        temp, dataset, allowlist = self.write_inputs(
            [record("owner/a")],
            [sync.target_id("owner/a"), sync.target_id("owner/b")],
        )
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(sync.SyncClosed, "pilot_missing"):
            sync.load_targets(dataset, allowlist)


class SynchronisationTests(unittest.TestCase):
    def target(self, name="owner/repo", *, private=False, value=None):
        return sync.Target(
            target_id=sync.target_id(name),
            full_name=name,
            private=private,
            completion=value if value is not None else completion(),
        )

    def test_unchanged_readme_creates_no_commit_or_branch_write(self):
        target = self.target()
        desired = sync.desired_readme(readme_bytes(), target.completion)
        client = FakeClient({"owner/repo": {"readme": desired}})
        plan = sync.prepare_target(target, client)
        result = sync.apply_plan(plan, client, apply=True)
        self.assertEqual(result.action, "unchanged")
        writes = {"create_ref", "update_ref", "update_file", "create_pull_request", "update_pull_request"}
        self.assertFalse(any(call[0] in writes for call in client.calls))

    def test_apply_writes_only_automation_branch_and_opens_reviewable_pr(self):
        target = self.target()
        client = FakeClient({"owner/repo": {"readme": readme_bytes()}})
        plan = sync.prepare_target(target, client)
        applied = sync.apply_plan(plan, client, apply=True)
        self.assertEqual(applied.action, "opened_pr")
        update = next(call for call in client.calls if call[0] == "update_file")
        self.assertEqual(update[3], sync.SYNC_BRANCH)
        self.assertNotEqual(update[3], "main")
        self.assertIn(("create_pull_request", "owner/repo", sync.SYNC_BRANCH, "main"), client.calls)

    def test_existing_pr_is_updated(self):
        target = self.target()
        client = FakeClient(
            {
                "owner/repo": {
                    "readme": readme_bytes(),
                    "sync_ref": {"object": {"sha": "old"}},
                    "pr": 12,
                }
            }
        )
        plan = sync.prepare_target(target, client)
        applied = sync.apply_plan(plan, client, apply=True)
        self.assertEqual(applied.action, "updated_pr")
        self.assertIn(("update_pull_request", "owner/repo", 12), client.calls)
        self.assertFalse(any(call[0] == "create_pull_request" for call in client.calls))

    def test_all_targets_preflight_before_any_write(self):
        client = FakeClient(
            {
                "owner/good": {"readme": readme_bytes()},
                "owner/bad": {"readme": b"# missing markers\n"},
            }
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "dataset.json"
            allowlist = root / "allowlist.json"
            dataset.write_text(
                json.dumps(
                    {
                        "view": "internal-owner-completion",
                        "repositories": [
                            record("owner/good"),
                            record("owner/bad"),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            allowlist.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "target_hashes": [
                            sync.target_id("owner/good"),
                            sync.target_id("owner/bad"),
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(sync.SyncClosed):
                sync.run(dataset, allowlist, apply=True, client=client)
        writes = {"create_ref", "update_ref", "update_file", "create_pull_request", "update_pull_request"}
        self.assertFalse(any(call[0] in writes for call in client.calls))

    def test_generated_readme_contains_only_target_completion(self):
        own = self.target("owner/private-one", private=True)
        other_secret = "OTHER_PRIVATE_REPOSITORY_SECRET"
        result = sync.desired_readme(readme_bytes(), own.completion)
        self.assertNotIn(other_secret.encode(), result)

    def test_safe_logs_and_pr_metadata_contain_no_private_data_or_credentials(self):
        name = "owner/highly-private-repository"
        result = sync.SyncResult(sync.target_id(name), "opened_pr")
        log = sync.safe_event(result)
        forbidden = [
            name,
            "docs/AUTHORITY.md",
            "Work",
            "secret-token-value",
            "50.0%",
        ]
        combined = log + sync.PR_TITLE + sync.PR_BODY
        for value in forbidden:
            self.assertNotIn(value, combined)
        self.assertIn(sync.target_id(name)[:12], log)

    def test_api_failure_is_sanitised(self):
        error = sync.ApiFailure("update_file", 403)
        text = str(error)
        self.assertEqual(text, "api_update_file_403")
        self.assertNotIn("github.com", text)
        self.assertNotIn("owner/repo", text)


if __name__ == "__main__":
    unittest.main()
