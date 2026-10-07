import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "validate_generated_outputs", SCRIPTS / "validate_generated_outputs.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)


class RuntimeVisibilityContractTests(unittest.TestCase):
    def test_public_and_private_runtime_flags_are_valid(self):
        subject.validate_runtime_visibility({"private": False})
        subject.validate_runtime_visibility({"private": True})

    def test_private_identity_prefix_is_not_a_leak(self):
        self.assertFalse(
            subject.contains_repository_identity(
                "Public repo: armpitpete/threadkeeper-core",
                "armpitpete/threadkeeper",
            )
        )
        self.assertFalse(
            subject.contains_repository_identity(
                "https://github.com/armpitpete/threadkeeper-core",
                "https://github.com/armpitpete/threadkeeper",
            )
        )

    def test_exact_private_identity_and_private_url_path_are_leaks(self):
        self.assertTrue(
            subject.contains_repository_identity(
                "See armpitpete/threadkeeper.",
                "armpitpete/threadkeeper",
            )
        )
        self.assertTrue(
            subject.contains_repository_identity(
                "https://github.com/armpitpete/threadkeeper/issues/1",
                "https://github.com/armpitpete/threadkeeper",
            )
        )

    def test_missing_or_non_boolean_flag_is_rejected(self):
        for value in (None, "true", 1, 0):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    subject.ValidationError,
                    "runtime repository privacy flag is invalid",
                ):
                    subject.validate_runtime_visibility({"private": value})


if __name__ == "__main__":
    unittest.main()
