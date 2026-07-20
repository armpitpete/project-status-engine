import base64
import json
from pathlib import Path
import sys
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


class AuthorityExceptionTests(unittest.TestCase):
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

    def test_queue_is_deterministic_and_summary_keeps_all_codes(self):
        projects = [
            {
                "name": "zeta",
                "full_name": "owner/zeta",
                "private": True,
                "url": "https://example.test/zeta",
                "authority_exception": subject.validate_exception(
                    document(code="no_completion_evidence", source_sha="b" * 40)
                ),
            },
            {
                "name": "alpha",
                "full_name": "owner/alpha",
                "private": False,
                "url": "https://example.test/alpha",
                "authority_exception": subject.validate_exception(
                    document(code="ambiguous_project_type", source_sha="c" * 40)
                ),
            },
        ]
        queue = subject.queue_for(projects)
        self.assertEqual(
            [item["full_name"] for item in queue],
            ["owner/alpha", "owner/zeta"],
        )
        summary = subject.summary_for(queue)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(tuple(summary["counts"]), subject.PRIMARY_CODES)
        self.assertEqual(summary["counts"]["ambiguous_project_type"], 1)
        self.assertEqual(summary["counts"]["no_completion_evidence"], 1)

    def test_owner_renderers_include_queue_identity(self):
        data = {
            "authority_exception_queue": [
                {
                    "full_name": "owner/private-project",
                    "url": "https://example.test/private-project",
                    "code": "no_completion_evidence",
                    "detail": "Needs an explicit bounded authority record.",
                }
            ]
        }
        self.assertIn("owner/private-project", subject.render_markdown(data))
        self.assertIn("no_completion_evidence", subject.render_html(data))


if __name__ == "__main__":
    unittest.main()
