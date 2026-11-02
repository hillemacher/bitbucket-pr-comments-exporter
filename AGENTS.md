# Repository Guidelines

## Project Structure & Module Organization

This repository contains a stdlib-only Python CLI for exporting Bitbucket pull request comments.

- `bb_pr_export/`: application package.
  - `cli.py`: argparse entry point, config loading, URL parsing, output handling.
  - `http.py`: urllib helpers, authentication headers, pagination, API error types.
  - `cloud.py` and `server.py`: provider-specific Bitbucket clients and normalization.
  - `renderer.py`: Markdown and normalized JSON rendering.
- `tests/`: `unittest` test suite using mocks; no live Bitbucket calls.
- `README.md`: user-facing installation and usage docs.
- `bb-export.example.toml`: commented non-secret config template.
- `pyproject.toml`: package metadata and `bb-export` console script.
- `LICENSE`: MIT license for public publication.
- `.github/workflows/test.yml`: GitHub Actions workflow running the `unittest` suite on Python 3.11 and 3.12.
- `.gitignore`: excludes local config, secrets, Python caches, virtual environments, and build outputs.

## Build, Test, and Development Commands

- `python -m unittest discover`: run the full test suite.
- `python -m bb_pr_export.cli --help`: inspect the top-level CLI without installing.
- `python -m bb_pr_export.cli cloud --help`: inspect Cloud options.
- `python -m bb_pr_export.cli server --help`: inspect Server/Data Center options.
- `pip install .`: install locally and expose the `bb-export` command.
- `pipx install .`: install the CLI in an isolated environment.

## Coding Style & Naming Conventions

Use Python 3.11+ and standard library APIs only. Prefer clear functions, type hints, and explicit error handling over framework abstractions. Use 4-space indentation, `snake_case` for functions and variables, `PascalCase` for exception classes, and module names that match their provider or responsibility. There is currently no configured formatter or linter.

## Testing Guidelines

Tests use `unittest` and `unittest.mock`. Name files `tests/test_*.py` and test classes `*Tests`. Patch provider functions or `urllib.request.urlopen`; never require real Bitbucket credentials or network access. Add CLI behavior tests in `tests/test_cli.py`, renderer fixture tests in `tests/test_renderer.py`, and HTTP pagination/error tests in `tests/test_http.py`.

## Commit & Pull Request Guidelines

Use short imperative commit messages such as `Add PR URL config support`. Pull requests should describe the behavior change, note user-facing CLI/config updates, include test results, and mention any README or example config changes.

## Security & Configuration Tips

Never store tokens, app passwords, or PATs in config files. Secrets must come from `--token` or `BB_TOKEN`; usernames may come from CLI, config, or `BB_USERNAME`. Keep `bb-export.example.toml` non-secret and update it whenever config behavior changes.
