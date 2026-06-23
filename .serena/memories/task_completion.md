# Task Completion

- Required verification for code changes: `python -m unittest discover`.
- For CLI surface changes, also run relevant help smoke checks:
  - `python -m bb_pr_export.cli --help`
  - `python -m bb_pr_export.cli cloud --help`
  - `python -m bb_pr_export.cli server --help`
- For config/URL behavior changes, add or update tests in `tests/test_cli.py`; avoid live API calls.
- For renderer changes, update `tests/test_renderer.py` with fixed normalized dict fixtures.
- For HTTP behavior changes, update `tests/test_http.py` with `unittest.mock.patch` around `urllib.request.urlopen`.
- Update `README.md` and `bb-export.example.toml` when user-facing CLI/config behavior changes.
- No linter, formatter, type checker, or CI config is currently defined in the repo.