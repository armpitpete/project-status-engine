import base64
import importlib.util
import json
import math
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "completion_status.py"
SPEC = importlib.util.spec_from_file_location("completion_status", MODULE_PATH)
completion = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(completion)


def document(*, overall=True):
    return {
        "schema_version": 1,
        "authority": "docs/PROJECT_AUTHORITY.md",
        "project_type": "manuscript",
        "stages": [
            {"id": "drafting", "label": "Drafting", "completed": 36, "total": 36, "weight": 25},
            {"id": "editing", "label": "Editing", "completed": 18, "total": 36, "weight": 50},
            {"id": "preflight", "label": "Print preflight", "completed": 0, "total": 1, "weight": 25},
        ],
        "overall": {"enabled": overall},
    }


class ValidationTests(unittest.TestCase):
    def test_stage_and_weighted_overall_percentages_are_deterministic(self):
        result = completion.validate_progress(document())
        self.assertEqual(
            [stage["percentage"] for stage in result["stages"]],
            [100.0, 50.0, 0.0],
        )
        self.assertEqual(result["overall_percentage"], 50.0)
        self.assertEqual(result["authority"], "docs/PROJECT_AUTHORITY.md")

    def test_overall_is_absent_unless_explicitly_enabled(self):
        result = completion.validate_progress(document(overall=False))
        self.assertFalse(result["overall_enabled"])
        self.assertIsNone(result["overall_percentage"])

    def test_completed_cannot_exceed_total(self):
        value = document()
        value["stages"][0]["completed"] = 37
        with self.assertRaisesRegex(
            completion.ProgressValidationError, "must not exceed total"
        ):
            completion.validate_progress(value)

    def test_enabled_overall_requires_weights_totaling_100(self):
        value = document()
        value["stages"][0]["weight"] = 20
        with self.assertRaisesRegex(
            completion.ProgressValidationError, "weights must total 100"
        ):
            completion.validate_progress(value)

    def test_authority_is_required(self):
        value = document()
        del value["authority"]
        with self.assertRaisesRegex(completion.ProgressValidationError, "authority"):
            completion.validate_progress(value)

    def test_unknown_fields_are_rejected_to_match_published_schema(self):
        value = document()
        value["guessed_readiness"] = "print-ready"
        with self.assertRaisesRegex(
            completion.ProgressValidationError, "unknown fields"
        ):
            completion.validate_progress(value)

        stage_value = document()
        stage_value["stages"][0]["status"] = "done"
        with self.assertRaisesRegex(
            completion.ProgressValidationError, "unknown fields"
        ):
            completion.validate_progress(stage_value)

    def test_weights_must_be_finite(self):
        value = document()
        value["stages"][0]["weight"] = math.nan
        with self.assertRaisesRegex(completion.ProgressValidationError, "finite"):
            completion.validate_progress(value)


class FetchTests(unittest.TestCase):
    def test_decodes_github_contents_payload(self):
        raw = json.dumps(document()).encode("utf-8")
        payload = {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        }
        result = completion.validate_progress(
            completion.decode_contents_payload(payload)
        )
        self.assertEqual(result["state"], "valid")

    def test_missing_file_is_not_configured_not_an_error(self):
        def getter(path, query):
            raise RuntimeError("GitHub API error 404: Not Found")

        result, error = completion.fetch_repository_progress("owner/repo", getter)
        self.assertEqual(result["state"], "not_configured")
        self.assertIsNone(error)

    def test_invalid_document_is_reported(self):
        raw = json.dumps({"schema_version": 1}).encode("utf-8")
        payload = {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        }

        result, error = completion.fetch_repository_progress(
            "owner/repo", lambda path, query: payload
        )
        self.assertEqual(result["state"], "invalid")
        self.assertIn("invalid .project/progress.json", error)

    def test_non_standard_json_constants_are_rejected(self):
        raw = b'{"schema_version":1,"authority":"docs/A.md","stages":[],"weight":NaN}'
        payload = {
            "type": "file",
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        }
        with self.assertRaisesRegex(
            completion.ProgressValidationError, "non-standard JSON constant"
        ):
            completion.decode_contents_payload(payload)


class PrivacyAndRenderingTests(unittest.TestCase):
    def test_public_output_redacts_private_completion(self):
        projects = [
            {
                "full_name": "Private project #1",
                "private": True,
                "completion": completion.validate_progress(document()),
            }
        ]
        data = {"view": "public", "projects": projects}
        output = completion.render_html(data) + completion.render_markdown(data)
        self.assertIn("Redacted", output)
        self.assertNotIn("Drafting 36/36", output)
        self.assertNotIn("docs/PROJECT_AUTHORITY.md", output)

    def test_private_output_includes_stage_detail(self):
        projects = [
            {
                "full_name": "owner/private-project",
                "private": True,
                "completion": completion.validate_progress(document()),
            }
        ]
        data = {"view": "private", "projects": projects}
        output = completion.render_markdown(data)
        self.assertIn("50.0%", output)
        self.assertIn("Drafting 36/36", output)


if __name__ == "__main__":
    unittest.main()
