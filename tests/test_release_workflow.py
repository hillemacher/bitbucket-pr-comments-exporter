"""Run the stable release workflow's publish step offline with fake tools."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/hillemacher/bitbucket-pr-mcp'
DIGEST = 'sha256:' + 'b' * 64


def step_script(name):
    source = (ROOT / '.github/workflows/release.yml').read_text()
    step = source.split(f'      - name: {name}\n', 1)[1]
    return textwrap.dedent(step.split('        run: |\n', 1)[1].split('      - name:', 1)[0])


class ReleaseWorkflowTests(unittest.TestCase):
    def run_publish(self, ref, tags):
        script = step_script('Publish combined manifest and bundle')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            (root / 'dist').mkdir()
            shebang = '#!' + sys.executable + '\n'
            (bin_dir / 'docker').write_text(shebang + (
                "import json, os, sys\n"
                "args = sys.argv[1:]\n"
                "open(os.environ['FAKE_LOG'], 'a').write(json.dumps(args) + '\\n')\n"
                "if args[:3] == ['buildx', 'imagetools', 'inspect']:\n"
                f"    print('{DIGEST}')\n"
            ))
            (bin_dir / 'git').write_text(shebang + (
                "import os\nprint(os.environ['FAKE_TAGS'])\n"
            ))
            (bin_dir / 'python').write_text(shebang)
            for tool in bin_dir.iterdir():
                tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
                   'IMAGE': IMAGE, 'VERSION': ref.lstrip('v'), 'GITHUB_REF_NAME': ref,
                   'GITHUB_SHA': 'c' * 40, 'GITHUB_ENV': str(root / 'env'),
                   'FAKE_LOG': str(root / 'log'), 'FAKE_TAGS': tags}
            result = subprocess.run(['/bin/bash', '-e', '-c', script], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in (root / 'log').read_text().splitlines()]
            env_file = root / 'env'
            return calls, env_file.read_text() if env_file.exists() else ''

    def test_highest_stable_tag_also_publishes_latest(self):
        calls, env = self.run_publish('v0.2.0', 'v0.1.0\nv0.1.1\nv0.2.0\nv0.10.0-rc1\n')
        create = calls[0]
        self.assertEqual(create[:3], ['buildx', 'imagetools', 'create'])
        self.assertEqual(create[3:7], ['-t', f'{IMAGE}:0.2.0', '-t', f'{IMAGE}:latest'])
        self.assertIn('PUBLISH_LATEST=1', env)

    def test_version_sort_is_numeric(self):
        calls, _ = self.run_publish('v0.10.0', 'v0.9.0\nv0.10.0\n')
        self.assertIn(f'{IMAGE}:latest', calls[0])

    def test_older_hotfix_does_not_move_latest(self):
        calls, env = self.run_publish('v0.1.1', 'v0.1.0\nv0.1.1\nv0.2.0\n')
        self.assertNotIn(f'{IMAGE}:latest', calls[0])
        self.assertIn(f'{IMAGE}:0.1.1', calls[0])
        self.assertNotIn('PUBLISH_LATEST', env)

    def test_bundle_is_pinned_to_versioned_digest_not_latest(self):
        script = step_script('Publish combined manifest and bundle')
        self.assertIn('inspect "$IMAGE:$VERSION"', script)
        self.assertIn('--image "$IMAGE@$digest"', script)

    def test_verification_checks_latest_matches_version(self):
        script = step_script('Verify public downloads without credentials')
        self.assertIn('PUBLISH_LATEST', script)
        self.assertIn('manifest_digest latest', script)


if __name__ == '__main__':
    unittest.main()
