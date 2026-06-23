# Core

- Fresh Python CLI project for exporting Bitbucket pull request comments to Markdown or normalized JSON.
- Package root: `bb_pr_export/`.
- Entry point: `bb-export = bb_pr_export.cli:main` in `pyproject.toml`.
- Main modules:
  - `bb_pr_export/cli.py`: argparse CLI, config loading, PR URL parsing, option precedence, output path creation, error-to-exit-code handling.
  - `bb_pr_export/http.py`: urllib helpers, auth headers, JSON fetch, Cloud/Server pagination, retry and typed errors.
  - `bb_pr_export/cloud.py`: Bitbucket Cloud API client and normalization.
  - `bb_pr_export/server.py`: Bitbucket Server/Data Center API client and normalization.
  - `bb_pr_export/renderer.py`: Markdown and JSON renderers for normalized export data.
- Docs/config artifacts: `README.md`, `bb-export.example.toml`.
- Tests live in `tests/` and use only stdlib `unittest`/`unittest.mock`.
- Read `mem:tech_stack` for runtime/build constraints, `mem:conventions` for project-specific behavior rules, `mem:suggested_commands` for useful commands, and `mem:task_completion` before finishing coding tasks.