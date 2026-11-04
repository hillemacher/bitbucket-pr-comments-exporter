"""MCP/service coverage. All Bitbucket calls use fixtures or mocks."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bb_pr_export.http import AuthError, BitbucketExportError, NetworkError, NotFoundError
from bb_pr_export.mcp_export import Settings, export_pr, load_settings

CLOUD = 'https://bitbucket.org/w/r/pull-requests/42'
SERVER = 'https://bb.example/bitbucket/projects/P/repos/r/pull-requests/42/overview'
PAYLOAD = {'provider': 'cloud', 'pr': {'id': 42}, 'reviewers': [], 'comments': [
    {'id': 1, 'deleted': True}, {'id': 2, 'parent_id': 1, 'body': 'Visible reply'}]}


class ExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'BB_TOKEN': 'secret-test-token'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_provider_dispatch_filter_and_instance(self):
        for url, settings, target, expected in (
            (CLOUD, Settings('https://bitbucket.org'), 'cloud', ('w', 'r', '42', 'secret-test-token')),
            (SERVER, Settings('https://bb.example/bitbucket', 'name'), 'server',
             ('https://bb.example/bitbucket', 'P', 'r', '42', 'secret-test-token', 'name')),
        ):
            with self.subTest(target=target), patch(f'bb_pr_export.{target}.export_pull_request', return_value=PAYLOAD) as fetch:
                result = export_pr(settings, url)
                fetch.assert_called_once_with(*expected)
                self.assertEqual(result['comments'], PAYLOAD['comments'][1:])
                self.assertEqual(result['comments'][0]['parent_id'], 1)
        with patch('bb_pr_export.cloud.export_pull_request', return_value=PAYLOAD):
            self.assertEqual(export_pr(Settings('https://bitbucket.org', include_deleted=True), CLOUD), PAYLOAD)

    def test_no_request_to_rejected_destinations(self):
        invalid = ['42', 'https://user:secret@bb.example/projects/P/repos/r/pull-requests/1',
                   'https://evil.example/projects/P/repos/r/pull-requests/1',
                   SERVER.replace('/bitbucket/', '/other/'),
                   SERVER.replace('/repos/r/', '/repos/%2e%2e/'),
                   SERVER.replace('https:', 'http:')]
        with patch('bb_pr_export.server.export_pull_request') as server, patch('bb_pr_export.cloud.export_pull_request') as cloud:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(BitbucketExportError):
                    export_pr(Settings('https://bb.example/bitbucket'), url)
            server.assert_not_called()
            cloud.assert_not_called()

    def test_errors_hide_upstream_data(self):
        failures = [AuthError(401, 'secret-test-token', CLOUD), NotFoundError(404, 'secret-test-token', CLOUD),
                    NetworkError('secret-test-token', CLOUD), BitbucketExportError('secret-test-token')]
        for error in failures:
            with self.subTest(error=type(error)), patch('bb_pr_export.cloud.export_pull_request', side_effect=error):
                with self.assertRaises(BitbucketExportError) as caught:
                    export_pr(Settings('https://bitbucket.org'), CLOUD)
                self.assertNotIn('secret-test-token', str(caught.exception))

    def test_config_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            for text in ('[mcp]\nbase_url="https://bb.example/bitbucket"\n',
                         '[mcp]\nbase_url="https://bitbucket.org"\n'):
                path.write_text(text)
                self.assertFalse(load_settings(str(path)).include_deleted)
            for text in ('[mcp]\nbase_url="https://user:secret@bb.example"\n',
                         '[mcp]\nbase_url="https://bb.example"\ntoken="secret"\n',
                         '[mcp]\nbase_url="https://bb.example"\n[defaults]\ninclude_deleted="yes"\n'):
                path.write_text(text)
                with self.assertRaises(BitbucketExportError):
                    load_settings(str(path))

    def test_pagination_and_replies_for_both_providers(self):
        from bb_pr_export import http
        for url, settings, responses in (
            (CLOUD, Settings('https://bitbucket.org'), [
                {'id': 42}, {'values': [{'id': 1, 'deleted': True}], 'next': '?page=2'},
                {'values': [{'id': 2, 'parent': {'id': 1}, 'content': {'raw': 'reply'}}]}]),
            (SERVER, Settings('https://bb.example/bitbucket'), [
                {'id': 42}, {'values': [], 'isLastPage': False, 'nextPageStart': 100},
                {'values': [{'comment': {'id': 1, 'deleted': True, 'comments': [{'id': 2, 'text': 'reply'}]}}], 'isLastPage': True}]),
        ):
            with self.subTest(url=url), patch.object(http, 'fetch_json', side_effect=responses[1:]) as pages, \
                    patch('bb_pr_export.' + ('cloud' if url == CLOUD else 'server') + '.fetch_json', return_value=responses[0]):
                result = export_pr(settings, url)
                self.assertEqual(pages.call_count, 2)
                self.assertEqual([c['id'] for c in result['comments']], [2])
                self.assertEqual(result['comments'][0]['parent_id'], 1)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Install the optional MCP extra')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_and_structured_result(self):
        from mcp import Client
        from bb_pr_export.mcp_server import create_server
        with patch.dict(os.environ, {'BB_TOKEN': 'test'}), patch('bb_pr_export.cloud.export_pull_request', return_value=PAYLOAD):
            async with Client(create_server(Settings('https://bitbucket.org'))) as client:
                tools = (await client.list_tools()).tools
                self.assertEqual([tool.name for tool in tools], ['export_pr_comments'])
                self.assertEqual(tools[0].input_schema['required'], ['pr_url'])
                self.assertEqual(set(tools[0].input_schema['properties']), {'pr_url'})
                self.assertTrue(tools[0].annotations.read_only_hint)
                result = await client.call_tool('export_pr_comments', {'pr_url': CLOUD})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content['comments'], PAYLOAD['comments'][1:])
                self.assertEqual(json.loads(result.content[0].text), result.structured_content)
                rejected = await client.call_tool('export_pr_comments', {'pr_url': 'bad'})
                self.assertTrue(rejected.is_error)

    async def test_empty_and_unexpected_failure(self):
        from mcp import Client
        from bb_pr_export.mcp_server import create_server
        with patch.dict(os.environ, {'BB_TOKEN': 'secret'}):
            async with Client(create_server(Settings('https://bitbucket.org'))) as client:
                with patch('bb_pr_export.cloud.export_pull_request', return_value={**PAYLOAD, 'comments': []}):
                    result = await client.call_tool('export_pr_comments', {'pr_url': CLOUD})
                    self.assertEqual(result.structured_content['comments'], [])
                with patch('bb_pr_export.cloud.export_pull_request', side_effect=RuntimeError('secret')):
                    result = await client.call_tool('export_pr_comments', {'pr_url': CLOUD})
                    self.assertTrue(result.is_error)
                    self.assertNotIn('secret', result.content[0].text)
