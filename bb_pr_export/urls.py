"""Shared Bitbucket web URL parsing (no network or credentials)."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse, urlsplit
from .http import BitbucketExportError


def recognize_provider(url: str) -> str:
    """Recognize supported web PR URLs before making authenticated requests."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise BitbucketExportError("Invalid PR URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in url)
    ):
        raise BitbucketExportError("Provide an HTTP(S) PR URL without embedded credentials.")

    if parsed.hostname.lower() == "bitbucket.org":
        # The existing Cloud URL parser requires this exact authority.
        supported = port is None and parsed.netloc.lower() == "bitbucket.org"
        pattern = r"/[^/]+/[^/]+/pull-requests/[0-9]+(?:/.*)?"
        provider = "cloud"
    else:
        supported = True
        pattern = r"(?:/[^/]+)*/projects/[^/]+/repos/[^/]+/pull-requests/[0-9]+(?:/.*)?"
        provider = "server"
    if not supported or not re.fullmatch(pattern, parsed.path):
        raise BitbucketExportError("Provide a supported Bitbucket Cloud or Server/Data Center PR URL.")
    return provider


def parse_pr_url(url: str, provider: str) -> dict[str, str]:
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


