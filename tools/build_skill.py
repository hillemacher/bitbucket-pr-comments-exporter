"""Build the self-contained feedback skill from the maintained exporter source."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "bitbucket-pr-feedback"


def build_bundle(output: Path) -> Path:
    skill = ROOT / "skills" / SKILL_NAME
    files = [
        (skill / "SKILL.md", "SKILL.md"),
        (skill / "scripts" / "export_pr.py", "scripts/export_pr.py"),
        (ROOT / "LICENSE", "LICENSE"),
    ]
    for source in sorted((ROOT / "bb_pr_export").rglob("*.py")):
        relative = source.relative_to(ROOT)
        files.append((source, f"scripts/{relative.as_posix()}"))
    # Check inputs before opening an existing bundle for replacement.
    for source, _ in files:
        if not source.is_file():
            raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for source, destination in files:
            archive.write(source, f"{SKILL_NAME}/{destination}")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"{SKILL_NAME}.zip")
    args = parser.parse_args(argv)
    print(f"Wrote {build_bundle(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
