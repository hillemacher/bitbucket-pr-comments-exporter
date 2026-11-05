"""Build a source-free MCP launcher bundle for release or local preview."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
IMAGE_RE = re.compile(r"ghcr\.io/hillemacher/bitbucket-pr-mcp@sha256:[0-9a-f]{64}")


def build_bundle(output: Path, image: str | None = None, *, preview: bool = False) -> Path:
    if preview and image is not None:
        raise ValueError('choose either preview or a published image digest')
    if preview:
        with (ROOT / 'pyproject.toml').open('rb') as metadata:
            version = tomllib.load(metadata)['project']['version']
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('preview requires a stable X.Y.Z package version')
        image = f'ghcr.io/hillemacher/bitbucket-pr-mcp:{version}'
    elif image is None or not IMAGE_RE.fullmatch(image):
        raise ValueError('image must be the published bitbucket-pr-mcp SHA-256 digest reference')
    guide = (ROOT / 'docs/bitbucket-pr-mcp-howto_EN.md').read_bytes()
    if preview:
        guide = (
            '# Unpublished preview\n\n'
            f'This local review bundle targets `{image}`. '
            'The image reference is unavailable until publication. '
            'Do not run setup/start from this bundle yet. '
            'Regenerate the final release ZIP with the published multi-platform digest; '
            'this preview uses a version tag and is not a release artifact.\n\n'
        ).encode() + guide
    launcher = (ROOT / 'container/bitbucket-pr-mcp.sh').read_text(encoding='utf-8')
    launcher, count = re.subn(r'^DEFAULT_IMAGE="[^"\n]+"$', f'DEFAULT_IMAGE="{image}"', launcher, flags=re.MULTILINE)
    if count != 1:
        raise ValueError('expected exactly one launcher DEFAULT_IMAGE')
    files = [
        ('container/bitbucket-pr-mcp.sh', launcher.encode(), 0o755),
        ('bitbucket-pr-mcp-howto_EN.md', guide, 0o644),
        ('LICENSE', (ROOT / 'LICENSE').read_bytes(), 0o644),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data, mode in files:
            info = ZipInfo(f'bitbucket-pr-mcp/{name}')
            info.create_system = 3
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--image', help='Published multi-platform digest reference')
    mode.add_argument('--preview', action='store_true', help='Unpublished local review bundle using the package version tag')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    output = args.output or ROOT / 'dist' / (
        'bitbucket-pr-mcp-preview.zip' if args.preview else 'bitbucket-pr-mcp.zip'
    )
    try:
        output = build_bundle(output, args.image, preview=args.preview)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Bundle failed: {exc}\n')
    print(f'Wrote {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
