import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import portfolio_bootstrap as subject


class PortfolioBootstrapTokenBoundaryTests(unittest.TestCase):
    def test_inventory_union_prefers_authenticated_metadata(self):
        public = [
            {"full_name": "owner/public", "source": "public"},
            {"full_name": "owner/shared", "source": "public"},
        ]
        authenticated = [
            {"full_name": "owner/private", "source": "authenticated"},
            {"full_name": "owner/shared", "source": "authenticated"},
        ]
        merged = subject.merge_repository_inventories(authenticated, public)
        self.assertEqual(
            [repository["full_name"] for repository in merged],
            ["owner/private", "owner/public", "owner/shared"],
        )
        shared = next(item for item in merged if item["full_name"] == "owner/shared")
        self.assertEqual(shared["source"], "authenticated")

    def test_report_records_inventory_sources_without_identities(self):
        report = subject.aggregate_run_report(
            "apply",
            21,
            [subject.Result("a" * 64, "failure", "repository_inventory_below_minimum")],
            "failed",
            inventory_sources={"authenticated": 21, "public": 18, "union": 21},
            minimum_inventory=49,
        ).decode("utf-8")
        self.assertIn('"minimum_inventory": 49', report)
        self.assertIn('"authenticated": 21', report)
        self.assertIn('"public": 18', report)
        self.assertIn('"union": 21', report)
        self.assertNotIn("owner/", report)
        self.assertNotIn("a" * 64, report)

    def test_exception_plan_uses_primary_code_in_branch_report(self):
        calls = []

        class Client:
            def upsert_exception_report(self, *args):
                calls.append(args)

        plan = subject.RepositoryPlan(
            "owner/repo",
            True,
            "main",
            "abc123",
            "manuscript",
            "exception",
            {},
            "no_completion_evidence",
            "No bounded count.",
        )
        result = subject.apply_plan(plan, Client(), apply=True)
        self.assertEqual(result.action, "exception")
        self.assertEqual(
            calls,
            [
                (
                    "owner/repo",
                    "abc123",
                    "manuscript",
                    "no_completion_evidence",
                    "No bounded count.",
                )
            ],
        )

    def test_unchanged_plan_clears_exception_branch(self):
        calls = []

        class Client:
            def clear_exception_report(self, full_name):
                calls.append(full_name)

        plan = subject.RepositoryPlan(
            "owner/repo", False, "main", "abc123", "software", "unchanged", {}
        )
        result = subject.apply_plan(plan, Client(), apply=True)
        self.assertEqual(result.action, "unchanged")
        self.assertEqual(calls, ["owner/repo"])

    def test_inventory_below_minimum_fails_before_planning(self):
        class Client:
            inventory_counts = {"authenticated": 1, "public": 1, "union": 1}

            def repositories(self):
                return [
                    {
                        "full_name": "armpitpete/only",
                        "owner": {"login": "armpitpete"},
                        "default_branch": "main",
                        "archived": False,
                        "fork": False,
                        "disabled": False,
                    }
                ]

        previous = subject.MINIMUM_ACTIVE_REPOSITORIES
        subject.MINIMUM_ACTIVE_REPOSITORIES = 2
        try:
            with self.assertRaisesRegex(
                subject.BootstrapClosed, "repository_inventory_below_minimum"
            ):
                subject.run(Client(), apply=False)
        finally:
            subject.MINIMUM_ACTIVE_REPOSITORIES = previous


if __name__ == "__main__":
    unittest.main()
