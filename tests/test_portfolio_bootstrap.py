import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import portfolio_bootstrap as subject


class PortfolioBootstrapTests(unittest.TestCase):
    def test_extracts_explicit_counts_and_checks_percentage(self):
        text = """# Current state\n\nControlled recovery: 30 of 36 — 83.3% complete\n"""
        stages = subject.extract_stages(text, "README.md")
        self.assertEqual(len(stages), 1)
        self.assertEqual((stages[0].completed, stages[0].total), (30, 36))
        self.assertEqual(stages[0].evidence, "README.md#L3")

    def test_extracts_realistic_bold_bullet_authority(self):
        text = """# Project Status

## Current recovery position

- controlled prose recovery: **30 of 36 sequences — 83.3%**;
"""
        stages = subject.extract_stages(text, "PROJECT_STATUS.md")
        self.assertEqual(stages[0].label, "controlled prose recovery")
        self.assertEqual((stages[0].completed, stages[0].total), (30, 36))

    def test_rejects_mismatched_percentage(self):
        with self.assertRaisesRegex(subject.BootstrapClosed, "contradictory_percentage"):
            subject.extract_stages(
                "# Completion\nDrafting: 3 of 4 — 90% complete\n", "STATUS.md"
            )

    def test_rejects_conflicting_counts_for_same_stage(self):
        with self.assertRaisesRegex(subject.BootstrapClosed, "contradictory_stage"):
            subject.extract_stages(
                "# Completion\nDrafting: 3 of 4 complete\nDrafting: 4 of 4 complete\n",
                "STATUS.md",
            )

    def test_ignores_bare_counts_without_completion_context(self):
        stages = subject.extract_stages("# Dimensions\nPanels: 3 of 4\n", "README.md")
        self.assertEqual(stages, [])

    def test_build_contract_disables_overall(self):
        contract = subject.build_contract(
            "manuscript",
            "README.md",
            [subject.EvidenceStage("Controlled recovery", 30, 36, "README.md#L4")],
        )
        self.assertEqual(contract["overall"], {"enabled": False})
        view = subject.progress_view(contract)
        self.assertEqual(view["stages"][0]["percentage"], 83.3)

    def test_appends_markers_without_changing_human_bytes(self):
        original = b"# Project\n\nHuman text.\n"
        progress = {
            "authority": "README.md",
            "stages": [
                {
                    "id": "drafting",
                    "label": "Drafting",
                    "completed": 1,
                    "total": 2,
                    "percentage": 50.0,
                }
            ],
            "overall_percentage": None,
        }
        desired = subject.desired_readme(original, progress)
        self.assertTrue(desired.startswith(original))
        self.assertEqual(desired.count(subject.START_MARKER), 1)
        self.assertEqual(desired.count(subject.END_MARKER), 1)

    def test_replaces_only_marker_interior(self):
        original = (
            b"# Project\n\n"
            + subject.START_MARKER
            + b"\nold\n"
            + subject.END_MARKER
            + b"\nTail\n"
        )
        progress = {
            "authority": "STATUS.md",
            "stages": [
                {
                    "id": "build",
                    "label": "Build",
                    "completed": 2,
                    "total": 2,
                    "percentage": 100.0,
                }
            ],
            "overall_percentage": None,
        }
        desired = subject.desired_readme(original, progress)
        self.assertTrue(desired.startswith(b"# Project\n\n" + subject.START_MARKER))
        self.assertTrue(desired.endswith(subject.END_MARKER + b"\nTail\n"))

    def test_classifies_without_using_classification_for_completion(self):
        repo = {"name": "example", "full_name": "owner/example"}
        self.assertEqual(
            subject.classify_project(repo, ["package.json", "src/pages/index.astro"]),
            "website",
        )
        self.assertEqual(
            subject.classify_project(repo, ["chapters/01.md", "README.md"]),
            "manuscript",
        )

    def test_accepts_existing_weighted_overall_contract(self):
        contract = {
            "schema_version": 1,
            "authority": "STATUS.md",
            "stages": [
                {"id": "a", "label": "A", "completed": 1, "total": 2, "weight": 40},
                {"id": "b", "label": "B", "completed": 3, "total": 4, "weight": 60},
            ],
            "overall": {"enabled": True},
        }
        view = subject.validate_progress(contract)
        self.assertEqual(view["overall_percentage"], 65.0)
        self.assertIn(b"Overall completion: **65.0%**", subject.render_generated_section(view))

    def test_contract_json_round_trip(self):
        contract = subject.build_contract(
            "software",
            "docs/PROJECT_STATUS.md",
            [subject.EvidenceStage("Milestones", 4, 5, "docs/PROJECT_STATUS.md#L8")],
        )
        encoded = (json.dumps(contract, indent=2) + "\n").encode()
        self.assertEqual(subject.progress_view(json.loads(encoded))["stages"][0]["completed"], 4)


if __name__ == "__main__":
    unittest.main()
