import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_bootstrap as subject


PRIMARY_CODES = (
    "missing_completion_contract",
    "missing_authoritative_source",
    "missing_readme_marker",
    "ambiguous_project_type",
    "contradictory_evidence",
    "no_completion_evidence",
    "inactive_repository_candidate",
)


def valid_contract():
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


class PlanningClient:
    def __init__(self, *, contract=None, readme=b"# Project\n", pending=False, paths=None):
        self.contract = contract
        self.readme = readme
        self.pending = pending
        self.paths = paths or ["README.md", "package.json"]

    def ref(self, full_name, branch):
        return {"object": {"sha": "main-sha"}}

    def tree(self, full_name, sha):
        return [
            {"path": path, "type": "blob", "size": 128}
            for path in self.paths
        ]

    def open_prs(self, full_name, base):
        if not self.pending:
            return []
        return [{"number": 17, "head": {"ref": "owner/reviewed-onboarding"}}]

    def pr_files(self, full_name, number):
        return [{"filename": subject.PROGRESS_PATH}]

    def file(self, full_name, path, ref):
        if path == subject.PROGRESS_PATH:
            if self.contract is None:
                return None
            return (json.dumps(self.contract).encode("utf-8"), "progress-sha")
        if path == subject.README_PATH:
            return (self.readme, "readme-sha")
        return None


class PortfolioExceptionTaxonomyTests(unittest.TestCase):
    def test_registry_contains_exact_primary_taxonomy(self):
        self.assertEqual(subject.PRIMARY_EXCEPTION_CODES, PRIMARY_CODES)
        self.assertEqual(
            subject.AUTHORITY_REGISTRY["repository_identity_mode"],
            "dynamic-owner-inventory",
        )

    def test_classifier_uses_one_primary_code_without_inference(self):
        cases = [
            (
                dict(
                    raw_code="contradictory_stage",
                    has_contract=False,
                    authority_paths=["STATUS.md"],
                    project_type="software",
                ),
                "contradictory_evidence",
            ),
            (
                dict(
                    raw_code="progress_shape",
                    has_contract=True,
                    authority_paths=[],
                    project_type="software",
                ),
                "missing_completion_contract",
            ),
            (
                dict(
                    raw_code="readme_markers",
                    has_contract=True,
                    authority_paths=["STATUS.md"],
                    project_type="software",
                ),
                "missing_readme_marker",
            ),
            (
                dict(
                    raw_code="insufficient_authority",
                    has_contract=False,
                    authority_paths=["README.md"],
                    project_type="unknown",
                ),
                "ambiguous_project_type",
            ),
            (
                dict(
                    raw_code="insufficient_authority",
                    has_contract=False,
                    authority_paths=[],
                    project_type="software",
                ),
                "missing_authoritative_source",
            ),
            (
                dict(
                    raw_code="insufficient_authority",
                    has_contract=False,
                    authority_paths=["README.md"],
                    project_type="software",
                ),
                "no_completion_evidence",
            ),
            (
                dict(
                    raw_code="insufficient_authority",
                    has_contract=False,
                    authority_paths=[],
                    project_type="software",
                    inactive=True,
                ),
                "inactive_repository_candidate",
            ),
        ]
        for evidence, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(subject.classify_primary_exception(**evidence), expected)

        with self.assertRaisesRegex(
            subject.BootstrapClosed, "exception_taxonomy_unclassified"
        ):
            subject.classify_primary_exception(
                "unrecognised_evidence",
                has_contract=False,
                authority_paths=[],
                project_type="software",
            )

    def test_report_separates_primary_exceptions_from_failures(self):
        report = json.loads(
            subject.aggregate_run_report(
                "apply",
                50,
                [
                    subject.Result("a" * 64, "exception", "contradictory_evidence"),
                    subject.Result("b" * 64, "failure", "api_tree_403"),
                ],
                "failed",
                inventory_sources={"authenticated": 50, "public": 19, "union": 50},
                minimum_inventory=49,
            )
        )
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(tuple(report["exceptions"]), tuple(sorted(PRIMARY_CODES)))
        self.assertEqual(report["exceptions"]["contradictory_evidence"], 1)
        self.assertEqual(sum(report["exceptions"].values()), 1)
        self.assertEqual(report["failures"], {"api_tree_403": 1})
        self.assertNotIn("codes", report)

    def test_committed_bootstrap_baseline_preserves_inventory_and_actions(self):
        report = json.loads((ROOT / "portfolio-bootstrap-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["inventory"], 50)
        self.assertEqual(
            report["actions"],
            {"exception": 42, "opened_pr": 5, "unchanged": 3},
        )
        self.assertEqual(sum(report["exceptions"].values()), 42)

    def test_existing_onboarding_pr_remains_pending(self):
        repo = {
            "full_name": "owner/repo",
            "private": False,
            "default_branch": "main",
            "description": "",
            "topics": [],
        }
        plan = subject.plan_repository(
            repo,
            PlanningClient(pending=True, paths=["README.md"]),
        )
        self.assertEqual(plan.action, "pending_onboarding_pr")
        self.assertEqual(plan.pending_pr_number, 17)

    def test_readme_only_repair_stays_separate_from_completion_exception(self):
        repo = {
            "full_name": "owner/repo",
            "private": False,
            "default_branch": "main",
            "description": "A software utility",
            "topics": [],
        }
        plan = subject.plan_repository(repo, PlanningClient(contract=valid_contract()))
        self.assertEqual(plan.action, "readme_repair")
        self.assertEqual(set(plan.files), {subject.README_PATH})
        self.assertIsNone(plan.exception_code)

    def test_existing_valid_repository_remains_unchanged(self):
        contract = valid_contract()
        view = subject.validate_progress(contract)
        current = subject.desired_readme(b"# Project\n", view)
        repo = {
            "full_name": "owner/repo",
            "private": False,
            "default_branch": "main",
            "description": "A software utility",
            "topics": [],
        }
        plan = subject.plan_repository(
            repo,
            PlanningClient(contract=contract, readme=current),
        )
        self.assertEqual(plan.action, "unchanged")
        self.assertEqual(plan.files, {})

    def test_contradictory_evidence_never_resolves_automatically(self):
        repo = {
            "full_name": "owner/repo",
            "private": False,
            "default_branch": "main",
            "description": "Documentation",
            "topics": [],
        }
        readme = (
            b"# Completion\n"
            b"Drafting: 3 of 4 complete\n"
            b"Drafting: 4 of 4 complete\n"
        )
        plan = subject.plan_repository(
            repo,
            PlanningClient(contract=None, readme=readme, paths=["README.md"]),
        )
        self.assertEqual(plan.action, "exception")
        self.assertEqual(plan.exception_code, "contradictory_evidence")
        self.assertEqual(plan.files, {})


if __name__ == "__main__":
    unittest.main()
