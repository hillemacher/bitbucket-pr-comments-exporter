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


if __name__ == "__main__":
    unittest.main()
