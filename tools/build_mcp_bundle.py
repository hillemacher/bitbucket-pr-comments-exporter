"""Build the source-free MCP launcher bundle for a published image digest."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
IMAGE_RE = re.compile(r"ghcr\.io/hillemacher/bitbucket-pr-mcp@sha256:[0-9a-f]{64}")


def build_bundle(output: Path, image: str) -> Path:
    if not IMAGE_RE.fullmatch(image):
        raise ValueError('image must be the published bitbucket-pr-mcp SHA-256 digest reference')
    launcher = (ROOT / 'container/bitbucket-pr-mcp.sh').read_text(encoding='utf-8')
    launcher, count = re.subn(r'^DEFAULT_IMAGE="[^"\n]+"$', f'DEFAULT_IMAGE="{image}"', launcher, flags=re.MULTILINE)
    if count != 1:
        raise ValueError('expected exactly one launcher DEFAULT_IMAGE')
    files = [
        ('container/bitbucket-pr-mcp.sh', launcher.encode(), 0o755),
        ('bitbucket-pr-mcp-howto_EN.md', (ROOT / 'docs/bitbucket-pr-mcp-howto_EN.md').read_bytes(), 0o644),
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
    parser.add_argument('--image', required=True, help='Published multi-platform digest reference')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/bitbucket-pr-mcp.zip')
    args = parser.parse_args(argv)
    try:
        output = build_bundle(args.output, args.image)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Bundle failed: {exc}\n')
    print(f'Wrote {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
