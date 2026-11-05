"""Verify the shipped launcher needs no source files and pins an exact image."""
import os
import contextlib
import io
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools.build_mcp_bundle import ROOT, build_bundle, main


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
                self.assertNotIn('Unpublished preview', archive.read(
                    'bitbucket-pr-mcp/bitbucket-pr-mcp-howto_EN.md').decode())
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

    def test_preview_contains_only_guide_launcher_and_license(self):
        with (ROOT / 'pyproject.toml').open('rb') as metadata:
            version = tomllib.load(metadata)['project']['version']
        image = f'ghcr.io/hillemacher/bitbucket-pr-mcp:{version}'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = build_bundle(root / 'preview.zip', preview=True)
            with ZipFile(bundle) as archive:
                self.assertEqual(set(archive.namelist()), {
                    'bitbucket-pr-mcp/container/bitbucket-pr-mcp.sh',
                    'bitbucket-pr-mcp/bitbucket-pr-mcp-howto_EN.md',
                    'bitbucket-pr-mcp/LICENSE',
                })
                launcher = archive.getinfo('bitbucket-pr-mcp/container/bitbucket-pr-mcp.sh')
                self.assertTrue((launcher.external_attr >> 16) & stat.S_IXUSR)
                self.assertIn(f'DEFAULT_IMAGE="{image}"', archive.read(launcher).decode())
                guide = archive.read('bitbucket-pr-mcp/bitbucket-pr-mcp-howto_EN.md').decode()
                self.assertTrue(guide.startswith('# Unpublished preview'))
                self.assertIn('unavailable until publication', guide)
                self.assertIn('Regenerate the final release ZIP', guide)
                archive.extractall(root / 'extracted')
            env = {k: v for k, v in os.environ.items() if k not in ('BB_MCP_IMAGE', 'BB_MCP_PORT')}
            result = subprocess.run([
                '/bin/bash', str(root / 'extracted/bitbucket-pr-mcp/container/bitbucket-pr-mcp.sh'),
                '--help',
            ], cwd=root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(image, result.stdout)

    def test_cli_requires_exactly_one_mode_and_selects_default_output(self):
        image = 'ghcr.io/hillemacher/bitbucket-pr-mcp@sha256:' + 'b' * 64
        for arguments in ([], ['--preview', '--image', image]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(arguments)
                self.assertEqual(error.exception.code, 2)
        for arguments, name, reference, preview in (
            (['--preview'], 'bitbucket-pr-mcp-preview.zip', None, True),
            (['--image', image], 'bitbucket-pr-mcp.zip', image, False),
            (['--preview', '--output', 'custom.zip'], 'custom.zip', None, True),
        ):
            with self.subTest(arguments=arguments), patch(
                'tools.build_mcp_bundle.build_bundle'
            ) as builder, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
                expected = Path(name) if name == 'custom.zip' else ROOT / 'dist' / name
                builder.assert_called_once_with(expected, reference, preview=preview)

    def test_preview_cannot_be_combined_with_release_image(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'bundle.zip'
            output.write_bytes(b'existing')
            with self.assertRaises(ValueError):
                build_bundle(output, 'ghcr.io/hillemacher/bitbucket-pr-mcp@sha256:' + 'a' * 64,
                             preview=True)
            self.assertEqual(output.read_bytes(), b'existing')
