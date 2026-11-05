"""Execute the candidate workflow's Python steps offline with fake CI inputs."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


def workflow_scripts():
    source = (ROOT / '.github/workflows/candidate.yml').read_text()
    return [textwrap.dedent(script) for script in re.findall(
        r"          python - <<'PYTHON'\n(.*?)          PYTHON\n", source, re.S
    )]


class CandidateWorkflowTests(unittest.TestCase):
    def test_anonymous_pulls_handle_single_platform_digest_store(self):
        source = (ROOT / '.github/workflows/candidate.yml').read_text()
        step = source.split('      - name: Verify public downloads without credentials\n', 1)[1]
        script = textwrap.dedent(step.split('        run: |\n', 1)[1].split('      - name:', 1)[0])
        fake = '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == '--config'
config = Path(args[1])
assert config.is_dir() and not (config / 'config.json').exists()
state = Path(os.environ['FAKE_STATE'])
log = Path(os.environ['FAKE_LOG'])
with log.open('a') as output:
    output.write(json.dumps(args) + '\\n')
if args[2] == 'pull':
    if state.exists() or os.environ.get('FAIL_PULL'):
        sys.exit('cannot overwrite digest')
    state.write_text(args[-1])
elif args[2:4] == ['image', 'rm']:
    assert state.read_text() == args[-1]
    state.unlink()
else:
    sys.exit('unexpected Docker operation')
'''
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                docker = root / 'docker'
                docker.write_text('#!' + sys.executable + '\n' + fake)
                docker.chmod(0o755)
                image = 'ghcr.io/hillemacher/bitbucket-pr-mcp@sha256:' + 'a' * 64
                env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                       'IMAGE_REF': image, 'FAKE_STATE': str(root / 'state'),
                       'FAKE_LOG': str(root / 'log'), 'FAIL_PULL': '1' if fail else ''}
                result = subprocess.run(['/bin/bash', '-e', '-c', script], cwd=root,
                                        env=env, capture_output=True, text=True, timeout=10)
                calls = [json.loads(line) for line in (root / 'log').read_text().splitlines()]
                self.assertFalse(Path(calls[0][1]).exists(), 'temporary configuration was not cleaned up')
                self.assertEqual(result.returncode == 0, not fail, result.stderr)
                if fail:
                    self.assertEqual(len(calls), 1)
                else:
                    self.assertEqual([call[2:] for call in calls], [
                        ['pull', '--platform', 'linux/amd64', image],
                        ['image', 'rm', image],
                        ['pull', '--platform', 'linux/arm64', image],
                    ])

    def test_validation_accepts_candidate_and_rejects_invalid_ci_inputs(self):
        validation, _ = workflow_scripts()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pyproject.toml').write_text('[project]\nversion = "0.1.0"\n')
            output = root / 'output'
            env = {**os.environ, 'CANDIDATE_TAG': 'mcp-candidate-001',
                   'GITHUB_SHA': 'a' * 40, 'GITHUB_OUTPUT': str(output)}
            result = subprocess.run([sys.executable, '-c', validation], cwd=root,
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), 'version=0.1.0\n')
            for invalid in ({'CANDIDATE_TAG': 'v0.1.0'},
                            {'CANDIDATE_TAG': 'mcp-candidate-'},
                            {'CANDIDATE_TAG': 'mcp-candidate-001\nextra'},
                            {'GITHUB_SHA': 'short'}):
                with self.subTest(invalid=invalid):
                    result = subprocess.run([sys.executable, '-c', validation], cwd=root,
                                            env={**env, **invalid}, capture_output=True,
                                            text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(output.read_text(), 'version=0.1.0\n')

    def test_provenance_records_published_digest_and_source(self):
        _, provenance = workflow_scripts()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'dist').mkdir()
            image = 'ghcr.io/hillemacher/bitbucket-pr-mcp'
            reference = image + '@sha256:' + 'b' * 64
            env = {**os.environ, 'CANDIDATE_TAG': 'mcp-candidate-001',
                   'GITHUB_SHA': 'a' * 40, 'VERSION': '0.1.0', 'IMAGE': image,
                   'IMAGE_REF': reference, 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
            result = subprocess.run([sys.executable, '-c', provenance], cwd=root,
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = json.loads((root / 'dist/candidate.json').read_text())
            self.assertEqual(metadata, {
                'candidate_tag': 'mcp-candidate-001', 'source_commit': 'a' * 40,
                'package_version': '0.1.0', 'image_tag': image + ':candidate-' + 'a' * 40,
                'image_ref': reference, 'platforms': ['linux/amd64', 'linux/arm64'],
            })
            self.assertIn(reference, (root / 'summary').read_text())
