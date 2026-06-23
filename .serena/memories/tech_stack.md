# Tech Stack

- Python 3.11+ only; `pyproject.toml` sets `requires-python = ">=3.11"`.
- Packaging: setuptools build backend, package discovery for `bb_pr_export*`.
- Runtime dependencies: none beyond Python standard library.
- Important stdlib modules in use:
  - `argparse` for CLI.
  - `urllib.request` / `urllib.error` / `urllib.parse` for HTTP and URL parsing.
  - `json` for API payloads and normalized JSON output.
  - `tomllib` for config files; requires Python 3.11+.
  - `unittest` and `unittest.mock` for tests.
- Console script: `bb-export` maps to `bb_pr_export.cli:main`.
- No `requests`, `httpx`, pytest, ruff, mypy, or formatter config currently exists.