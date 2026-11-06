"""Publication and security gate regression checks; no scanner/network required."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import security_check


class PublicationTests(unittest.TestCase):
    def test_sensitive_generated_paths_are_ignored_but_example_is_publishable(self):
        root = Path(__file__).resolve().parents[1]
        # Source distributions and Docker test copies have no Git metadata.
        if not (root / '.git').exists():
            self.skipTest('requires checkout metadata')
        paths = ['bitbucket.pat', '.bitbucket-pr-mcp/config.toml',
                 '.setup-token.fixture', 'pr_42_comments.md',
                 'pr_42_comments.json', 'exports/review.json']
        result = subprocess.run(['git', 'check-ignore', '--no-index', *paths, 'bb-export.example.toml'],
                                cwd=root, capture_output=True, text=True, check=False)
        self.assertEqual(set(result.stdout.splitlines()), set(paths))

    @patch('tools.security_check.run_scanner', side_effect=[1, 0])
    def test_secret_findings_fail_gate_and_both_surfaces_are_scanned(self, scanner):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'fixture.txt').write_text('fixture')
            self.assertNotEqual(security_check.scan_secrets(root, root), 0)
        self.assertEqual(scanner.call_count, 2)
        self.assertIn('--log-opts=--all', scanner.call_args_list[0].args)
        self.assertIn('--max-archive-depth=4', scanner.call_args_list[1].args)
        self.assertTrue(all('--redact' in call.args for call in scanner.call_args_list))

    @patch('tools.security_check.subprocess.run')
    def test_scanners_receive_no_socket_credentials_or_writable_source(self, run):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            security_check.run_scanner(security_check.GITLEAKS, [(source, '/repo', False)], 'git', '/repo')
        command = run.call_args.args[0]
        self.assertIn(f'{source}:/repo:ro', command)
        self.assertFalse(any('docker.sock' in arg or 'BB_TOKEN' in arg for arg in command))
        self.assertIn('--cap-drop=ALL', command)

    @patch('tools.security_check.subprocess.run')
    @patch('tools.security_check.run_scanner', side_effect=[0, 0, 1])
    def test_image_gate_keeps_report_and_sbom_and_propagates_findings(self, scanner, run):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / '.image.tar').write_text('fixture')
            self.assertEqual(security_check.scan_image('fixture-image', output), 1)
            self.assertFalse((output / '.image.tar').exists())
        commands = [call.args for call in scanner.call_args_list]
        self.assertIn('--format=json', commands[0])
        self.assertIn('--format=cyclonedx', commands[1])
        self.assertIn('--severity=HIGH,CRITICAL', commands[2])
        self.assertFalse(any('--ignore-unfixed' in arg for command in commands for arg in command))


class ReleasePolicyTests(unittest.TestCase):
    def test_release_and_candidate_require_scans_before_upload(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('candidate', 'release'):
            source = (root / '.github/workflows' / (name + '.yml')).read_text()
            self.assertIn('uses: ./.github/workflows/security.yml', source)
            self.assertIn('needs: security', source)
            self.assertLess(source.index('Scan image before upload'), source.index('docker push'))
            self.assertIn('if: always()', source)
            self.assertIn('dist/image-security/sbom.cdx.json', source)

    def test_workflow_actions_are_sha_pinned(self):
        import re
        root = Path(__file__).resolve().parents[1]
        for path in (root / '.github/workflows').glob('*.yml'):
            for action in re.findall(r'uses: ([^\s]+)', path.read_text()):
                if not action.startswith('./'):
                    self.assertRegex(action, r'^[^@]+@[0-9a-f]{40}$', str(path))


class ArtifactExpansionTests(unittest.TestCase):
    def test_wheels_are_expanded_and_member_paths_cannot_escape(self):
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, output = root / 'inputs', root / 'expanded'
            inputs.mkdir(); output.mkdir()
            with ZipFile(inputs / 'fixture.whl', 'w') as archive:
                archive.writestr('../../outside.py', 'sensitive fixture text')
            manifest = security_check.expand_artifacts(inputs, output)
            self.assertEqual(list(manifest.values()), ['fixture.whl!../../outside.py'])
            self.assertEqual((output / '00000.txt').read_text(), 'sensitive fixture text')
            self.assertFalse((root / 'outside.py').exists())

    def test_symlink_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / 'output'; output.mkdir()
            (root / 'link').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                security_check.expand_artifacts(root, output)
