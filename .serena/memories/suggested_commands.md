# Suggested Commands

- Run all tests: `python -m unittest discover`.
- CLI help without installing: `python -m bb_pr_export.cli --help`.
- Subcommand help:
  - `python -m bb_pr_export.cli cloud --help`
  - `python -m bb_pr_export.cli server --help`
- Install locally for console script testing: `pip install .`.
- Install as an isolated CLI: `pipx install .`.
- Example Server/DC run with env token: `BB_TOKEN=TOKEN python -m bb_pr_export.cli server --url https://bitbucket.example.com/projects/PROJECT/repos/REPO/pull-requests/42/overview`.
- Example Cloud run with env token: `BB_TOKEN=APP_PASSWORD python -m bb_pr_export.cli cloud --url https://bitbucket.org/WORKSPACE/REPO/pull-requests/42`.
- Repo search preference: use `rg` / `rg --files` when available.