from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DOC = ROOT / "docs" / "PRIVATE_DASHBOARD_DEPLOYMENT.md"


class WindowsCredentialPreparationTests(unittest.TestCase):
    def setUp(self):
        self.script = (SCRIPTS / "prepare_private_deploy_credentials.ps1").read_text(
            encoding="utf-8"
        )

    def test_generates_only_a_dedicated_ed25519_key_and_refuses_silent_overwrite(self):
        self.assertIn('ssh-keygen', self.script)
        self.assertIn('-t ed25519', self.script)
        self.assertIn('-N ""', self.script)
        self.assertIn('project-status-engine-private-deploy-ed25519', self.script)
        self.assertIn('if ($existing.Count -gt 0 -and -not $Force)', self.script)
        self.assertIn('Re-run with -Force only after confirming', self.script)

    def test_does_not_print_or_copy_private_key_contents(self):
        self.assertIn('The private-key contents were not printed', self.script)
        self.assertNotIn('Get-Content -LiteralPath $keyPath', self.script)
        self.assertNotIn('Set-Clipboard', self.script)
        self.assertNotIn('gh secret set', self.script)

    def test_manifest_preserves_host_verification_and_enablement_boundaries(self):
        self.assertIn('PRIVATE_STATUS_DEPLOY_KEY', self.script)
        self.assertIn('PRIVATE_STATUS_KNOWN_HOSTS', self.script)
        self.assertIn('Verify the server SSH host fingerprint independently', self.script)
        self.assertIn('Do not enable PRIVATE_STATUS_DEPLOY_ENABLED', self.script)


class ServerProvisioningScriptTests(unittest.TestCase):
    def setUp(self):
        self.path = SCRIPTS / "provision_private_dashboard_target.sh"
        self.script = self.path.read_text(encoding="utf-8")

    def test_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(self.path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_refuses_any_unexpected_identity_or_target(self):
        self.assertIn('EXPECTED_HOST="server.vaelinya.uk"', self.script)
        self.assertIn('EXPECTED_USER="vaelinya"', self.script)
        self.assertIn('EXPECTED_HOME="/home/vaelinya"', self.script)
        self.assertIn('TARGET_PARENT="/home/vaelinya/public_html/private"', self.script)
        self.assertIn('TARGET_DIRECTORY="${TARGET_PARENT}/project-status-engine"', self.script)
        self.assertIn('[[ ${EUID} -ne 0 ]]', self.script)
        self.assertIn('[[ -d "$TARGET_PARENT" ]]', self.script)
        self.assertNotIn('mkdir -p "$TARGET_PARENT"', self.script)

    def test_installs_only_one_ed25519_key_with_restrictions(self):
        self.assertIn('exactly one non-empty line', self.script)
        self.assertIn('^ssh-ed25519', self.script)
        self.assertIn('no-agent-forwarding', self.script)
        self.assertIn('no-port-forwarding', self.script)
        self.assertIn('no-pty', self.script)
        self.assertIn('no-user-rc', self.script)
        self.assertIn('no-X11-forwarding', self.script)
        self.assertIn('chmod 0600', self.script)
        self.assertNotIn('ssh-rsa', self.script)

    def test_creates_exact_target_and_verifies_account_access(self):
        self.assertIn('install -d -o "$EXPECTED_USER"', self.script)
        self.assertIn('runuser -u "$EXPECTED_USER" -- test -w "$TARGET_DIRECTORY"', self.script)
        self.assertIn('runuser -u "$EXPECTED_USER" -- test -x "$TARGET_DIRECTORY"', self.script)
        self.assertNotIn('chmod 777', self.script)
        self.assertNotIn('chown -R', self.script)

    def test_host_key_output_requires_independent_verification(self):
        self.assertIn('/etc/ssh/ssh_host_ed25519_key.pub', self.script)
        self.assertIn('Candidate PRIVATE_STATUS_KNOWN_HOSTS line', self.script)
        self.assertIn('independent trusted channel', self.script)
        self.assertNotIn('ssh-keyscan', self.script)
        self.assertNotIn('StrictHostKeyChecking=no', self.script)


class ProvisioningDocumentationTests(unittest.TestCase):
    def test_documents_one_bounded_operator_path(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn('prepare_private_deploy_credentials.ps1', text)
        self.assertIn('provision_private_dashboard_target.sh', text)
        self.assertIn('PRIVATE_STATUS_DEPLOY_KEY', text)
        self.assertIn('PRIVATE_STATUS_KNOWN_HOSTS', text)
        self.assertIn('PRIVATE_STATUS_DEPLOY_ENABLED=true', text)
        self.assertIn('independent trusted channel', text)
        self.assertIn('Do not declare authenticated private delivery complete', text)


if __name__ == "__main__":
    unittest.main()
