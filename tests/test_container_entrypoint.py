import importlib.util
import io
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
    def test_initial_setup_guidance_keeps_examples_out_of_config(self):
        for base in ('https://bb.internal/bitbucket', 'https://bitbucket.org'):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as directory, \
                    patch.object(entry, 'CONFIG', Path(directory)), \
                    patch.dict(os.environ, {'BB_TOKEN': 'secret-fixture'}, clear=True), \
                    patch('builtins.input', side_effect=[base, '']) as prompts, \
                    patch.object(entry.getpass, 'getpass') as hidden_input, \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                entry.setup(False)
                settings = entry.load_settings(str(Path(directory) / 'config.toml'))
                self.assertEqual(settings.base_url, base)
                self.assertIsNone(settings.username)
                text = output.getvalue()
                for guidance in ('https://bitbucket.example.com/bitbucket', 'https://bitbucket.org',
                                 'context path', 'jane.doe', 'Basic authentication', 'Bearer/PAT',
                                 'separately from config.toml', 'Using the token supplied by BB_TOKEN'):
                    self.assertIn(guidance, text)
                self.assertNotIn('secret-fixture', text)
                hidden_input.assert_not_called()
                self.assertEqual(prompts.call_count, 2)
                self.assertNotIn('Configure default repository', text)

    def test_token_rotation_guidance_and_repeat_setup(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), \
                patch.dict(os.environ, {}, clear=True), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            (Path(directory) / 'config.toml').write_text('[server]\nserver="https://bb.internal"\n')
            (Path(directory) / 'bitbucket.pat').write_text('old-secret')
            with patch('builtins.input') as prompts, \
                    patch.object(entry.getpass, 'getpass', return_value='rotated-secret') as hidden_input:
                entry.setup(True)
                hidden_input.assert_called_once_with('Bitbucket PAT (hidden): ')
                prompts.assert_not_called()
            text = output.getvalue()
            self.assertIn('input is hidden', text)
            self.assertIn('separately from config.toml', text)
            self.assertNotIn('Base URL examples', text)
            self.assertNotIn('repository defaults let you', text)
            self.assertNotIn('Using the token supplied by BB_TOKEN', text)
            self.assertNotIn('rotated-secret', text)
            self.assertNotIn('old-secret', text)
            output.seek(0)
            output.truncate(0)
            entry.setup(False)
            self.assertNotIn('The token is saved', output.getvalue())
            self.assertNotIn('rotated-secret', output.getvalue())

    def test_setup_preserves_configuration_and_rotates_token_atomically(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), \
                patch.dict(os.environ, {'BB_TOKEN': 'fixture-first'}), patch('builtins.input', side_effect=['https://bitbucket.org', '']):
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

    def test_existing_legacy_config_and_comments_are_preserved(self):
        original = ('# personal settings\n[cloud]\nworkspace="old"\nrepo="old"\n'
                    '[defaults]\ninclude_deleted=true # retain\n[custom]\nvalue=123\n')
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), \
                patch.dict(os.environ, {}, clear=True), patch('builtins.input') as prompts:
            path = Path(directory) / 'config.toml'
            path.write_text(original)
            token = Path(directory) / 'bitbucket.pat'
            token.write_text('fixture')
            entry.setup(False)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(token.read_text(), 'fixture')
            self.assertEqual(entry.preflight().base_url, 'https://bitbucket.org')
            self.assertTrue(entry.preflight().include_deleted)
            prompts.assert_not_called()

    def test_failed_write_retains_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('original')
            with patch.object(entry.os, 'replace', side_effect=OSError('fixture failure')):
                with self.assertRaises(OSError):
                    entry.write_private(path, 'replacement')
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['config.toml'])

    def test_url_check_routes_to_shared_resolver(self):
        settings = entry.settings_from_config({'mcp': {'base_url': 'https://bitbucket.org'}})
        url = 'https://bitbucket.org/w/r/pull-requests/42'
        with patch.object(entry, 'export_pr', return_value={'comments': [], 'reviewers': []}) as export:
            entry.check(settings, url)
            export.assert_called_once_with(settings, url)
        with patch('bb_pr_export.cloud.export_pull_request') as fetch, self.assertRaises(BitbucketExportError):
            entry.check(settings, '42')
        fetch.assert_not_called()

    def test_invalid_existing_config_preserves_files_on_token_rotation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(entry, 'CONFIG', Path(directory)), \
                patch.dict(os.environ, {'BB_TOKEN': 'replacement'}):
            path = Path(directory) / 'config.toml'
            original = '[mcp]\nbase_url="invalid"\n'
            path.write_text(original)
            token = Path(directory) / 'bitbucket.pat'
            token.write_text('original')
            with self.assertRaises(BitbucketExportError):
                entry.setup(True)
            self.assertEqual(path.read_text(), original)
            self.assertEqual(token.read_text(), 'original')
