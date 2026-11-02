import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bb_pr_export.cli import main


EXPORT = {
    "pr": {
        "id": 500,
        "title": "Title",
        "state": "OPEN",
        "author": "Author",
        "source_branch": "feature",
        "destination_branch": "main",
        "created": "2024-01-01T00:00:00+00:00",
        "description": "",
    },
    "reviewers": [],
    "comments": [],
}


class CliTests(unittest.TestCase):
    @patch.dict("os.environ", {"BB_TOKEN": "token"}, clear=True)
    @patch("bb_pr_export.cli.server.export_pull_request", return_value=EXPORT)
    def test_server_url_derives_required_values(self, export_pull_request):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text("", encoding="utf-8")
            output = Path(temp_dir) / "out.md"

            exit_code = main(
                [
                    "server",
                    "--config",
                    str(config),
                    "--url",
                    "https://bitbucket.CompanyX/projects/CoolP/repos/SomeRepo/pull-requests/500/overview",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(exit_code, 0)
        export_pull_request.assert_called_once_with("https://bitbucket.CompanyX", "CoolP", "SomeRepo", "500", "token", None)

    @patch.dict("os.environ", {"BB_TOKEN": "token"}, clear=True)
    @patch("bb_pr_export.cli.cloud.export_pull_request", return_value=EXPORT)
    def test_cloud_url_derives_required_values(self, export_pull_request):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text("", encoding="utf-8")
            output = Path(temp_dir) / "out.md"

            exit_code = main(
                [
                    "cloud",
                    "--config",
                    str(config),
                    "--url",
                    "https://bitbucket.org/workspace/repo/pull-requests/500",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(exit_code, 0)
        export_pull_request.assert_called_once_with("workspace", "repo", "500", "token")

    @patch.dict("os.environ", {"BB_TOKEN": "token"}, clear=True)
    @patch("bb_pr_export.cli.server.export_pull_request", return_value=EXPORT)
    def test_cli_flags_override_url_and_config(self, export_pull_request):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
[server]
server = "https://config.example"
project = "ConfigProject"
repo = "ConfigRepo"

[defaults]
output_dir = "exports"
""",
                encoding="utf-8",
            )
            output = Path(temp_dir) / "out.md"

            exit_code = main(
                [
                    "server",
                    "--config",
                    str(config),
                    "--url",
                    "https://url.example/projects/UrlProject/repos/UrlRepo/pull-requests/500/overview",
                    "--server",
                    "https://cli.example",
                    "--project",
                    "CliProject",
                    "--repo",
                    "CliRepo",
                    "--pr",
                    "600",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(exit_code, 0)
        export_pull_request.assert_called_once_with("https://cli.example", "CliProject", "CliRepo", "600", "token", None)

    @patch.dict("os.environ", {"BB_TOKEN": "token"}, clear=True)
    @patch("bb_pr_export.cli.server.export_pull_request", return_value=EXPORT)
    def test_config_fills_missing_values_and_output_dir(self, export_pull_request):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            output_dir = Path(temp_dir) / "exports"
            config.write_text(
                f"""
[server]
server = "https://config.example"
project = "ConfigProject"
repo = "ConfigRepo"
username = "config.user"

[defaults]
output_dir = "{output_dir}"
format = "md"
include_deleted = true
""",
                encoding="utf-8",
            )

            exit_code = main(["server", "--config", str(config), "--pr", "500"])

            expected_output = output_dir / "pr_500_comments.md"
            self.assertTrue(expected_output.exists())

        self.assertEqual(exit_code, 0)
        export_pull_request.assert_called_once_with(
            "https://config.example",
            "ConfigProject",
            "ConfigRepo",
            "500",
            "token",
            "config.user",
        )

    @patch.dict("os.environ", {"BB_TOKEN": "token"}, clear=True)
    def test_config_rejects_secret_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text(
                """
[server]
server = "https://config.example"
token = "secret"
""",
                encoding="utf-8",
            )
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = main(["server", "--config", str(config), "--pr", "500"])

        self.assertEqual(exit_code, 1)
        self.assertIn("must not contain secrets", stderr.getvalue())

    @patch.dict("os.environ", {"BB_TOKEN": "token"}, clear=True)
    def test_missing_required_fields_exits_with_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.toml"
            config.write_text("", encoding="utf-8")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = main(["server", "--config", str(config), "--pr", "500"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Missing required option", stderr.getvalue())

class DeletedOptionTests(unittest.TestCase):
    def test_boolean_validation_and_cli_precedence(self):
        from bb_pr_export.cli import _build_parser, _resolve_args, _validate_args
        from bb_pr_export.http import BitbucketExportError
        flags = ['cloud', '--workspace', 'w', '--repo', 'r', '--pr', '1']
        for value in ('false', 0, 1, [], {}):
            with self.subTest(value=value):
                args = _resolve_args(_build_parser().parse_args(flags), {'defaults': {'include_deleted': value}})
                with self.assertRaises(BitbucketExportError):
                    _validate_args(args)
        for config, expected in (({}, False), ({'defaults': {'include_deleted': False}}, False), ({'defaults': {'include_deleted': True}}, True)):
            args = _resolve_args(_build_parser().parse_args(flags), config)
            _validate_args(args)
            self.assertIs(args.include_deleted, expected)
        args = _resolve_args(_build_parser().parse_args(flags + ['--include-deleted']), {'defaults': {'include_deleted': False}})
        self.assertIs(args.include_deleted, True)

    @patch.dict('os.environ', {'BB_TOKEN': 'dummy'}, clear=True)
    @patch('bb_pr_export.cli._load_config', return_value={})
    @patch('bb_pr_export.cli.cloud.export_pull_request')
    def test_json_flag_reaches_renderer(self, fetch, load):
        import json
        fetch.return_value = {**EXPORT, 'comments': [{'id': 1, 'deleted': True, 'body': 'deleted'}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.json'
            flags = ['cloud', '--workspace', 'w', '--repo', 'r', '--pr', '1', '--format', 'json', '--output', str(output)]
            for extra, expected in (([], []), (['--include-deleted'], fetch.return_value['comments'])):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(flags + extra), 0)
                self.assertEqual(json.loads(output.read_text())['comments'], expected)


class OutputErrorTests(unittest.TestCase):
    @patch.dict('os.environ', {'BB_TOKEN': 'dummy'}, clear=True)
    @patch('bb_pr_export.cli._load_config', return_value={})
    @patch('bb_pr_export.cli.cloud.export_pull_request', return_value=EXPORT)
    def test_filesystem_errors_are_reported(self, fetch, load):
        for operation in ('mkdir', 'write_text'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'out.md'
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(Path, operation, side_effect=PermissionError(13, 'Permission denied')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(['cloud', '--workspace', 'w', '--repo', 'r', '--pr', '1', '--output', str(path)])
                self.assertEqual(code, 1)
                self.assertIn(str(path), stderr.getvalue())
                self.assertIn('Permission denied', stderr.getvalue())
                self.assertNotIn('Traceback', stderr.getvalue())
                self.assertEqual(stdout.getvalue(), '')


class AuthenticationMessageTests(unittest.TestCase):
    @patch.dict('os.environ', {'BB_TOKEN': 'dummy'}, clear=True)
    @patch('bb_pr_export.cli._load_config', return_value={})
    def test_provider_specific_authentication_guidance(self, load):
        from bb_pr_export.http import AuthError
        cases = [(['cloud', '--workspace', 'w', '--repo', 'r'], 'read:pullrequest:bitbucket'),
                 (['server', '--server', 'https://api.example', '--project', 'P', '--repo', 'r'], 'read access')]
        for flags, expected in cases:
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch('bb_pr_export.cli._fetch_export', side_effect=AuthError(401, 'unauthorized', 'https://api.example')), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(main(flags + ['--pr', '1']), 1)
            self.assertIn(expected, stderr.getvalue())
            self.assertNotIn('dummy', stderr.getvalue())
            self.assertEqual(stdout.getvalue(), '')


if __name__ == "__main__":
    unittest.main()
