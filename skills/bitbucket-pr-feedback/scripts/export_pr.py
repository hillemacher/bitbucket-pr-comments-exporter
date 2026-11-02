"""URL-only entry point for the bundled Bitbucket feedback skill."""

from __future__ import annotations

import argparse
import re
from urllib.parse import urlsplit

from bb_pr_export import cli


def provider_for_url(url: str) -> str:
    """Recognize supported web PR URLs before making authenticated requests."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Invalid PR URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in url)
    ):
        raise argparse.ArgumentTypeError("Provide an HTTP(S) PR URL without embedded credentials.")

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
        raise argparse.ArgumentTypeError("Provide a supported Bitbucket Cloud or Server/Data Center PR URL.")
    return provider


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export feedback from one Bitbucket PR URL as JSON.")
    parser.add_argument("url", help="Bitbucket Cloud or Server/Data Center PR URL")
    parser.add_argument("--output", required=True, help="Destination JSON file")
    args = parser.parse_args(argv)
    try:
        provider = provider_for_url(args.url)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    return cli.main([provider, "--url", args.url, "--format", "json", "--output", args.output])


if __name__ == "__main__":
    raise SystemExit(main())
