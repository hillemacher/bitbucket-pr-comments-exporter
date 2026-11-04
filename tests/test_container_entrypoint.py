import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bb_pr_export.http import BitbucketExportError

spec = importlib.util.spec_from_file_location('bb_container', Path(__file__).resolve().parents[1] / 'container/entrypoint.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@unittest.skipUnless(importlib.util.find_spec('tomlkit'), 'Install the optional MCP extra')
class ContainerEntrypointTests(unittest.TestCase):
    def test_setup_preserves_configuration_and_rotates_token_atomically(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), \
                patch.dict(os.environ, {'BB_TOKEN': 'fixture-first'}), patch('builtins.input', side_effect=['https://bitbucket.org', '', '']):
            entry.setup(False)
            config = (Path(directory) / 'config.toml').read_bytes()
            os.environ['BB_TOKEN'] = 'fixture-second'
            entry.setup(False)
            self.assertEqual((Path(directory) / 'bitbucket.pat').read_text().strip(), 'fixture-first')
            os.environ['BB_TOKEN'] = 'fixture-second'
            entry.setup(True)
            self.assertEqual((Path(directory) / 'bitbucket.pat').read_text().strip(), 'fixture-second')
            self.assertEqual((Path(directory) / 'config.toml').read_bytes(), config)
            for name in ('config.toml', 'bitbucket.pat'):
                self.assertEqual((Path(directory) / name).stat().st_mode & 0o777, 0o600)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['bitbucket.pat', 'config.toml'])
            (Path(directory) / 'bitbucket.pat').write_text('bad token')
            with self.assertRaises(BitbucketExportError):
                entry.preflight()

    def test_guided_defaults_preserve_comments_and_clear_only_repository(self):
        original = '# personal settings\n[mcp]\nbase_url="https://bb.example/bitbucket"\n[server]\nusername="name" # retain\n[defaults]\nformat="md"\n[custom]\nvalue=123\n'
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / 'config.toml'
            path.write_text(original)
            token = Path(directory) / 'bitbucket.pat'
            token.write_text('fixture')
            with patch('builtins.input', side_effect=['y', 'P', 'repo']):
                entry.setup(False, True)
            settings = entry.preflight()
            self.assertEqual((settings.project, settings.repo), ('P', 'repo'))
            self.assertIn('# personal settings', path.read_text())
            self.assertIn('# retain', path.read_text())
            self.assertIn('value=123', path.read_text())
            self.assertEqual(token.read_text(), 'fixture')
            with patch('builtins.input', return_value='n'):
                entry.setup(False, True)
            self.assertIsNone(entry.preflight().repo)
            self.assertEqual(entry.preflight().username, 'name')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_failed_write_retains_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('original')
            with patch.object(entry.os, 'replace', side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):
                    entry.write_private(path, 'replacement')
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['config.toml'])

    def test_numeric_check_routes_to_shared_resolver(self):
        settings = entry.settings_from_config({'cloud': {'workspace': 'w', 'repo': 'r'}})
        with patch.object(entry, 'export_pr', return_value={'comments': [], 'reviewers': []}) as export:
            entry.check(settings, '42')
            export.assert_called_once_with(settings, pr_id=42)

    def test_initial_cloud_defaults_and_clearing_inferred_instance(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), patch.dict(os.environ, {'BB_TOKEN': 'fixture'}):
            with patch('builtins.input', side_effect=['https://bitbucket.org', '', 'y', 'workspace', 'repo']):
                entry.setup(False)
            self.assertEqual(entry.preflight().workspace, 'workspace')
            path = Path(directory) / 'config.toml'
            # An imported exporter config has no explicit MCP base URL.
            path.write_text('[cloud]\nworkspace="workspace"\nrepo="repo"\n')
            with patch('builtins.input', return_value='n'):
                entry.setup(False, True)
            settings = entry.preflight()
            self.assertEqual(settings.base_url, 'https://bitbucket.org')
            self.assertIsNone(settings.repo)

    def test_invalid_update_preserves_config_and_pat(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), patch.dict(os.environ, {'BB_TOKEN': 'replacement'}):
            path = Path(directory) / 'config.toml'
            original = '[server]\nserver="https://bb.example"\n'
            path.write_text(original)
            token = Path(directory) / 'bitbucket.pat'
            token.write_text('original')
            with patch('builtins.input', side_effect=['y', '../bad', 'repo']), self.assertRaises(BitbucketExportError):
                entry.setup(True, True)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(token.read_text(), 'original')
