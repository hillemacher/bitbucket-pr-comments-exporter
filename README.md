# Bitbucket PR Comments Exporter

Bitbucket PR Comments Exporter is a self-contained Python CLI that exports pull request metadata, review outcomes, inline comments, general comments, and replies from Bitbucket Cloud or Bitbucket Server/Data Center into a clean Markdown file suitable for LLM context, or into normalized JSON for programmatic use.

## Installation

```bash
pip install .
```

or:

```bash
pipx install .
```

## Quickstart

Bitbucket Cloud:

```bash
bb-export cloud --workspace WORKSPACE --repo REPO --pr 42 --token APP_PASSWORD
bb-export cloud --url https://bitbucket.org/WORKSPACE/REPO/pull-requests/42 --token APP_PASSWORD
```

Bitbucket Server/Data Center:

```bash
bb-export server --server https://bitbucket.example.com --project PROJECT --repo REPO --pr 42 --username USERNAME --token TOKEN
bb-export server --url https://bitbucket.example.com/projects/PROJECT/repos/REPO/pull-requests/42/overview --username USERNAME --token TOKEN
```

You can also provide secrets with environment variables:

```bash
BB_TOKEN=APP_PASSWORD bb-export cloud --workspace WORKSPACE --repo REPO --pr 42
BB_USERNAME=USERNAME BB_TOKEN=TOKEN bb-export server --server https://bitbucket.example.com --project PROJECT --repo REPO --pr 42
```

Use `--output FILE` to choose the destination, `--include-deleted` to include deleted comments as `~~[deleted]~~`, and `--format json` to write normalized JSON instead of Markdown.

## Config File

You can save non-secret defaults in TOML. By default, the tool looks for `./bb-export.toml`, then `~/.config/bb-export/config.toml`. Pass `--config PATH` to use a specific file.

See [`bb-export.example.toml`](bb-export.example.toml) for a commented config file explaining each section. A minimal Server/Data Center config looks like this:

```toml
[server]
server = "https://bitbucket.CompanyX"
project = "CoolP"
repo = "SomeRepo"
username = "your.username"

[defaults]
output_dir = "exports"
format = "md"
include_deleted = false
```

Then export a PR with only the changing value:

```bash
BB_TOKEN=TOKEN bb-export server --config bb-export.toml --pr 500
```

CLI flags override values parsed from `--url`; URL values override config; config fills missing defaults. Tokens and app passwords are never read from config files. Use `--token` or `BB_TOKEN`.

## Tokens

For Bitbucket Cloud, generate an app password with Pull Requests: Read permission. See: Bitbucket Cloud app passwords.

For Bitbucket Server/Data Center, generate a personal access token with pull request read access. See: Bitbucket Server personal access tokens.

## Output Format

The Markdown output starts with PR title, author, state, branch direction, creation date, and description. It then includes a review outcome table when reviewer decisions are available, followed by inline comments grouped by file and line, then general comments. Replies are nested under their parent comment.

The resulting `.md` file is designed to be pasted or attached as LLM context when asking for a review summary, unresolved issue list, implementation follow-up plan, or risk analysis.

## Why No External Dependencies?

The exporter uses only the Python standard library so it is easy to audit, simple to install, and safe to run locally in restricted environments. No data leaves your machine except requests sent directly to the Bitbucket API you configure.
