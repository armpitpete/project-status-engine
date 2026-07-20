import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_bootstrap as subject


STATUS = b"# Completion\n\nDelivery: 3 of 4 complete\n"
README_WITH_COUNT = b"# Project\n\nDelivery: 2 of 4 complete\n"


def repository(*, mixed=False):
    description = "A software utility"
    return {
        "full_name": "armpitpete/example",
        "private": False,
        "default_branch": "main",
        "description": description,
        "topics": [],
        "owner": {"login": "armpitpete"},
        "archived": False,
        "fork": False,
        "disabled": False,
        "mixed": mixed,
    }


def invalid_contract(authority="STATUS.md"):
    return json.dumps(
        {
            "schema_version": 1,
            "authority": authority,
            "project_type": "software",
            "stages": [],
            "overall": {"enabled": False},
        }
    ).encode("utf-8")


class RepairClient:
    def __init__(
        self,
        *,
        progress=None,
        readme=b"# Project\n",
        authorities=None,
        extra_paths=None,
    ):
        self.progress = progress if progress is not None else invalid_contract()
        self.readme = readme
        self.authorities = dict(authorities or {"STATUS.md": STATUS})
        self.extra_paths = list(extra_paths or ["package.json"])
        self.calls = []
        self.head_files = {}
        self.repair_pr = False

    def ref(self, full_name, branch):
        return {"object": {"sha": "a" * 40}}

    def tree(self, full_name, sha):
        paths = [
            subject.PROGRESS_PATH,
            subject.README_PATH,
            *self.authorities,
            *self.extra_paths,
        ]
        return [
            {"path": path, "type": "blob", "size": 256}
            for path in dict.fromkeys(paths)
        ]

    def open_prs(self, full_name, base):
        if not self.repair_pr:
            return []
        return [
            {
                "number": 12,
                "title": subject.CONTRACT_REPAIR_PR_TITLE,
                "draft": False,
                "head": {
                    "ref": subject.CONTRACT_REPAIR_BRANCH,
                    "sha": "b" * 40,
                },
            }
        ]

    def pr_files(self, full_name, number):
        paths = self.head_files or {
            subject.PROGRESS_PATH: b"",
            subject.README_PATH: b"",
        }
        return [{"filename": path} for path in sorted(paths)]

    def file(self, full_name, path, ref):
        if ref == "b" * 40 and path in self.head_files:
            return self.head_files[path], f"head-{path}"
        if path == subject.PROGRESS_PATH:
            return self.progress, "progress-sha"
        if path == subject.README_PATH:
            return self.readme, "readme-sha"
        if path in self.authorities:
            return self.authorities[path], f"authority-{path}"
        return None

    def write_commit(self, full_name, branch, base_sha, files, message):
        self.calls.append(("write", full_name, branch, base_sha, set(files), message))
        self.head_files = dict(files)
        return "b" * 40

    def upsert_contract_repair_pr(self, full_name, base, project_type, authority):
        self.calls.append(("upsert", full_name, base, project_type, authority))
        return "opened_pr"

    def clear_exception_report(self, full_name):
        self.calls.append(("clear", full_name))

    def repositories(self):
        return [repository()]

    def merge_bootstrap_pr(self, full_name, number, head_sha):
        self.calls.append(("merge", full_name, number, head_sha))


class CompletionContractRepairTests(unittest.TestCase):
    def test_parseable_invalid_contract_uses_only_its_declared_authority(self):
        client = RepairClient(
            authorities={
                "STATUS.md": STATUS,
                "README.md": README_WITH_COUNT,
            }
        )
        plan = subject.plan_repository(repository(), client)
        self.assertEqual(plan.action, "contract_repair")
        self.assertEqual(set(plan.files), {subject.PROGRESS_PATH, subject.README_PATH})
        repaired = json.loads(plan.files[subject.PROGRESS_PATH])
        self.assertEqual(repaired["authority"], "STATUS.md")
        self.assertEqual(
            [(stage["label"], stage["completed"], stage["total"]) for stage in repaired["stages"]],
            [("Delivery", 3, 4)],
        )
        self.assertEqual(repaired["overall"], {"enabled": False})
        self.assertNotIn("weight", repaired["stages"][0])

    def test_unreadable_contract_repairs_from_one_explicit_authority(self):
        client = RepairClient(
            progress=b"{not json",
            authorities={"STATUS.md": STATUS},
        )
        plan = subject.plan_repository(repository(), client)
        self.assertEqual(plan.action, "contract_repair")
        repaired = json.loads(plan.files[subject.PROGRESS_PATH])
        self.assertEqual(repaired["authority"], "STATUS.md")
        self.assertEqual(repaired["stages"][0]["completed"], 3)
        self.assertEqual(repaired["stages"][0]["total"], 4)

    def test_no_bounded_authority_leaves_missing_contract_unresolved(self):
        client = RepairClient(
            progress=b"{not json",
            authorities={"STATUS.md": b"# Status\nNo bounded completion evidence.\n"},
        )
        plan = subject.plan_repository(repository(), client)
        self.assertEqual(plan.action, "exception")
        self.assertEqual(plan.exception_code, "missing_completion_contract")
        self.assertEqual(plan.files, {})

    def test_conflicting_authorities_never_resolve_automatically(self):
        client = RepairClient(
            progress=b"{not json",
            readme=README_WITH_COUNT,
            authorities={"STATUS.md": STATUS},
        )
        plan = subject.plan_repository(repository(), client)
        self.assertEqual(plan.action, "exception")
        self.assertEqual(plan.exception_code, "contradictory_evidence")
        self.assertEqual(plan.files, {})

    def test_ambiguous_project_type_blocks_replacement_contract(self):
        client = RepairClient(
            progress=b"{not json",
            authorities={"STATUS.md": STATUS},
            extra_paths=["astro.config.mjs", "chapters/01.md"],
        )
        plan = subject.plan_repository(repository(mixed=True), client)
        self.assertEqual(plan.action, "exception")
        self.assertEqual(plan.exception_code, "ambiguous_project_type")
        self.assertEqual(plan.files, {})

    def test_unsafe_readme_markers_block_atomic_repair(self):
        duplicate = (
            subject.START_MARKER
            + b"\n"
            + subject.START_MARKER
            + b"\n"
            + subject.END_MARKER
        )
        client = RepairClient(readme=duplicate)
        plan = subject.plan_repository(repository(), client)
        self.assertEqual(plan.action, "exception")
        self.assertEqual(plan.exception_code, "missing_readme_marker")
        self.assertEqual(plan.files, {})

    def test_apply_uses_dedicated_branch_and_explicit_authority(self):
        client = RepairClient()
        plan = subject.plan_repository(repository(), client)
        result = subject.apply_plan(plan, client, apply=True)
        self.assertEqual(result.action, "opened_pr")
        write = next(call for call in client.calls if call[0] == "write")
        self.assertEqual(write[2], subject.CONTRACT_REPAIR_BRANCH)
        self.assertEqual(write[4], {subject.PROGRESS_PATH, subject.README_PATH})
        self.assertIn(
            ("upsert", "armpitpete/example", "main", "software", "STATUS.md"),
            client.calls,
        )

    def test_controlled_repair_pr_is_not_misclassified_as_human_onboarding(self):
        client = RepairClient()
        expected = subject.plan_repository(repository(), client)
        client.head_files = dict(expected.files)
        client.repair_pr = True
        repeated = subject.plan_repository(repository(), client)
        self.assertEqual(repeated.action, "contract_repair")
        self.assertIsNone(repeated.pending_pr_number)

    def test_merge_approved_revalidates_exact_contract_repair(self):
        client = RepairClient()
        expected = subject.plan_repository(repository(), client)
        client.head_files = dict(expected.files)
        client.repair_pr = True
        results = subject.merge_approved(client, apply=True)
        self.assertEqual([(item.action, item.code) for item in results], [("merged_pr", None)])
        self.assertIn(
            ("merge", "armpitpete/example", 12, "b" * 40),
            client.calls,
        )


if __name__ == "__main__":
    unittest.main()
