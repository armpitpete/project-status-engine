import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "real_thing_status.py"
SPEC = importlib.util.spec_from_file_location("real_thing_status", MODULE_PATH)
status = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(status)


def record(*, claimed="complete", verified="complete", human_required=True):
    environments = {
        "designed": "authoritative-design-contract",
        "implemented": "exact-repository-state",
        "automated-checks": "exact-head-workflow",
        "independent-review": "exact-head-independent-review",
        "merged": "default-branch-exact-commit",
        "deployed": "exact-private-dashboard-release",
        "live-behaviour": "live-private-dashboard",
        "human-acceptance": "owner-dashboard-acceptance",
    }
    stages = []
    for stage_name in status.STAGES:
        required = human_required or stage_name != "human-acceptance"
        if required:
            environment = environments[stage_name]
            stages.append(
                {
                    "stage": stage_name,
                    "required": True,
                    "required_environment": environment,
                    "rationale": None,
                    "result": "PASS",
                    "relationship": "direct",
                    "observed_environment": environment,
                    "evidence": [f"evidence://{stage_name}"],
                    "limitations": [],
                }
            )
        else:
            stages.append(
                {
                    "stage": stage_name,
                    "required": False,
                    "required_environment": None,
                    "rationale": "No subjective acceptance is required for this bounded claim.",
                    "result": "NOT_APPLICABLE",
                    "relationship": "not-applicable",
                    "observed_environment": None,
                    "evidence": [],
                    "limitations": [],
                }
            )
    return {
        "claimed": claimed,
        "verified": verified,
        "authority": "docs/STATUS_AUTHORITY.md",
        "stages": stages,
        "limitations": [],
    }


class RealThingStatusTests(unittest.TestCase):
    def test_complete_requires_direct_passes_for_all_required_stages(self):
        result = status.validate_status(record())
        self.assertEqual(result["verified"], "complete")

    def test_proxy_cannot_pass_live_behaviour(self):
        value = record()
        live = next(stage for stage in value["stages"] if stage["stage"] == "live-behaviour")
        live["relationship"] = "proxy"
        live["observed_environment"] = "generated-html-fixture"
        with self.assertRaisesRegex(status.StatusValidationError, "proxy evidence cannot pass"):
            status.validate_status(value)

    def test_proxy_failure_is_insufficient_not_failure_of_real_environment(self):
        value = record(verified="insufficient")
        live = next(stage for stage in value["stages"] if stage["stage"] == "live-behaviour")
        live.update(
            {
                "result": "FAIL",
                "relationship": "proxy",
                "observed_environment": "generated-html-fixture",
                "evidence": ["evidence://fixture-failure"],
            }
        )
        with self.assertRaisesRegex(status.StatusValidationError, "proxy failure is INSUFFICIENT"):
            status.validate_status(value)

    def test_missing_deployment_makes_complete_claim_insufficient(self):
        value = record(verified="insufficient")
        deployed = next(stage for stage in value["stages"] if stage["stage"] == "deployed")
        deployed.update(
            {
                "result": "INSUFFICIENT",
                "relationship": "missing",
                "observed_environment": None,
                "evidence": [],
                "limitations": ["No exact deployment receipt exists."],
            }
        )
        result = status.validate_status(value)
        self.assertEqual(result["verified"], "insufficient")

    def test_missing_human_acceptance_makes_complete_claim_insufficient(self):
        value = record(verified="insufficient")
        human = next(stage for stage in value["stages"] if stage["stage"] == "human-acceptance")
        human.update(
            {
                "result": "INSUFFICIENT",
                "relationship": "missing",
                "observed_environment": None,
                "evidence": [],
                "limitations": ["Owner acceptance has not occurred."],
            }
        )
        status.validate_status(value)

    def test_implemented_claim_can_pass_while_later_stages_are_open(self):
        value = record(claimed="implemented", verified="implemented")
        for stage in value["stages"]:
            if status.STAGES.index(stage["stage"]) > status.STAGES.index("implemented"):
                stage.update(
                    {
                        "result": "INSUFFICIENT",
                        "relationship": "missing",
                        "observed_environment": None,
                        "evidence": [],
                        "limitations": ["Later stage remains open."],
                    }
                )
        result = status.validate_status(value)
        self.assertEqual(result["verified"], "implemented")

    def test_wrong_environment_cannot_pass(self):
        value = record()
        deployed = next(stage for stage in value["stages"] if stage["stage"] == "deployed")
        deployed["observed_environment"] = "local-preview"
        with self.assertRaisesRegex(status.StatusValidationError, "required environment"):
            status.validate_status(value)

    def test_not_applicable_requires_rationale(self):
        value = record(human_required=False)
        human = next(stage for stage in value["stages"] if stage["stage"] == "human-acceptance")
        human["rationale"] = None
        with self.assertRaisesRegex(status.StatusValidationError, "requires a rationale"):
            status.validate_status(value)

    def test_every_stage_cannot_be_not_applicable(self):
        value = record(verified="insufficient")
        for stage in value["stages"]:
            stage.update(
                {
                    "required": False,
                    "required_environment": None,
                    "rationale": "Declared not applicable.",
                    "result": "NOT_APPLICABLE",
                    "relationship": "not-applicable",
                    "observed_environment": None,
                    "evidence": [],
                }
            )
        with self.assertRaisesRegex(status.StatusValidationError, "at least one stage"):
            status.validate_status(value)


if __name__ == "__main__":
    unittest.main()
