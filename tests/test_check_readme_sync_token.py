"""Dedicated README sync credential preflight never leaks tokens or API bodies."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_readme_sync_token as check


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class CredentialPreflightTests(unittest.TestCase):
    def test_missing_token_fails_without_network(self):
        self.assertEqual(
            check.check_token("", urlopen=lambda *_a, **_kw: self.fail("network called")),
            "missing",
        )

    def test_valid_token_uses_bearer_get_user_only(self):
        def fake_open(request, *, timeout):
            self.assertEqual(request.full_url, "https://api.github.com/user")
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(timeout, 15)
            return _Response()
        self.assertEqual(check.check_token("test-token", urlopen=fake_open), "accepted")

    def test_unauthorised_stays_sanitised(self):
        def fake_open(request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "private identity secret-token",
                {}, io.BytesIO(b"private body"),
            )
        self.assertEqual(check.check_token("secret-token", urlopen=fake_open), "unauthorized")

    def test_forbidden_is_distinct_from_unauthorised(self):
        def fake_open(request, *, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "denied", {}, None)
        self.assertEqual(check.check_token("secret-token", urlopen=fake_open), "forbidden")

    def test_network_error_fails_closed(self):
        def fake_open(_request, *, timeout):
            raise urllib.error.URLError("secret-token")
        self.assertEqual(check.check_token("secret-token", urlopen=fake_open), "api_unavailable")

    def test_main_only_prints_fixed_status(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"README_SYNC_TOKEN": "secret-token"}):
            with patch.object(check, "check_token", return_value="unauthorized"):
                with contextlib.redirect_stdout(output):
                    result = check.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), '{"credential_preflight":"unauthorized"}\n')
        self.assertNotIn("secret-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
