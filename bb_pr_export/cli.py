"""Command-line interface for the Bitbucket PR comments exporter."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import cloud, server
from .http import AuthError, BitbucketExportError, NetworkError, NotFoundError
from .renderer import render_json, render_markdown

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

    try:
        config = _load_config(args.config)
        _reject_secret_config(config)
        args = _resolve_args(args, config)
        _validate_args(args)
    except BitbucketExportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    token = args.token or os.environ.get("BB_TOKEN")
    if not token:
        print("Missing token. Pass --token or set BB_TOKEN.", file=sys.stderr)
        return 1

    try:
        export = _fetch_export(args, token)
        output_path = _output_path(args)
        content = render_json(export, include_deleted=args.include_deleted) if args.format == "json" else render_markdown(export, include_deleted=args.include_deleted)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise BitbucketExportError(f"Could not write output '{output_path}': {exc.strerror or str(exc)}") from exc
    except AuthError:
        print(
            "Authentication failed. Check that the token/app password is valid and has Pull Requests: Read scope.",
            file=sys.stderr,
        )
        return 1
    except NotFoundError:
        print(_not_found_message(args), file=sys.stderr)
        return 1
    except NetworkError as exc:
        hint = " Check the --server URL." if args.provider == "server" else ""
        print(f"{exc}.{hint}", file=sys.stderr)
        return 1
    except BitbucketExportError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wrote {output_path}")
    return 0


def _fetch_export(args: argparse.Namespace, token: str) -> dict[str, Any]:
    match args.provider:
        case "cloud":
            return cloud.export_pull_request(args.workspace, args.repo, args.pr, token)
        case "server":
            username = args.username or os.environ.get("BB_USERNAME")
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
            raise BitbucketExportError(f"Could not parse config file '{path}': {exc}") from exc

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            try:
                with path.open("rb") as config_file:
                    return tomllib.load(config_file)
            except OSError as exc:
                raise BitbucketExportError(f"Could not read config file '{path}': {exc.strerror}") from exc
            except tomllib.TOMLDecodeError as exc:
                raise BitbucketExportError(f"Could not parse config file '{path}': {exc}") from exc
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


def _parse_pr_url(url: str, provider: str) -> dict[str, str]:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise BitbucketExportError(f"Invalid PR URL '{url}'. Include scheme and host, for example https://...")

    parts = [part for part in parsed.path.split("/") if part]
    match provider:
        case "server":
            return _parse_server_url(parsed.scheme, parsed.netloc, parts, url)
        case "cloud":
            return _parse_cloud_url(parsed.netloc, parts, url)
        case _:
            raise BitbucketExportError(f"Unknown provider: {provider}")


def _parse_server_url(scheme: str, netloc: str, parts: list[str], original_url: str) -> dict[str, str]:
    try:
        projects_index = parts.index("projects")
        repos_index = parts.index("repos")
        prs_index = parts.index("pull-requests")
        project = unquote(parts[projects_index + 1])
        repo = unquote(parts[repos_index + 1])
        pr = unquote(parts[prs_index + 1])
    except (ValueError, IndexError) as exc:
        raise BitbucketExportError(
            "Server PR URL must look like "
            "https://host/projects/PROJECT/repos/REPO/pull-requests/PR_ID"
        ) from exc
    if projects_index > repos_index or repos_index > prs_index:
        raise BitbucketExportError(f"Could not parse Server PR URL '{original_url}'.")
    context_path = "/".join(parts[:projects_index])
    server_url = f"{scheme}://{netloc}"
    if context_path:
        server_url = f"{server_url}/{context_path}"
    return {"server": server_url, "project": project, "repo": repo, "pr": pr}


def _parse_cloud_url(netloc: str, parts: list[str], original_url: str) -> dict[str, str]:
    if netloc.lower() != "bitbucket.org":
        raise BitbucketExportError(f"Cloud PR URL must use bitbucket.org, got '{original_url}'.")
    try:
        prs_index = parts.index("pull-requests")
        workspace = unquote(parts[0])
        repo = unquote(parts[1])
        pr = unquote(parts[prs_index + 1])
    except (ValueError, IndexError) as exc:
        raise BitbucketExportError("Cloud PR URL must look like https://bitbucket.org/WORKSPACE/REPO/pull-requests/PR_ID") from exc
    if prs_index < 2:
        raise BitbucketExportError(f"Could not parse Cloud PR URL '{original_url}'.")
    return {"workspace": workspace, "repo": repo, "pr": pr}


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
    parser.add_argument("--token")
    parser.add_argument("--url", help="Bitbucket pull request URL")
    parser.add_argument("--config", help="Path to a TOML config file")
    parser.add_argument("--output")
    parser.add_argument("--output-dir")
    parser.add_argument("--include-deleted", action="store_true", default=None)
    parser.add_argument("--format", choices=("md", "json"))


if __name__ == "__main__":
    raise SystemExit(main())
