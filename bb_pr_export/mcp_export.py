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
    workspace: str | None = None
    project: str | None = None
    repo: str | None = None

    @property
    def provider(self) -> str:
        return 'cloud' if self.base_url == 'https://bitbucket.org' else 'server'

    @property
    def missing_defaults(self) -> list[str]:
        keys = ('workspace', 'repo') if self.provider == 'cloud' else ('project', 'repo')
        return [f'[{self.provider}].{key}' for key in keys if not getattr(self, key)]

    def describe(self) -> str:
        repository = '/'.join(value or '?' for value in (
            self.workspace if self.provider == 'cloud' else self.project, self.repo))
        availability = ('PR-number input available' if not self.missing_defaults else
                        'PR-number input unavailable: missing ' + ', '.join(self.missing_defaults))
        return f'Instance: {self.base_url}; default repository: {repository}; {availability}.'


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
    return settings_from_config(_load_config(path))


def settings_from_config(config: dict[str, Any]) -> Settings:
    """Resolve only MCP-relevant settings; output options belong to the CLI."""
    _reject_secret_config(config)
    tables = {}
    for name in ('mcp', 'server', 'cloud', 'defaults'):
        table = config.get(name, {})
        if not isinstance(table, dict):
            raise BitbucketExportError(f'Config table [{name}] must be a TOML table.')
        tables[name] = table
    mcp, server_config, cloud_config, defaults = (tables[k] for k in ('mcp', 'server', 'cloud', 'defaults'))
    base = mcp.get('base_url')
    if base is None:
        has_server = bool(server_config.get('server'))
        has_cloud = bool(cloud_config.get('workspace') or cloud_config.get('repo'))
        if has_server and has_cloud:
            raise BitbucketExportError('Both providers are configured; set [mcp].base_url explicitly.')
        base = server_config.get('server') if has_server else 'https://bitbucket.org' if has_cloud else None
    if not isinstance(base, str) or not base:
        raise BitbucketExportError('Set [mcp].base_url, [server].server, or Cloud repository defaults.')
    base = canonical_base(base)
    if urlsplit(base).hostname == 'bitbucket.org' and base != 'https://bitbucket.org':
        raise BitbucketExportError('Cloud base URL must be https://bitbucket.org.')
    provider = 'cloud' if base == 'https://bitbucket.org' else 'server'
    provider_config = tables[provider]
    values = {}
    for key in (('workspace', 'repo') if provider == 'cloud' else ('project', 'repo')):
        value = provider_config.get(key)
        if value is not None and (not isinstance(value, str) or not value or value in {'.', '..'}
                                  or any(c.isspace() or c in '/\\' for c in value)):
            raise BitbucketExportError(f'[{provider}].{key} must be a nonempty repository identifier without path separators.')
        values[key] = value
    username = server_config.get('username')
    if username is None:
        username = defaults.get('username')
    if username is None:
        username = os.environ.get('BB_USERNAME')
    deleted = defaults.get('include_deleted', False)
    if not isinstance(deleted, bool) or (username is not None and not isinstance(username, str)):
        raise BitbucketExportError('Expected a username string and boolean [defaults].include_deleted.')
    return Settings(base, username if provider == 'server' else None, deleted, **values)


def resolve_pr(settings: Settings, pr_url: str | None = None, *, pr_id: int | None = None) -> tuple[str, dict[str, str]]:
    """Resolve either a complete URL or an ID, before any authenticated requests."""
    if (pr_url is None) == (pr_id is None):
        raise BitbucketExportError('Provide exactly one of pr_url or pr_id.')
    if pr_id is not None:
        if type(pr_id) is not int or pr_id <= 0:
            raise BitbucketExportError('pr_id must be a positive integer.')
        if settings.missing_defaults:
            raise BitbucketExportError('PR-number input needs ' + ', '.join(settings.missing_defaults) +
                                       '; run setup --defaults or provide a full PR URL.')
        values = {'pr': str(pr_id), 'repo': settings.repo}
        if settings.provider == 'cloud':
            values['workspace'] = settings.workspace
        else:
            values.update(server=settings.base_url, project=settings.project)
        return settings.provider, values
    provider = recognize_provider(pr_url)
    p = urlsplit(pr_url)
    if '%' in p.path or '\\' in pr_url or any(s in {'.', '..'} for s in p.path.split('/')):
        raise BitbucketExportError('Ambiguous PR URL path.')
    try:
        values = parse_pr_url(pr_url, provider)
    except BitbucketExportError:
        raise BitbucketExportError('Invalid PR URL.') from None
    base = f'{p.scheme}://{p.netloc}' if provider == 'cloud' else values['server']
    if canonical_base(base) != settings.base_url:
        raise BitbucketExportError('PR URL is outside the configured Bitbucket instance.')
    return provider, values


def export_pr(settings: Settings, pr_url: str | None = None, *, pr_id: int | None = None) -> dict[str, Any]:
    provider, values = resolve_pr(settings, pr_url, pr_id=pr_id)
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
