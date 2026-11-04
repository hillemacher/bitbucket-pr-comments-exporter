"""URL-only entry point for the bundled Bitbucket feedback skill."""

from __future__ import annotations

import argparse

from bb_pr_export import cli
from bb_pr_export.urls import recognize_provider
from bb_pr_export.http import BitbucketExportError


def provider_for_url(url: str) -> str:
    try:
        return recognize_provider(url)
    except BitbucketExportError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export feedback from one Bitbucket PR URL as JSON.")
    parser.add_argument("url", help="Bitbucket Cloud or Server/Data Center PR URL")
    parser.add_argument("--output", required=True, help="Destination JSON file")
    parser.add_argument(
        "--auth-mode", choices=("token", "egress"), default="egress",
        help="Authentication source: egress credential injection (default) or local token",
    )
    args = parser.parse_args(argv)
    try:
        provider = provider_for_url(args.url)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    return cli.main([
        provider, "--url", args.url, "--format", "json", "--output", args.output,
        "--auth-mode", args.auth_mode,
    ])


if __name__ == "__main__":
    raise SystemExit(main())
