from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_private_dashboard.sh"


class PrivateDeployContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_oracle_target_contract(self):
        self.assertIn("server.vaelinya.uk", self.text)
        self.assertIn("ORACLE_SSH_USER:-vaelinya", self.text)
        self.assertIn("/home/vaelinya/public_html/private/project-status-engine/", self.text)

    def test_rsync_is_mirroring_and_strict(self):
        self.assertIn("rsync", self.text)
        self.assertIn("--delete", self.text)
        self.assertIn("StrictHostKeyChecking=yes", self.text)
        self.assertNotIn("StrictHostKeyChecking=no", self.text)
        self.assertNotIn("sshpass", self.text.lower())

    def test_private_build_must_exist_before_deploy(self):
        self.assertIn('SOURCE_DIR="${PRIVATE_STATUS_OUT_DIR:-private-build}"', self.text)
        self.assertIn('"${SOURCE_DIR}/index.html"', self.text)
        self.assertIn('"${SOURCE_DIR}/status.json"', self.text)


if __name__ == "__main__":
    unittest.main()
