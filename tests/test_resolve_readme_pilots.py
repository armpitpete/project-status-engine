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


if __name__ == "__main__":
    unittest.main()
