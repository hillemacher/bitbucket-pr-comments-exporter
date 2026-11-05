"""Verify the shipped launcher needs no source files and pins an exact image."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from zipfile import ZipFile

from tools.build_mcp_bundle import build_bundle


class MCPBundleTests(unittest.TestCase):
    def test_bundle_is_source_free_executable_and_digest_pinned(self):
        image = 'ghcr.io/hillemacher/bitbucket-pr-mcp@sha256:' + 'a' * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = build_bundle(root / 'bundle.zip', image)
            with ZipFile(bundle) as archive:
                self.assertEqual(set(archive.namelist()), {
                    'bitbucket-pr-mcp/container/bitbucket-pr-mcp.sh',
                    'bitbucket-pr-mcp/bitbucket-pr-mcp-howto_EN.md',
                    'bitbucket-pr-mcp/LICENSE',
                })
                member = archive.getinfo('bitbucket-pr-mcp/container/bitbucket-pr-mcp.sh')
                self.assertTrue((member.external_attr >> 16) & stat.S_IXUSR)
                script = archive.read(member).decode()
                self.assertIn(f'DEFAULT_IMAGE="{image}"', script)
                archive.extractall(root / 'extracted')
            launcher = root / 'extracted/bitbucket-pr-mcp/container/bitbucket-pr-mcp.sh'
            env = {k: v for k, v in os.environ.items() if k not in ('BB_MCP_IMAGE', 'BB_MCP_PORT')}
            result = subprocess.run(['/bin/bash', str(launcher), '--help'], cwd=root,
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(image, result.stdout)

    def test_invalid_image_does_not_replace_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'bundle.zip'
            output.write_bytes(b'existing')
            for image in ('latest', 'ghcr.io/hillemacher/bitbucket-pr-mcp:0.1.0',
                          'ghcr.io/hillemacher/bitbucket-pr-mcp@sha256:' + 'g' * 64):
                with self.subTest(image=image), self.assertRaises(ValueError):
                    build_bundle(output, image)
                self.assertEqual(output.read_bytes(), b'existing')
