import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "portfolio_forensic_audit", ROOT / "scripts" / "portfolio_forensic_audit.py"
)
subject = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)


def git(repository: Path, *arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return process.stdout.strip()


class PortfolioForensicAuditTests(unittest.TestCase):
    def test_secret_value_is_fingerprinted_not_returned(self):
        value = b"ghp_1234567890abcdefghijABCDEFGHIJ"
        findings = subject.scan_bytes(
            b"token=" + value,
            repository="armpitpete/example",
            surface="fixture",
            location="fixture.txt",
        )
        github = [finding for finding in findings if finding.detector == "github_token"]
        self.assertEqual(len(github), 1)
        serialised = json.dumps(github[0].as_dict())
        self.assertNotIn(value.decode("ascii"), serialised)
        self.assertEqual(github[0].fingerprint, subject.hashlib.sha256(value).hexdigest())

    def test_placeholder_assignment_is_ignored(self):
        findings = subject.scan_bytes(
            b'API_KEY="your-key-placeholder"',
            repository="armpitpete/example",
            surface="fixture",
            location="fixture.txt",
        )
        self.assertFalse(any(item.detector == "credential_assignment" for item in findings))

    def test_sensitive_paths_distinguish_examples(self):
        finding = subject.sensitive_path_finding(
            "armpitpete/example", "git_history", "config/.env"
        )
        self.assertIsNotNone(finding)
        self.assertIsNone(
            subject.sensitive_path_finding(
                "armpitpete/example", "git_history", "config/.env.example"
            )
        )

    def test_zip_members_are_scanned_after_decompression(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "artifact.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "logs/output.txt",
                    b"OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
                )
            findings, size, limitations = subject.scan_archive(
                archive_path,
                repository="armpitpete/example",
                surface="actions_artifact",
                location="artifact:1",
            )
        self.assertGreater(size, 0)
        self.assertEqual(limitations, [])
        self.assertTrue(any(item.detector == "openai_key" for item in findings))
        self.assertTrue(any("logs/output.txt" in item.location for item in findings))

    def test_git_history_includes_removed_secret_blob(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary) / "repository"
            repository.mkdir()
            git(repository, "init", "-b", "main")
            git(repository, "config", "user.name", "Test User")
            git(repository, "config", "user.email", "test@example.invalid")
            secret = "AIza12345678901234567890123456789012345"
            (repository / "config.txt").write_text(secret + "\n", encoding="utf-8")
            git(repository, "add", "config.txt")
            git(repository, "commit", "-m", "Add fixture")
            (repository / "config.txt").write_text("removed\n", encoding="utf-8")
            git(repository, "commit", "-am", "Remove fixture")

            report = subject.RepositoryReport(
                repository="armpitpete/example",
                visibility="private",
                archived=False,
            )
            subject.scan_git_history("armpitpete/example", repository, report)

        self.assertGreaterEqual(report.git_objects_scanned, 2)
        candidates = [item for item in report.findings if item.detector == "google_api_key"]
        self.assertEqual(len(candidates), 1)
        self.assertNotEqual(candidates[0].location, "")
        self.assertNotIn(secret, json.dumps(candidates[0].as_dict()))

    def test_report_keeps_known_platform_limitations_explicit(self):
        report = subject.RepositoryReport(
            repository="armpitpete/example",
            visibility="private",
            archived=False,
        )
        document = subject.build_report("armpitpete", [report])
        self.assertEqual(document["coverage"]["repositories"], 1)
        self.assertFalse(document["security_boundary"]["secret_values_in_report"])
        self.assertTrue(
            any("deleted unreachable branch refs" in item for item in document["limitations"])
        )


if __name__ == "__main__":
    unittest.main()
