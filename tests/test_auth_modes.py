import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from bb_pr_export.cli import main
from bb_pr_export.http import auth_headers
from tests.test_http import FakeResponse


TARGETS = (
    ("cloud", "https://bitbucket.org/workspace/repo/pull-requests/42"),
    ("server", "https://example.com/projects/PROJ/repos/repo/pull-requests/42"),
)


class AuthModeTests(unittest.TestCase):
    def test_no_token_produces_no_auth_even_with_username(self):
        self.assertEqual(auth_headers(None, "ignored"), {})
        self.assertEqual(auth_headers("token"), {"Authorization": "Bearer token"})
        encoded = base64.b64encode(b"user:token").decode("ascii")
        self.assertEqual(auth_headers("token", "user"), {"Authorization": f"Basic {encoded}"})

    def test_egress_requests_are_gets_without_auth_including_pagination(self):
        for provider, url in TARGETS:
            for credentials in (False, True):
                with self.subTest(provider=provider, credentials=credentials), tempfile.TemporaryDirectory() as directory:
                    config = Path(directory) / "config.toml"
                    config.write_text('[server]\nusername="config-user"\n', encoding="utf-8")
                    output = Path(directory) / "review.json"
                    environment = {"BB_TOKEN": "env-secret", "BB_USERNAME": "env-user"} if credentials else {}
                    flags = ["--token", "flag-secret"] if credentials else []
                    if credentials and provider == "server":
                        flags.extend(["--username", "flag-user"])
                    pages = (
                        [{"values": [], "next": "https://api.bitbucket.org/2.0/next"}, {"values": []}]
                        if provider == "cloud" else
                        [{"values": [], "isLastPage": False, "nextPageStart": 100},
                         {"values": [], "isLastPage": True}]
                    )
                    with patch.dict(os.environ, environment, clear=True), patch(
                        "urllib.request.OpenerDirector.open",
                        side_effect=[FakeResponse({"id": 42}), *map(FakeResponse, pages)],
                    ) as transport, contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(main([
                            provider, "--url", url, "--config", str(config), "--format", "json",
                            "--output", str(output), "--auth-mode", "egress", *flags,
                        ]), 0)
                    self.assertEqual(transport.call_count, 3)
                    for call in transport.call_args_list:
                        request = call.args[0]
                        self.assertEqual(request.get_method(), "GET")
                        self.assertFalse(any(name.lower() == "authorization" for name, _ in request.header_items()))
                    self.assertEqual(json.loads(output.read_text())["pr"]["id"], 42)

    def test_egress_auth_failure_has_no_fallback(self):
        for provider, url in TARGETS:
            for status in (401, 403):
                with self.subTest(provider=provider, status=status), tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "review.json"
                    errors = io.StringIO()
                    failure = urllib.error.HTTPError(url, status, "Denied", None, io.BytesIO(b"{}"))
                    with patch.dict(os.environ, {"BB_TOKEN": "secret", "BB_USERNAME": "user"}, clear=True), patch(
                        "bb_pr_export.cli.DEFAULT_CONFIG_PATHS", ()
                    ), patch("urllib.request.OpenerDirector.open", side_effect=failure) as transport:
                        with contextlib.redirect_stderr(errors):
                            self.assertEqual(main([
                                provider, "--url", url, "--output", str(output), "--auth-mode", "egress"
                            ]), 1)
                    self.assertEqual(transport.call_count, 1)
                    self.assertIsNone(transport.call_args.args[0].get_header("Authorization"))
                    self.assertIn("egress access rules and credential injection", errors.getvalue())
                    self.assertNotIn("secret", errors.getvalue())
                    self.assertFalse(output.exists())

    def test_cli_default_token_and_explicit_token_modes_keep_authentication(self):
        for provider, url in TARGETS:
            for explicit in (False, True):
                with self.subTest(provider=provider, explicit=explicit), tempfile.TemporaryDirectory() as directory:
                    username = ["--username", "user"] if provider == "server" else []
                    flags = ["--auth-mode", "token"] if explicit else []
                    page = {"values": [], "isLastPage": True}
                    with patch.dict(os.environ, {"BB_TOKEN": "token"}, clear=True), patch(
                        "bb_pr_export.cli.DEFAULT_CONFIG_PATHS", ()
                    ), patch("urllib.request.OpenerDirector.open", side_effect=[
                        FakeResponse({"id": 42}), FakeResponse(page)
                    ]) as transport, contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(main([
                            provider, "--url", url, "--output", str(Path(directory) / "review.json"),
                            *username, *flags,
                        ]), 0)
                    expected = auth_headers("token", "user" if provider == "server" else None)["Authorization"]
                    for call in transport.call_args_list:
                        self.assertEqual(call.args[0].get_header("Authorization"), expected)
