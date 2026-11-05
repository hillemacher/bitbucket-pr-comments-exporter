"""Opt-in Docker smoke test: python tests/smoke_container.py IMAGE.

Uses a disposable Bitbucket fixture, fake PAT, network and MCP container. No live
Bitbucket requests. Requires the optional MCP extra on the test host.
"""
import asyncio
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from mcp import Client

FIXTURE = '''import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.headers.get('Authorization') != 'Bearer smoke-fixture':
   self.send_error(401); return
  data = {'id': 42, 'title': 'fixture'}
  if '/activities' in self.path:
   data = {'values': [{'comment': {'id': 1, 'text': 'fixture comment'}}], 'isLastPage': True}
  body = json.dumps(data).encode()
  self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)
 def log_message(self, *args): pass
HTTPServer(('0.0.0.0', 8010), Handler).serve_forever()
'''


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


async def verify(url):
    async with Client(url) as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == ['export_pr_comments']
        result = await client.call_tool('export_pr_comments', {
            'pr_url': 'http://bb-fixture:8010/bitbucket/projects/P/repos/r/pull-requests/42'})
        assert not result.is_error, result
        assert result.structured_content['comments'][0]['body'] == 'fixture comment'
        assert tools[0].input_schema['required'] == ['pr_url']
        assert set(tools[0].input_schema['properties']) == {'pr_url'}
        numbered = await client.call_tool('export_pr_comments', {'pr_id': 42})
        assert numbered.is_error
        rejected = await client.call_tool('export_pr_comments', {'pr_url': 'https://evil.example/projects/P/repos/r/pull-requests/42'})
        assert rejected.is_error


def main():
    image = sys.argv[1]
    prefix = 'bb-smoke-' + uuid.uuid4().hex[:10]
    network, fixture, service = prefix + '-net', prefix + '-fixture', prefix + '-mcp'
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        (path/'config.toml').write_text('[mcp]\nbase_url="http://bb-fixture:8010/bitbucket"\n[server]\nproject="P"\nrepo="r"\n')
        (path/'bitbucket.pat').write_text('smoke-fixture\n')
        (path/'fixture.py').write_text(FIXTURE)
        for name in ('config.toml', 'bitbucket.pat'):
            (path/name).chmod(0o600)
        try:
            docker('network','create',network)
            docker('run','-d','--name',fixture,'--network',network,'--network-alias','bb-fixture',
                   '--entrypoint','python3','-v',f'{path}/fixture.py:/fixture.py:ro',image,'/fixture.py')
            # Select a host port before launch so transport security can use it.
            import socket
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
            docker('run','-d','--name',service,'--network',network,'--user',f'{os.getuid()}:{os.getgid()}',
                   '-p',f'127.0.0.1:{port}:9000','-v',f'{path}:/config:ro',
                   '-e',f'BB_MCP_HOST_PORT={port}',image)
            for _ in range(30):
                try:
                    docker('exec',service,'python3','/app/entrypoint.py','probe-mcp','http://127.0.0.1:9000/mcp')
                    break
                except subprocess.CalledProcessError:
                    time.sleep(0.5)
            else:
                raise RuntimeError(docker('logs',service))
            print(docker('exec', service, 'python3', '/app/entrypoint.py', 'check', 'http://bb-fixture:8010/bitbucket/projects/P/repos/r/pull-requests/42'))
            asyncio.run(verify(f'http://127.0.0.1:{port}/mcp'))
            if platform.system() == 'Darwin':
                print(docker('run','--rm',image,'probe-mcp',f'http://host.docker.internal:{port}/mcp'))
            else:
                # Linux CI verifies container access over the fixture network.
                # Host-loopback forwarding through host.docker.internal is macOS-specific.
                print(docker('run', '--rm', '--network', f'container:{service}', image,
                             'probe-mcp', 'http://127.0.0.1:9000/mcp'))
            print('Container smoke passed: host exports and container MCP connectivity.')
        finally:
            for name in (service, fixture):
                subprocess.run(['docker','rm','-f',name],capture_output=True)
            subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__ == '__main__':
    main()
