import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import authority_exceptions as subject


def document(**overrides):
    value = {
        "schema_version": 2,
        "status": "requires_authority",
        "source_sha": "a" * 40,
        "project_type": "software",
        "code": "no_completion_evidence",
        "registry": "config/portfolio-authority-registry.json",
        "detail": "No explicit completed-and-total evidence was found.",
        "accepted_evidence": "An authority document must state completed and total counts.",
    }
    value.update(overrides)
    return value


def payload(value):
    raw = json.dumps(value).encode("utf-8")
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(raw).decode("ascii"),
    }


def project(name, code, sha):
    return {
        "name": name,
        "full_name": f"owner/{name}",
        "private": name.startswith("private"),
        "url": f"https://example.test/{name}",
        "authority_exception": subject.validate_exception(
            document(code=code, source_sha=sha)
        ),
    }


class AuthorityExceptionTests(unittest.TestCase):
    def test_resolution_registry_covers_exact_primary_taxonomy(self):
        self.assertEqual(tuple(subject.RESOLUTION_LANES), subject.PRIMARY_CODES)
        for code, policy in subject.RESOLUTION_LANES.items():
            self.assertTrue(policy["resolution_lane"])
            self.assertIsInstance(policy["owner_decision_required"], bool)
            self.assertTrue(policy["required_action"])
            self.assertTrue(policy["template_kind"])
            self.assertIn(code, subject.PRIMARY_CODE_SET)

    def test_rejects_incomplete_resolution_registry(self):
        registry = json.loads(subject.RESOLUTION_REGISTRY_PATH.read_text(encoding="utf-8"))
        registry["lanes"].pop("contradictory_evidence")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "registry.json"
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(subject.AuthorityExceptionError, "all primary codes"):
                subject.load_resolution_registry(path)

    def test_validates_registered_primary_exception(self):
        result = subject.validate_exception(document())
        self.assertEqual(result["code"], "no_completion_evidence")
        self.assertEqual(result["source_branch"], subject.EXCEPTION_BRANCH)
        self.assertEqual(result["source_path"], subject.EXCEPTION_PATH)

    def test_rejects_unregistered_code_and_invalid_sha(self):
        with self.assertRaisesRegex(subject.AuthorityExceptionError, "registered primary"):
            subject.validate_exception(document(code="insufficient_authority"))
        with self.assertRaisesRegex(subject.AuthorityExceptionError, "40-character"):
            subject.validate_exception(document(source_sha="not-a-sha"))

    def test_fetch_uses_exception_branch_and_treats_404_as_absent(self):
        calls = []

        def getter(path, query):
            calls.append((path, query))
            return payload(document())

        result, error = subject.fetch_repository_exception("owner/repo", getter)
        self.assertIsNone(error)
        self.assertEqual(result["code"], "no_completion_evidence")
        self.assertEqual(
            calls,
            [
                (
                    "/repos/owner/repo/contents/.project/bootstrap-exception.json",
                    {"ref": "automation/project-status-bootstrap-exception"},
                )
            ],
        )

        def missing(path, query):
            raise RuntimeError("GitHub API error 404: Not Found")

        result, error = subject.fetch_repository_exception("owner/repo", missing)
        self.assertIsNone(result)
        self.assertIsNone(error)

    def test_queue_is_deterministic_and_routes_every_code(self):
        projects = [
            project("zeta", "no_completion_evidence", "b" * 40),
            project("alpha", "ambiguous_project_type", "c" * 40),
        ]
        queue = subject.queue_for(projects)
        self.assertEqual(
            [item["full_name"] for item in queue],
            ["owner/alpha", "owner/zeta"],
        )
        alpha = queue[0]
        self.assertEqual(alpha["resolution_lane"], "project_type_decision")
        self.assertTrue(alpha["owner_decision_required"])
        self.assertIn("Select one authoritative project type", alpha["required_action"])

        summary = subject.summary_for(queue)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["owner_decision_required"], 2)
        self.assertEqual(tuple(summary["counts"]), subject.PRIMARY_CODES)
        self.assertEqual(summary["counts"]["ambiguous_project_type"], 1)
        self.assertEqual(summary["counts"]["no_completion_evidence"], 1)
        self.assertEqual(summary["lane_counts"]["project_type_decision"], 1)
        self.assertEqual(summary["lane_counts"]["bounded_evidence_authoring"], 1)

    def test_automated_contract_lane_is_not_counted_as_owner_decision(self):
        queue = subject.queue_for(
            [project("repairable", "missing_completion_contract", "d" * 40)]
        )
        self.assertFalse(queue[0]["owner_decision_required"])
        self.assertEqual(queue[0]["resolution_lane"], "completion_contract_repair")
        summary = subject.summary_for(queue)
        self.assertEqual(summary["owner_decision_required"], 0)

    def test_owner_renderers_include_lane_and_required_action(self):
        queue = subject.queue_for(
            [project("private-project", "no_completion_evidence", "e" * 40)]
        )
        data = {"authority_exception_queue": queue}
        markdown = subject.render_markdown(data)
        html = subject.render_html(data)
        self.assertIn("owner/private-project", markdown)
        self.assertIn("bounded_evidence_authoring", markdown)
        self.assertIn("Add explicit completed and total counts", html)

    def test_templates_use_placeholders_and_never_invent_completion_values(self):
        codes = [
            "missing_authoritative_source",
            "no_completion_evidence",
            "ambiguous_project_type",
            "contradictory_evidence",
            "inactive_repository_candidate",
            "missing_readme_marker",
            "missing_completion_contract",
        ]
        queue = subject.queue_for(
            [project(f"repo-{index}", code, f"{index + 1:x}" * 40) for index, code in enumerate(codes)]
        )
        rendered = subject.render_resolution_templates(
            {"authority_exception_queue": queue}
        )
        self.assertIn("[completed] of [total] complete", rendered)
        self.assertIn("Project type: manuscript | website | software", rendered)
        self.assertIn("Decision: active | archive | excluded", rendered)
        self.assertIn("Human-written bytes to preserve", rendered)
        self.assertNotIn("100% complete", rendered)
        self.assertNotIn("0% complete", rendered)


if __name__ == "__main__":
    unittest.main()
