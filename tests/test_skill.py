import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from bb_pr_export.http import AuthError, NetworkError
from tools.build_skill import ROOT, SKILL_NAME, build_bundle


def load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "skill_export_pr", ROOT / "skills" / SKILL_NAME / "scripts" / "export_pr.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wrapper = load_wrapper()
CLOUD_URL = "https://bitbucket.org/workspace/repo/pull-requests/42"
SERVER_URL = "https://example.com/bitbucket/projects/PROJ/repos/repo/pull-requests/42/overview"
EXPORT = {"provider": "cloud", "pr": {"id": 42}, "reviewers": [], "comments": []}


class SkillWrapperTests(unittest.TestCase):
    def test_selects_provider_and_forces_json(self):
        for url, provider in ((CLOUD_URL, "cloud"), (SERVER_URL, "server")):
            with self.subTest(url=url), patch.object(wrapper.cli, "main", return_value=1) as main:
                self.assertEqual(wrapper.main([url, "--output", "result.json"]), 1)
                main.assert_called_once_with([
                    provider, "--url", url, "--format", "json", "--output", "result.json"
                ])

    def test_rejects_missing_or_unsupported_inputs_before_export(self):
        invalid = [
            [], ["42"], ["https://example.com"],
            ["https://example.com/projects/P/repos/R/pull-requests/nope"],
            ["https://bitbucket.org/w/r/pull-requests/"],
            ["ftp://bitbucket.org/w/r/pull-requests/42"],
            ["https://user:secret@example.com/projects/P/repos/R/pull-requests/42"],
            ["https://bitbucket.org:bad/w/r/pull-requests/42"],
            ["https://bitbucket.org:443/w/r/pull-requests/42"],
            ["https://[broken"], [CLOUD_URL, SERVER_URL],
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments), patch.object(wrapper.cli, "main") as main:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    wrapper.main([*arguments, "--output", "result.json"])
                self.assertEqual(error.exception.code, 2)
                main.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            wrapper.main([CLOUD_URL])

    def test_query_and_fragment_are_accepted(self):
        self.assertEqual(wrapper.provider_for_url(CLOUD_URL + "?foo=bar#comment-1"), "cloud")

    def test_current_directory_config_is_preserved_and_url_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "bb-export.toml"
            config.write_text(
                '[server]\nserver="https://wrong.example"\nproject="Wrong"\n'
                'repo="wrong"\nusername="config-user"\n[defaults]\nformat="md"\n',
                encoding="utf-8",
            )
            original = Path.cwd()
            try:
                os.chdir(directory)
                with patch.dict(os.environ, {"BB_TOKEN": "test-token"}, clear=True), patch(
                    "bb_pr_export.cli.server.export_pull_request", return_value=EXPORT
                ) as export, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(wrapper.main([SERVER_URL, "--output", "review.json"]), 0)
                    self.assertEqual(Path.cwd(), Path(directory).resolve())
                    self.assertEqual(json.loads(Path("review.json").read_text()), EXPORT)
                    export.assert_called_once_with(
                        "https://example.com/bitbucket", "PROJ", "repo", "42", "test-token", "config-user"
                    )
            finally:
                os.chdir(original)

    def test_failures_do_not_create_output_or_expose_token(self):
        for failure in (None, AuthError(401, "rejected", CLOUD_URL), NetworkError("offline", CLOUD_URL)):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "review.json"
                errors = io.StringIO()
                environment = {} if failure is None else {"BB_TOKEN": "secret-value"}
                with patch.dict(os.environ, environment, clear=True), patch(
                    "bb_pr_export.cli.DEFAULT_CONFIG_PATHS", ()
                ), patch("bb_pr_export.cli.cloud.export_pull_request", side_effect=failure) as export:
                    with contextlib.redirect_stderr(errors):
                        self.assertEqual(wrapper.main([CLOUD_URL, "--output", str(output)]), 1)
                    if failure is None:
                        export.assert_not_called()
                self.assertFalse(output.exists())
                self.assertTrue(errors.getvalue())
                self.assertNotIn("secret-value", errors.getvalue())

    def test_provider_exports_preserve_discussions_and_filter_deleted_parents(self):
        cloud_comments = [
            {"id": 1, "deleted": True, "content": {"raw": "deleted request"}},
            {"id": 2, "parent": {"id": 1}, "content": {"raw": "Fixed, please check"},
             "inline": {"path": "a.py", "to": 9}},
            {"id": 3, "parent": {"id": 2}, "content": {"raw": "Still needs a test"}},
        ]
        server_activities = [{"commentAnchor": {"path": "a.py", "line": 9, "lineType": "ADDED"},
                              "comment": {"id": 1, "deleted": True, "text": "deleted request",
                                          "comments": [{"id": 2, "text": "Fixed, please check",
                                                        "comments": [{"id": 3, "text": "Still needs a test"}]}]}}]
        scenarios = (
            (CLOUD_URL, "cloud", "paginate_cloud", cloud_comments,
             {"id": 42, "participants": [{"user": {"display_name": "Reviewer"}, "approved": True}]}),
            (SERVER_URL, "server", "paginate_server", server_activities,
             {"id": 42, "reviewers": [{"user": {"displayName": "Reviewer"}, "status": "APPROVED"}]}),
        )
        for url, provider, pagination, comments, pr in scenarios:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "review.json"
                with patch.dict(os.environ, {"BB_TOKEN": "test-token"}, clear=True), patch(
                    "bb_pr_export.cli.DEFAULT_CONFIG_PATHS", ()
                ), patch(f"bb_pr_export.{provider}.fetch_json", return_value=pr), patch(
                    f"bb_pr_export.{provider}.{pagination}", return_value=comments
                ), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(wrapper.main([url, "--output", str(output)]), 0)
                result = json.loads(output.read_text())
                self.assertEqual(result["provider"], provider)
                self.assertEqual(result["reviewers"], [{"reviewer": "Reviewer", "decision": "approved"}])
                self.assertEqual([comment["id"] for comment in result["comments"]], [2, 3])
                self.assertEqual([comment["parent_id"] for comment in result["comments"]], [1, 2])
                self.assertEqual(result["comments"][0]["location"], {"path": "a.py", "line": 9, "side": "new"})
                self.assertEqual(result["comments"][1]["body"], "Still needs a test")


class SkillBundleTests(unittest.TestCase):
    def test_bundle_contains_maintained_source_and_runs_without_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            bundle = build_bundle(temporary / "dist" / "skill.zip")
            with ZipFile(bundle) as archive:
                expected = {f"{SKILL_NAME}/{name}" for name in (
                    "SKILL.md", "LICENSE", "scripts/export_pr.py"
                )}
                for source in (ROOT / "bb_pr_export").rglob("*.py"):
                    member = f"{SKILL_NAME}/scripts/{source.relative_to(ROOT).as_posix()}"
                    expected.add(member)
                    self.assertEqual(archive.read(member), source.read_bytes())
                self.assertEqual(set(archive.namelist()), expected)
                archive.extractall(temporary / "installed")
            scripts = temporary / "installed" / SKILL_NAME / "scripts"
            # -S excludes site-packages; clearing PYTHONPATH excludes the checkout.
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            result = subprocess.run(
                [sys.executable, "-S", str(scripts / "export_pr.py"), "--help"],
                cwd=temporary, env=environment, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--output", result.stdout)
            # Execute an actual bundled export using its own mocked provider.
            harness = (
                "import sys; from unittest.mock import patch; "
                "sys.path.insert(0, sys.argv[1]); import export_pr; "
                "from bb_pr_export import cli; "
                "cli.DEFAULT_CONFIG_PATHS = (); "
                f"export = {EXPORT!r}; "
                "mock = patch('bb_pr_export.cli.cloud.export_pull_request', return_value=export); "
                "mock.start(); "
                "raise SystemExit(export_pr.main([sys.argv[2], '--output', sys.argv[3]]))"
            )
            result = subprocess.run(
                [sys.executable, "-S", "-c", harness, str(scripts), CLOUD_URL, "review.json"],
                cwd=temporary, env={**environment, "BB_TOKEN": "test-token"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((temporary / "review.json").read_text()), EXPORT)
