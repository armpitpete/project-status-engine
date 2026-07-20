import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verify_private_access as access


class PrivateAccessVerificationTests(unittest.TestCase):
    def test_access_boundary_accepts_authentication_blocks(self):
        url = "https://command.vaelinya.uk/private/project-status-engine/"
        self.assertTrue(access.access_is_blocked(401, "", url))
        self.assertTrue(access.access_is_blocked(403, "", url))
        self.assertTrue(
            access.access_is_blocked(
                302,
                "https://vaelinya.cloudflareaccess.com/cdn-cgi/access/login",
                url,
            )
        )

    def test_access_boundary_rejects_anonymous_or_same_origin_access(self):
        url = "https://command.vaelinya.uk/private/project-status-engine/"
        self.assertFalse(access.access_is_blocked(200, "", url))
        self.assertFalse(
            access.access_is_blocked(
                302,
                "https://command.vaelinya.uk/private/project-status-engine/index.html",
                url,
            )
        )
        self.assertFalse(access.access_is_blocked(302, "", url))


class PrivateDeploymentScriptTests(unittest.TestCase):
    def _write_executable(self, path: Path, body: str) -> None:
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        private = root / "private-build"
        private.mkdir()
        for name in (
            "index.html",
            "status.json",
            "project-status.md",
            "completion-status.md",
            "authority-exceptions.md",
            "authority-resolution-templates.md",
        ):
            content = '{"view": "private"}\n' if name == "status.json" else f"{name}\n"
            (private / name).write_text(content, encoding="utf-8")
        key = root / "id_ed25519"
        key.write_text("test-key\n", encoding="utf-8")
        known_hosts = root / "known_hosts"
        known_hosts.write_text("server.vaelinya.uk ssh-ed25519 AAAATEST\n", encoding="utf-8")
        log = root / "commands.log"
        fake_bin = root / "bin"
        fake_bin.mkdir()
        self._write_executable(
            fake_bin / "ssh",
            """
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'ssh' >> "$COMMAND_LOG"
            printf ' <%s>' "$@" >> "$COMMAND_LOG"
            printf '\n' >> "$COMMAND_LOG"
            """,
        )
        self._write_executable(
            fake_bin / "rsync",
            """
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'rsync' >> "$COMMAND_LOG"
            printf ' <%s>' "$@" >> "$COMMAND_LOG"
            printf '\n' >> "$COMMAND_LOG"
            printf 'RSYNC_RSH=<%s>\n' "$RSYNC_RSH" >> "$COMMAND_LOG"
            """,
        )
        return private, key, known_hosts, log

    def _environment(
        self,
        private: Path,
        key: Path,
        known_hosts: Path,
        log: Path,
        fake_bin: Path,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
                "COMMAND_LOG": str(log),
                "PRIVATE_STATUS_DEPLOY_HOST": "server.vaelinya.uk",
                "PRIVATE_STATUS_DEPLOY_USER": "vaelinya",
                "PRIVATE_STATUS_DEPLOY_TARGET": "/home/vaelinya/public_html/private/project-status-engine/",
                "PRIVATE_STATUS_SOURCE_DIR": str(private),
                "PRIVATE_STATUS_SSH_KEY_FILE": str(key),
                "PRIVATE_STATUS_KNOWN_HOSTS_FILE": str(known_hosts),
            }
        )
        return env

    def test_script_uses_pinned_host_exact_target_and_delete_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private, key, known_hosts, log = self._fixture(root)
            env = self._environment(private, key, known_hosts, log, root / "bin")
            result = subprocess.run(
                ["bash", str(SCRIPTS / "deploy_private_status.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log.read_text(encoding="utf-8")
            self.assertIn("StrictHostKeyChecking=yes", commands)
            self.assertIn(f"UserKnownHostsFile={known_hosts}", commands)
            self.assertIn("BatchMode=yes", commands)
            self.assertIn("IdentitiesOnly=yes", commands)
            self.assertIn("rsync <--archive> <--compress> <--delete>", commands)
            self.assertIn(
                "<vaelinya@server.vaelinya.uk:/home/vaelinya/public_html/private/project-status-engine/>",
                commands,
            )
            self.assertIn(f"<{private}/>", commands)
            self.assertIn("RSYNC_RSH=<ssh -i", commands)
            self.assertIn("Private project-status dashboard deployed", result.stdout)

    def test_script_refuses_unexpected_target_before_remote_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private, key, known_hosts, log = self._fixture(root)
            env = self._environment(private, key, known_hosts, log, root / "bin")
            env["PRIVATE_STATUS_DEPLOY_TARGET"] = "/tmp/unsafe/"
            result = subprocess.run(
                ["bash", str(SCRIPTS / "deploy_private_status.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing unexpected deployment target", result.stderr)
            self.assertFalse(log.exists())

    def test_script_requires_all_private_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private, key, known_hosts, log = self._fixture(root)
            (private / "authority-resolution-templates.md").unlink()
            env = self._environment(private, key, known_hosts, log, root / "bin")
            result = subprocess.run(
                ["bash", str(SCRIPTS / "deploy_private_status.sh")],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing required file", result.stderr)
            self.assertFalse(log.exists())


class PrivateDeploymentWorkflowTests(unittest.TestCase):
    def test_workflow_keeps_private_deployment_gated_and_non_artifact(self):
        workflow = (ROOT / ".github" / "workflows" / "status.yml").read_text(
            encoding="utf-8"
        )
        gate = (
            "github.event_name != 'pull_request' && "
            "vars.PRIVATE_STATUS_DEPLOY_ENABLED == 'true'"
        )
        self.assertGreaterEqual(workflow.count(gate), 3)
        self.assertIn("PRIVATE_STATUS_DEPLOY_KEY", workflow)
        self.assertIn("PRIVATE_STATUS_KNOWN_HOSTS", workflow)
        self.assertIn("server.vaelinya.uk", workflow)
        self.assertIn("/home/vaelinya/public_html/private/project-status-engine/", workflow)
        self.assertIn("bash scripts/deploy_private_status.sh", workflow)
        self.assertIn("python scripts/verify_private_access.py", workflow)
        self.assertIn("path: public", workflow)
        self.assertNotIn("path: private-build", workflow)
        self.assertNotIn("upload-artifact", workflow)

    def test_deployment_script_never_disables_host_checking_or_uses_passwords(self):
        script = (SCRIPTS / "deploy_private_status.sh").read_text(encoding="utf-8")
        self.assertIn("StrictHostKeyChecking=yes", script)
        self.assertIn("UserKnownHostsFile=", script)
        self.assertIn("BatchMode=yes", script)
        self.assertIn("--delete", script)
        self.assertNotIn("StrictHostKeyChecking=no", script)
        self.assertNotIn("sshpass", script)
        self.assertNotIn("password", script.lower())


if __name__ == "__main__":
    unittest.main()
