import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "completion_status.py"
SPEC = importlib.util.spec_from_file_location("completion_status_guard", MODULE_PATH)
completion = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(completion)


class ProgressIsNotCompletionTests(unittest.TestCase):
    def test_full_numeric_count_is_count_complete_not_complete(self):
        result = completion.validate_progress(
            {
                "schema_version": 1,
                "authority": "docs/AUTHORITY.md",
                "stages": [
                    {
                        "id": "implementation",
                        "label": "Implementation tasks",
                        "completed": 3,
                        "total": 3,
                    }
                ],
            }
        )
        self.assertEqual(result["stages"][0]["state"], "count_complete")
        self.assertTrue(result["progress_only"])
        self.assertEqual(result["completion_claim"], "not_declared")

    def test_rendered_progress_disclaims_lifecycle_completion(self):
        completion_record = completion.validate_progress(
            {
                "schema_version": 1,
                "authority": "docs/AUTHORITY.md",
                "stages": [
                    {
                        "id": "implementation",
                        "label": "Implementation tasks",
                        "completed": 3,
                        "total": 3,
                    }
                ],
            }
        )
        data = {
            "view": "private",
            "projects": [
                {
                    "full_name": "owner/example",
                    "private": True,
                    "completion": completion_record,
                }
            ],
        }
        output = completion.render_markdown(data)
        self.assertIn("progress is not lifecycle completion", output)
        self.assertIn("count_complete", output)
        self.assertNotIn("| Valid |", output)


if __name__ == "__main__":
    unittest.main()
