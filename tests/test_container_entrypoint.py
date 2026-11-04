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


class ContainerEntrypointTests(unittest.TestCase):
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
