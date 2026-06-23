# Conventions

- Keep runtime stdlib-only. Do not add third-party runtime dependencies without explicit user direction.
- Secrets invariant: tokens/app passwords/PATs come only from `--token` or `BB_TOKEN`; usernames may come from CLI/config/`BB_USERNAME`. Config must reject token-like keys.
- CLI subcommand remains explicit: `bb-export cloud ...` or `bb-export server ...`; `--url` fills identifiers but does not infer provider.
- Option precedence in `cli.py`: CLI flags > URL-derived values > config values; env fills only token and server username fallback.
- Config lookup: explicit `--config PATH` only reads that path; otherwise default search is `./bb-export.toml`, then `~/.config/bb-export/config.toml`.
- Config tables: `[cloud]`, `[server]`, `[defaults]`. `bb-export.example.toml` is the documented commented template.
- Output behavior: `--output` or config `output` is an exact file path; otherwise `output_dir` contains default filename `pr_<id>_comments.<format>`; otherwise write in cwd.
- Provider clients return normalized dictionaries with `provider`, `pr`, `reviewers`, and `comments`; renderer should not depend on raw provider-specific payloads.
- HTTP behavior: Cloud pagination follows `next`; Server/DC pagination uses `isLastPage` and `nextPageStart`; retry one transient 5xx after 2 seconds.
- Error handling favors clear stderr and exit code `1` over stack traces for expected user/API failures.
- Tests patch provider functions or `urllib.request.urlopen`; no live Bitbucket calls.