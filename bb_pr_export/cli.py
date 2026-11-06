"""Command-line interface for the Bitbucket PR comments exporter."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from . import cloud, server
from .urls import parse_pr_url as _parse_pr_url
from .http import AuthError, BitbucketExportError, NetworkError, NotFoundError
from .renderer import render_json, render_markdown
from .files import write_private
from .security import redact
from .limits import export_budget, limits_from_config

DEFAULT_CONFIG_PATHS = (
    Path("bb-export.toml"),
    Path.home() / ".config" / "bb-export" / "config.toml",
)

SECRET_CONFIG_KEYS = {
    "token",
    "password",
    "app_password",
    "app-password",
    "pat",
    "personal_access_token",
    "personal-access-token",
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    def report(message: str) -> None:
        print(redact(message, (args.token, os.environ.get('BB_TOKEN')),
                     (getattr(args, 'username', None), os.environ.get('BB_USERNAME'))), file=sys.stderr)

    try:
        config = _load_config(args.config)
        _reject_secret_config(config)
        args = _resolve_args(args, config)
        _validate_args(args)
        limits = limits_from_config(config)
    except BitbucketExportError as exc:
        report(str(exc))
        return 1

    token = (args.token or os.environ.get("BB_TOKEN")) if args.auth_mode == "token" else None
    if args.auth_mode == "token" and not token:
        print("Missing token. Pass --token or set BB_TOKEN.", file=sys.stderr)
        return 1

    try:
        with export_budget(limits):
            export = _fetch_export(args, token)
        output_path = _output_path(args)
        content = render_json(export, include_deleted=args.include_deleted) if args.format == "json" else render_markdown(export, include_deleted=args.include_deleted)
        try:
            write_private(output_path, content)
        except OSError as exc:
            raise BitbucketExportError(f"Could not write output '{output_path}': {exc.strerror or str(exc)}") from exc
    except AuthError:
        print(
            ("Authentication failed. Check the egress access rules and credential injection setup."
             if args.auth_mode == "egress" else
             "Authentication failed. Check that the API token is valid and has read:pullrequest:bitbucket scope."
             if args.provider == "cloud" else
             "Authentication failed. Check that the token is valid and has repository/pull request read access."),
            file=sys.stderr,
        )
        return 1
    except NotFoundError:
        report(_not_found_message(args))
        return 1
    except NetworkError as exc:
        hint = " Check the --server URL." if args.provider == "server" else ""
        report(f"{exc}.{hint}")
        return 1
    except BitbucketExportError as exc:
        report(str(exc))
        return 1

    print(f"Wrote {output_path}")
    return 0


def _fetch_export(args: argparse.Namespace, token: str | None) -> dict[str, Any]:
    match args.provider:
        case "cloud":
            return cloud.export_pull_request(args.workspace, args.repo, args.pr, token)
        case "server":
            username = (args.username or os.environ.get("BB_USERNAME")) if args.auth_mode == "token" else None
            return server.export_pull_request(args.server, args.project, args.repo, args.pr, token, username)
        case _:
            raise BitbucketExportError(f"Unknown provider: {args.provider}")


def _default_output(pr_id: str, output_format: str) -> str:
    return f"pr_{pr_id}_comments.{output_format}"


def _output_path(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)
    default_name = _default_output(args.pr, args.format)
    if args.output_dir:
        return Path(args.output_dir) / default_name
    return Path(default_name)


def _not_found_message(args: argparse.Namespace) -> str:
    match args.provider:
        case "cloud":
            return (
                f"Not found. Check workspace '{args.workspace}', repository '{args.repo}', "
                f"and pull request '{args.pr}'."
            )
        case "server":
            return (
                f"Not found. Check project '{args.project}', repository '{args.repo}', "
                f"pull request '{args.pr}', and server URL '{args.server}'."
            )
        case _:
            return "Not found. Check the workspace/project, repository, and pull request id."


def _load_config(config_path: str | None) -> dict[str, Any]:
    if config_path:
        path = Path(config_path)
        try:
            with path.open("rb") as config_file:
                return tomllib.load(config_file)
        except OSError as exc:
            raise BitbucketExportError(f"Could not read config file '{path}': {exc.strerror}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise BitbucketExportError(f"Could not parse config file '{path}': invalid TOML syntax.") from exc

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            try:
                with path.open("rb") as config_file:
                    return tomllib.load(config_file)
            except OSError as exc:
                raise BitbucketExportError(f"Could not read config file '{path}': {exc.strerror}") from exc
            except tomllib.TOMLDecodeError as exc:
                raise BitbucketExportError(f"Could not parse config file '{path}': invalid TOML syntax.") from exc
    return {}


def _reject_secret_config(config: dict[str, Any]) -> None:
    root_secrets = SECRET_CONFIG_KEYS.intersection(config)
    if root_secrets:
        keys = ", ".join(sorted(root_secrets))
        raise BitbucketExportError(
            f"Config file must not contain secrets ({keys}). Pass credentials with --token or BB_TOKEN instead."
        )
    for table_name, table in config.items():
        if not isinstance(table, dict):
            continue
        found = SECRET_CONFIG_KEYS.intersection(table)
        if found:
            keys = ", ".join(sorted(found))
            raise BitbucketExportError(
                f"Config file must not contain secrets ({keys}) in [{table_name}]. "
                "Pass credentials with --token or BB_TOKEN instead."
            )


def _resolve_args(args: argparse.Namespace, config: dict[str, Any]) -> argparse.Namespace:
    defaults = _table(config, "defaults")
    provider_config = _table(config, args.provider)
    url_values = _parse_pr_url(args.url, args.provider) if args.url else {}

    resolved = argparse.Namespace(**vars(args))
    for key in _provider_keys(args.provider):
        setattr(resolved, key, _first_present(getattr(args, key, None), url_values.get(key), provider_config.get(key)))

    for key in ("output", "output_dir", "format", "include_deleted"):
        setattr(resolved, key, _first_present(getattr(args, key, None), defaults.get(key)))
    resolved.format = resolved.format or "md"
    if resolved.include_deleted is None:
        resolved.include_deleted = False

    if args.provider == "server":
        resolved.username = _first_present(args.username, provider_config.get("username"), defaults.get("username"))
    return resolved


def _table(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BitbucketExportError(f"Config table [{name}] must be a TOML table.")
    return value


def _provider_keys(provider: str) -> tuple[str, ...]:
    match provider:
        case "cloud":
            return ("workspace", "repo", "pr")
        case "server":
            return ("server", "project", "repo", "pr")
        case _:
            return ()


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _validate_args(args: argparse.Namespace) -> None:
    missing = [key for key in _provider_keys(args.provider) if not getattr(args, key, None)]
    if missing:
        joined = ", ".join(f"--{key.replace('_', '-')}" for key in missing)
        raise BitbucketExportError(f"Missing required option(s): {joined}. Provide them as flags, in --url, or in config.")
    if args.format not in {"md", "json"}:
        raise BitbucketExportError("Invalid format. Expected 'md' or 'json'.")
    if not isinstance(args.include_deleted, bool):
        raise BitbucketExportError("Invalid include_deleted value. Expected true or false.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bb-export", description="Export Bitbucket PR comments.")
    subparsers = parser.add_subparsers(dest="provider", required=True)

    cloud_parser = subparsers.add_parser("cloud", help="Export from Bitbucket Cloud")
    cloud_parser.add_argument("--workspace")
    cloud_parser.add_argument("--repo")
    cloud_parser.add_argument("--pr", metavar="PR_ID")
    _add_shared_options(cloud_parser)

    server_parser = subparsers.add_parser("server", help="Export from Bitbucket Server/Data Center")
    server_parser.add_argument("--server", help="Base URL, for example https://bitbucket.example.com")
    server_parser.add_argument("--project")
    server_parser.add_argument("--repo")
    server_parser.add_argument("--pr", metavar="PR_ID")
    server_parser.add_argument("--username")
    _add_shared_options(server_parser)

    return parser


def _add_shared_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--auth-mode", choices=("token", "egress"), default="token",
        help="Authentication source: local token (default) or egress credential injection",
    )
    parser.add_argument("--token")
    parser.add_argument("--url", help="Bitbucket pull request URL")
    parser.add_argument("--config", help="Path to a TOML config file")
    parser.add_argument("--output")
    parser.add_argument("--output-dir")
    parser.add_argument("--include-deleted", action="store_true", default=None)
    parser.add_argument("--format", choices=("md", "json"))


if __name__ == "__main__":
    raise SystemExit(main())
