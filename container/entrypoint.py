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
from bb_pr_export.mcp_export import canonical_base, export_pr, load_settings, settings_from_config

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
    print(settings.describe())
    return settings


def setup(renew: bool) -> None:
    from tomlkit import document, dumps, parse, table

    path = CONFIG / 'config.toml'
    creating = not path.exists()
    doc = document() if creating else parse(path.read_text(encoding='utf-8'))
    if creating:
        print('Base URL examples: https://bitbucket.example.com/bitbucket (Server/Data Center) '
              'or https://bitbucket.org (Cloud). Include any context path, such as /bitbucket.')
        base = canonical_base(input('Bitbucket base URL (include context path): ').strip())
        print('For Server/Data Center, a username (for example, jane.doe) selects Basic authentication; '
              'leave it blank for Bearer/PAT. Cloud does not use this username.')
        username = input('Optional Server username (Enter for Bearer/PAT): ').strip()
        doc['mcp'] = {'base_url': base}
        doc['defaults'] = {'include_deleted': False}
        if base != 'https://bitbucket.org':
            doc['server'] = {'server': base}
        if username:
            if 'server' not in doc:
                doc['server'] = table()
            doc['server']['username'] = username
    # Validate everything before modifying the existing file or PAT.
    settings_from_config(doc.unwrap())
    if creating:
        write_private(path, dumps(doc))
    if renew or not (CONFIG / 'bitbucket.pat').exists():
        print('The token is saved in bitbucket.pat, separately from config.toml.')
        if os.environ.get('BB_TOKEN'):
            print('Using the token supplied by BB_TOKEN.')
        else:
            print('Enter your Bitbucket token below; input is hidden.')
        token = os.environ.get('BB_TOKEN') or getpass.getpass('Bitbucket PAT (hidden): ')
        token = token.strip()
        if not token or any(c.isspace() for c in token):
            raise BitbucketExportError('PAT must be nonempty and contain no whitespace.')
        write_private(CONFIG / 'bitbucket.pat', token + '\n')
    preflight()
    print('Setup complete. Run check <PR_URL> to test access, then start.')


def check(settings, reference: str):
    result = export_pr(settings, reference)
    print(f"Export ok: {len(result['comments'])} comments, {len(result['reviewers'])} reviewer decisions")
    return result


async def probe(url: str, label: str = 'endpoint') -> None:
    from mcp import Client
    async with Client(url) as client:
        tools = await client.list_tools()
        if [tool.name for tool in tools.tools] != ['export_pr_comments']:
            raise BitbucketExportError('Unexpected MCP tool inventory.')
    print(f'MCP ready ({label}): {url} — export_pr_comments available')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'preflight', 'serve', 'check', 'probe-mcp', 'image-fingerprint'])
    parser.add_argument('reference', nargs='?')
    parser.add_argument('--tokens', action='store_true')
    parser.add_argument('--probe-label', default='endpoint', help='Connection path shown in MCP probe output')
    args = parser.parse_args()
    try:
        if args.command == 'setup':
            setup(args.tokens)
        elif args.command == 'image-fingerprint':
            image = json.load(sys.stdin)[0]
            stable = {key: image.get(key) for key in ('Architecture', 'Os', 'Variant', 'RootFS', 'Config')}
            print(hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest())
        elif args.command == 'probe-mcp':
            if not args.reference:
                parser.error('probe-mcp requires a URL')
            asyncio.run(asyncio.wait_for(probe(args.reference, args.probe_label), 10))
        else:
            settings = preflight()
            if args.command == 'serve':
                from bb_pr_export.mcp_server import main as serve
                return serve(['--config', str(CONFIG / 'config.toml'), '--host-port', os.environ.get('BB_MCP_HOST_PORT', '9002')])
            if args.command == 'check':
                if not args.reference:
                    parser.error('check requires a full PR URL')
                check(settings, args.reference)
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
