"""Container setup and runtime helpers. Secrets are never Docker environment settings."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from bb_pr_export.http import BitbucketExportError
from bb_pr_export.mcp_export import canonical_base, export_pr, load_settings

CONFIG = Path('/config')


def write_private(path: Path, value: str) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(value)
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def preflight():
    settings = load_settings(str(CONFIG / 'config.toml'))
    token = (CONFIG / 'bitbucket.pat').read_text().strip()
    if not token or any(c.isspace() for c in token):
        raise BitbucketExportError('PAT is empty or contains whitespace; run setup --tokens.')
    os.environ['BB_TOKEN'] = token
    return settings


def setup(renew: bool) -> None:
    if not (CONFIG / 'config.toml').exists():
        base = canonical_base(input('Bitbucket base URL (include context path): ').strip())
        username = input('Optional Server username (Enter for Bearer/PAT): ').strip()
        content = '[mcp]\nbase_url = ' + json.dumps(base) + '\n\n[server]\n'
        if username:
            content += 'username = ' + json.dumps(username) + '\n'
        content += '\n[defaults]\ninclude_deleted = false\n'
        write_private(CONFIG / 'config.toml', content)
    if renew or not (CONFIG / 'bitbucket.pat').exists():
        token = os.environ.get('BB_TOKEN') or getpass.getpass('Bitbucket PAT (hidden): ')
        token = token.strip()
        if not token or any(c.isspace() for c in token):
            raise BitbucketExportError('PAT must be nonempty and contain no whitespace.')
        write_private(CONFIG / 'bitbucket.pat', token + '\n')
    preflight()
    print('Setup complete. Run check <PR_URL> to test access, then start.')


async def probe(url: str) -> None:
    from mcp import Client
    async with Client(url) as client:
        tools = await client.list_tools()
        if [tool.name for tool in tools.tools] != ['export_pr_comments']:
            raise BitbucketExportError('Unexpected MCP tool inventory.')
    print('MCP ready: export_pr_comments')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'preflight', 'serve', 'check', 'probe-mcp', 'image-fingerprint'])
    parser.add_argument('url', nargs='?')
    parser.add_argument('--tokens', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'setup':
            setup(args.tokens)
        elif args.command == 'image-fingerprint':
            image = json.load(sys.stdin)[0]
            stable = {key: image.get(key) for key in ('Architecture', 'Os', 'Variant', 'RootFS', 'Config')}
            print(hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest())
        elif args.command == 'probe-mcp':
            if not args.url:
                parser.error('probe-mcp requires a URL')
            asyncio.run(asyncio.wait_for(probe(args.url), 10))
        else:
            settings = preflight()
            if args.command == 'serve':
                from bb_pr_export.mcp_server import main as serve
                return serve(['--config', str(CONFIG / 'config.toml'), '--host-port', os.environ.get('BB_MCP_HOST_PORT', '9002')])
            if args.command == 'check':
                if not args.url:
                    parser.error('check requires a PR URL')
                result = export_pr(settings, args.url)
                print(f"Export ok: {len(result['comments'])} comments, {len(result['reviewers'])} reviewer decisions")
            else:
                print('preflight: ok')
    except (BitbucketExportError, OSError) as exc:
        # OSError details may include local paths, but never read/print file contents.
        print(f'error: {exc}', file=sys.stderr)
        return 1
    except Exception:
        print('error: MCP probe or startup failed; check service status and URL.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
