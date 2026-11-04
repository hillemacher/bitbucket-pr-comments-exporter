"""Stdlib-only, in-memory export service for the single-instance MCP adapter."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from . import cloud, server
from .cli import _load_config, _reject_secret_config
from .http import AuthError, BitbucketExportError, NetworkError, NotFoundError
from .urls import parse_pr_url, recognize_provider


@dataclass(frozen=True)
class Settings:
    base_url: str
    username: str | None = None
    include_deleted: bool = False


def canonical_base(url: str) -> str:
    try:
        p = urlsplit(url)
        port = p.port
        if (p.scheme not in {'http', 'https'} or not p.hostname or p.username is not None
                or p.password is not None or p.query or p.fragment
                or any(c.isspace() for c in url) or '\\' in url):
            raise ValueError
        # Reject encoded separators/dot segments rather than normalizing ambiguous paths.
        if '%' in p.path or any(s in {'.', '..'} for s in p.path.split('/')):
            raise ValueError
        authority = p.hostname.lower()
        if ':' in authority:
            authority = f'[{authority}]'
        if port is not None and port != (443 if p.scheme == 'https' else 80):
            authority += f':{port}'
        return f'{p.scheme}://{authority}{p.path.rstrip("/")}'
    except (ValueError, TypeError) as exc:
        raise BitbucketExportError('Invalid Bitbucket base URL.') from exc


def load_settings(path: str) -> Settings:
    config = _load_config(path)
    _reject_secret_config(config)
    try:
        base = canonical_base(config['mcp']['base_url'])
        username = config.get('server', {}).get('username')
        deleted = config.get('defaults', {}).get('include_deleted', False)
        if not isinstance(deleted, bool) or (username is not None and not isinstance(username, str)):
            raise ValueError
        if urlsplit(base).hostname == 'bitbucket.org' and base != 'https://bitbucket.org':
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise BitbucketExportError('Expected [mcp].base_url, optional [server].username and boolean [defaults].include_deleted.') from exc
    return Settings(base, username, deleted)


def export_pr(settings: Settings, pr_url: str) -> dict[str, Any]:
    provider = recognize_provider(pr_url)
    # Forbid ambiguous escaped path segments before the legacy parser decodes them.
    p = urlsplit(pr_url)
    if '%' in p.path or '\\' in pr_url or any(s in {'.', '..'} for s in p.path.split('/')):
        raise BitbucketExportError('Ambiguous PR URL path.')
    values = parse_pr_url(pr_url, provider)
    base = f'{p.scheme}://{p.netloc}' if provider == 'cloud' else values['server']
    if canonical_base(base) != settings.base_url:
        raise BitbucketExportError('PR URL is outside the configured Bitbucket instance.')
    token = os.environ.get('BB_TOKEN')
    if not token:
        raise BitbucketExportError('Missing Bitbucket token; run setup.')
    try:
        if provider == 'cloud':
            result = cloud.export_pull_request(values['workspace'], values['repo'], values['pr'], token)
        else:
            result = server.export_pull_request(settings.base_url, values['project'], values['repo'], values['pr'], token, settings.username)
    except AuthError:
        raise BitbucketExportError('Bitbucket authentication failed; check the PAT and repository read permissions.') from None
    except NotFoundError:
        raise BitbucketExportError('Pull request not found or inaccessible.') from None
    except NetworkError:
        raise BitbucketExportError('Cannot reach Bitbucket; check network, VPN and certificate trust.') from None
    except BitbucketExportError:
        raise BitbucketExportError('Bitbucket returned an invalid or unsuccessful API response.') from None
    return {**result, 'comments': [c for c in result.get('comments', []) if settings.include_deleted or not c.get('deleted')]}
