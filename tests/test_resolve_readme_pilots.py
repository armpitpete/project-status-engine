import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_readme_pilots as resolver  # noqa: E402


def completion(project_type, authority, stage_ids):
    return {
        "state": "valid",
        "project_type": project_type,
        "authority": authority,
        "stages": [
            {
                "id": stage_id,
                "percentage": 50.0,
            }
            for stage_id in stage_ids
        ],
    }


def record(name, private, project_type, authority, stage_ids):
    return {
        "full_name": name,
        "private": private,
        "completion": completion(project_type, authority, stage_ids),
    }


class ResolverTests(unittest.TestCase):
    def inputs(self, repositories, targets):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        dataset = root / "dataset.json"
        selectors = root / "selectors.json"
        dataset.write_text(
            json.dumps(
                {
                    "view": "internal-owner-completion",
                    "repositories": repositories,
                }
            ),
            encoding="utf-8",
        )
        selectors.write_text(
            json.dumps({"schema_version": 1, "targets": targets}),
            encoding="utf-8",
        )
        self.addCleanup(temp.cleanup)
        return dataset, selectors

    def policy_inputs(self, repositories, mode="all-valid"):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        dataset = root / "dataset.json"
        policy = root / "policy.json"
        dataset.write_text(
            json.dumps(
                {
                    "view": "internal-owner-completion",
                    "repositories": repositories,
                }
            ),
            encoding="utf-8",
        )
        policy.write_text(
            json.dumps({"schema_version": 1, "mode": mode}),
            encoding="utf-8",
        )
        self.addCleanup(temp.cleanup)
        return dataset, policy

    def test_resolves_three_unique_contracts_without_committed_names(self):
        targets = [
            {
                "id": "pilot-01",
                "project_type": "manuscript",
                "authority": "docs/MANUSCRIPT.md",
                "private": True,
                "stage_ids": ["draft", "proof"],
            },
            {
                "id": "pilot-02",
                "project_type": "language-canon",
                "authority": "docs/LANGUAGE.md",
                "private": True,
                "stage_ids": ["grammar"],
            },
            {
                "id": "pilot-03",
                "project_type": "software",
                "authority": "README.md",
                "private": False,
                "stage_ids": ["engine"],
            },
        ]
        names = ["owner/secret-a", "owner/secret-b", "owner/public-c"]
        dataset, selectors = self.inputs(
            [
                record(names[0], True, "manuscript", "docs/MANUSCRIPT.md", ["draft", "proof"]),
                record(names[1], True, "language-canon", "docs/LANGUAGE.md", ["grammar"]),
                record(names[2], False, "software", "README.md", ["engine"]),
                record("owner/not-pilot", False, "other", "README.md", ["work"]),
            ],
            targets,
        )
        result = resolver.resolve(dataset, selectors)
        self.assertEqual(
            result["target_hashes"],
            [resolver.identifier(name) for name in names],
        )
        selector_text = selectors.read_text(encoding="utf-8")
        for name in names:
            self.assertNotIn(name, selector_text)

    def test_ambiguous_selector_fails_closed(self):
        target = {
            "id": "pilot-01",
            "project_type": "software",
            "authority": "README.md",
            "private": False,
            "stage_ids": ["engine"],
        }
        dataset, selectors = self.inputs(
            [
                record("owner/a", False, "software", "README.md", ["engine"]),
                record("owner/b", False, "software", "README.md", ["engine"]),
            ],
            [target],
        )
        with self.assertRaisesRegex(resolver.ResolutionClosed, "selector_match"):
            resolver.resolve(dataset, selectors)

    def test_invalid_completion_fails_closed(self):
        target = {
            "id": "pilot-01",
            "project_type": "software",
            "authority": "README.md",
            "private": False,
            "stage_ids": ["engine"],
        }
        bad = record("owner/a", False, "software", "README.md", ["engine"])
        bad["completion"]["stages"][0]["percentage"] = float("nan")
        dataset, selectors = self.inputs([bad], [target])
        with self.assertRaisesRegex(resolver.ResolutionClosed, "completion_percentage"):
            resolver.resolve(dataset, selectors)

    def test_output_contains_only_hashes(self):
        target = {
            "id": "pilot-01",
            "project_type": "software",
            "authority": "README.md",
            "private": False,
            "stage_ids": ["engine"],
        }
        name = "owner/private-name"
        dataset, selectors = self.inputs(
            [record(name, False, "software", "README.md", ["engine"])],
            [target],
        )
        result = resolver.resolve(dataset, selectors)
        text = json.dumps(result)
        self.assertNotIn(name, text)
        self.assertNotIn("README.md", text)
        self.assertEqual(len(result["target_hashes"]), 1)

    def test_all_valid_policy_selects_every_valid_repository(self):
        names = ["owner/z-private", "owner/a-public", "owner/m-private"]
        repositories = [
            record(names[0], True, "manuscript", "docs/A.md", ["draft"]),
            record(names[1], False, "software", "README.md", ["release"]),
            record(names[2], True, "website", "docs/STATUS.md", ["routes"]),
            {
                "full_name": "owner/not-configured",
                "private": True,
                "completion": {"state": "not-configured"},
            },
            {
                "full_name": "owner/invalid-authority",
                "private": False,
                "completion": {"state": "invalid", "error": "bad contract"},
            },
        ]
        dataset, policy = self.policy_inputs(repositories)
        result = resolver.resolve_policy(dataset, policy)
        self.assertEqual(
            result["target_hashes"],
            sorted(resolver.identifier(name) for name in names),
        )

    def test_all_valid_policy_output_contains_no_repository_identity(self):
        name = "owner/very-private-project"
        dataset, policy = self.policy_inputs(
            [record(name, True, "manuscript", "docs/AUTHORITY.md", ["proof"])]
        )
        result = resolver.resolve_policy(dataset, policy)
        text = json.dumps(result)
        self.assertNotIn(name, text)
        self.assertNotIn("AUTHORITY", text)
        self.assertEqual(result["target_hashes"], [resolver.identifier(name)])

    def test_all_valid_policy_fails_when_no_valid_target_exists(self):
        dataset, policy = self.policy_inputs(
            [
                {
                    "full_name": "owner/unconfigured",
                    "private": True,
                    "completion": {"state": "not-configured"},
                }
            ]
        )
        with self.assertRaisesRegex(resolver.ResolutionClosed, "policy_no_valid_targets"):
            resolver.resolve_policy(dataset, policy)

    def test_all_valid_policy_rejects_unknown_mode(self):
        dataset, policy = self.policy_inputs(
            [record("owner/a", False, "software", "README.md", ["engine"])],
            mode="all-repositories",
        )
        with self.assertRaisesRegex(resolver.ResolutionClosed, "policy_mode"):
            resolver.resolve_policy(dataset, policy)

    def test_duplicate_repository_record_fails_closed(self):
        duplicate = record("owner/a", False, "software", "README.md", ["engine"])
        dataset, policy = self.policy_inputs([duplicate, duplicate])
        with self.assertRaisesRegex(
            resolver.ResolutionClosed, "dataset_duplicate_repository"
        ):
            resolver.resolve_policy(dataset, policy)


if __name__ == "__main__":
    unittest.main()
