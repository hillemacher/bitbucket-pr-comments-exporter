"""Run digest-pinned scanners without mounting the Docker socket or credentials.

Examples:
  python tools/security_check.py secrets --artifacts dist/security-artifacts --output dist/security-reports
  python tools/security_check.py image IMAGE --output dist/security-reports
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from zipfile import ZipFile, is_zipfile

ROOT = Path(__file__).resolve().parents[1]
GITLEAKS = 'ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9'
TRIVY = 'aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c'


def run_scanner(image: str, mounts: list[tuple[Path, str, bool]], *arguments: str) -> int:
    command = ['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
               '--cap-drop=ALL', '--security-opt=no-new-privileges']
    for source, destination, writable in mounts:
        command.extend(['-v', f'{source}:{destination}' + ('' if writable else ':ro')])
    # git sees a read-only bind owned by a different ID on some Docker hosts.
    # This names only the checked-out repository; no host Git config is mounted.
    if image == GITLEAKS:
        command.extend(['--network=none', '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory',
                        '-e', 'GIT_CONFIG_VALUE_0=/repo'])
    return subprocess.run([*command, image, *arguments], check=False).returncode


def scan_secrets(artifacts: Path, output: Path) -> int:
    common = ['--redact', '--report-format=json', '--no-banner']
    history = run_scanner(GITLEAKS, [(ROOT, '/repo', False), (output, '/out', True)],
                          'git', '/repo', '--log-opts=--all',
                          '--report-path=/out/history-secrets.json', *common)
    # Scanners do not reliably expand every archive extension (notably .whl).
    # Expand ourselves to anonymous files, without trusting archive member paths.
    with tempfile.TemporaryDirectory(prefix='bb-publication-') as directory:
        expanded = Path(directory)
        manifest = expand_artifacts(artifacts, expanded)
        (output / 'artifact-members.json').write_text(json.dumps(manifest, indent=2) + '\n')
        files = run_scanner(GITLEAKS, [(expanded, '/artifacts', False), (output, '/out', True)],
                            'dir', '/artifacts', '--max-archive-depth=4',
                            '--report-path=/out/artifact-secrets.json', *common)
    return history or files


def expand_artifacts(artifacts: Path, output: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    total = 0
    maximum = 32 * 1024 * 1024

    def visit(data: bytes, label: str, depth: int) -> None:
        nonlocal total
        total += len(data)
        if len(data) > maximum or total > 256 * 1024 * 1024 or len(manifest) >= 10000:
            raise ValueError('Artifact scan size/member limit exceeded')
        stream = io.BytesIO(data)
        if is_zipfile(stream):
            if depth >= 4:
                raise ValueError('Artifact archive nesting limit exceeded')
            with ZipFile(stream) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    if member.file_size > maximum:
                        raise ValueError('Artifact member size limit exceeded')
                    visit(archive.read(member), label + '!' + member.filename, depth + 1)
            return
        stream.seek(0)
        try:
            archive = tarfile.open(fileobj=stream, mode='r:*')
        except tarfile.ReadError:
            pass
        else:
            with archive:
                if depth >= 4:
                    raise ValueError('Artifact archive nesting limit exceeded')
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile() or member.size > maximum:
                        raise ValueError('Unsafe artifact member type or size')
                    with archive.extractfile(member) as source:
                        visit(source.read(maximum + 1), label + '!' + member.name, depth + 1)
            return
        name = f'{len(manifest):05d}.txt'
        (output / name).write_bytes(data)
        manifest[name] = label

    for path in sorted(artifacts.rglob('*')):
        if path.is_symlink():
            raise ValueError('Artifact inputs must not contain symlinks')
        if path.is_file():
            with path.open('rb') as source:
                visit(source.read(maximum + 1), str(path.relative_to(artifacts)), 0)
    if not manifest:
        raise ValueError('No artifact contents to scan')
    return manifest


def scan_image(image: str, output: Path) -> int:
    archive = output / '.image.tar'
    try:
        subprocess.run(['docker', 'image', 'save', '-o', str(archive), image], check=True)
        mounts = [(output, '/scan', True)]
        cache = ['--cache-dir=/scan/trivy-cache']
        status = run_scanner(TRIVY, mounts, 'image', *cache, '--input=/scan/.image.tar',
                             '--scanners=vuln', '--list-all-pkgs', '--format=json',
                             '--output=/scan/vulnerabilities.json')
        if status:
            return status
        status = run_scanner(TRIVY, mounts, 'convert', '--format=cyclonedx',
                             '--output=/scan/sbom.cdx.json', '/scan/vulnerabilities.json')
        if status:
            return status
        # Retain the full report, including unfixed/low/medium findings. No blanket
        # ignore-unfixed switch or unreviewed exception file is applied.
        return run_scanner(TRIVY, mounts, 'convert', '--format=table', '--severity=HIGH,CRITICAL',
                           '--exit-code=1', '/scan/vulnerabilities.json')
    finally:
        archive.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    secrets = commands.add_parser('secrets')
    secrets.add_argument('--artifacts', required=True, type=Path)
    image = commands.add_parser('image')
    image.add_argument('image')
    for command in (secrets, image):
        command.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.command == 'secrets':
        artifacts = args.artifacts.resolve(strict=True)
        if not artifacts.is_dir() or output == artifacts or artifacts in output.parents:
            parser.error('artifacts must be a directory separate from scanner output')
        return scan_secrets(artifacts, output)
    return scan_image(args.image, output)


if __name__ == '__main__':
    raise SystemExit(main())
