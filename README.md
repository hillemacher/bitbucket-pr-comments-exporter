# Bitbucket PR Comments Exporter

[![Tests](https://github.com/hillemacher/bitbucket-pr-comments-exporter/actions/workflows/test.yml/badge.svg)](https://github.com/hillemacher/bitbucket-pr-comments-exporter/actions/workflows/test.yml)

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
bb-export cloud --workspace WORKSPACE --repo REPO --pr 42 --token API_TOKEN
bb-export cloud --url https://bitbucket.org/WORKSPACE/REPO/pull-requests/42 --token API_TOKEN
```

Bitbucket Server/Data Center:

```bash
bb-export server --server https://bitbucket.example.com --project PROJECT --repo REPO --pr 42 --username USERNAME --token TOKEN
bb-export server --url https://bitbucket.example.com/projects/PROJECT/repos/REPO/pull-requests/42/overview --username USERNAME --token TOKEN
```

You can also provide secrets with environment variables:

```bash
BB_TOKEN=API_TOKEN bb-export cloud --workspace WORKSPACE --repo REPO --pr 42
BB_USERNAME=USERNAME BB_TOKEN=TOKEN bb-export server --server https://bitbucket.example.com --project PROJECT --repo REPO --pr 42
```

Use `--output FILE` to choose the destination and `--format json` to write normalized JSON instead of Markdown. Deleted comments are omitted in both formats by default. With `--include-deleted`, Markdown shows `~~[deleted]~~`; JSON includes the normalized records with `deleted: true` and any body supplied by Bitbucket. Visible replies are retained even when their deleted parent is omitted.

## Agent Skill

The self-contained **bitbucket-pr-feedback** skill lets a local coding agent
retrieve feedback from one PR URL and summarize reviewer decisions, discussion
threads, candidate action items, and open questions. It supports Bitbucket Cloud
and Server/Data Center. Users need Python 3.11+; installing `bb-export` separately
is unnecessary.

Build the installable ZIP from a checkout:

```bash
python3 tools/build_skill.py
```

This writes `dist/bitbucket-pr-feedback.zip`. The builder packages the skill
instructions, a thin URL wrapper, the MIT license, and the maintained
`bb_pr_export` source. Generated bundles are ignored by Git; rebuild after
exporter or skill changes. The source skill folder alone is not self-contained.

Extract the ZIP into your agent's skill directory. For example, for a personal
Codex skill:

```bash
mkdir -p "$HOME/.agents/skills"
unzip dist/bitbucket-pr-feedback.zip -d "$HOME/.agents/skills"
```

The result should be `~/.agents/skills/bitbucket-pr-feedback/SKILL.md`, with the
bundled Python modules under `scripts/bb_pr_export`. Other agents can use the
same extracted folder in their supported skill location. When updating, replace
the previous skill folder with the newly built bundle.

Configure `BB_TOKEN` in the environment inherited by the agent's shell, using
the token requirements below. Server/Data Center can also use `BB_USERNAME`.
Never paste credentials into chat or put them in the skill or TOML config.
Then ask, for example:

```text
Use $bitbucket-pr-feedback to summarize the feedback on https://bitbucket.org/WORKSPACE/REPO/pull-requests/42
What follow-up actions do reviewers suggest on https://host/projects/PROJECT/repos/REPO/pull-requests/42/overview?
```

The agent runs the bundled entry point with a unique temporary output path:

```bash
python3 /absolute/path/to/bitbucket-pr-feedback/scripts/export_pr.py \
  'https://bitbucket.org/WORKSPACE/REPO/pull-requests/42' \
  --output /absolute/path/to/temporary-directory/review.json
```

Only one HTTP(S) PR URL is accepted, with a numeric PR ID. Bare PR numbers and
embedded credentials are rejected. Existing config discovery uses the caller's
working directory; URL values supply the PR identity, JSON output is forced,
and deleted-comment inclusion follows config (false by default).

The brief references comment IDs and file locations. It interprets replies but
cannot verify that feedback has been addressed: exports contain neither code
diffs nor normalized thread-resolution status. The skill retrieves and explains
feedback; it does not modify code or write to Bitbucket.

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

CLI flags override values parsed from `--url`; URL values override config; config fills missing defaults. Credentials are never read from config files. Use `--token` or `BB_TOKEN`.

## Tokens

For Bitbucket Cloud, create a scoped API token with `read:pullrequest:bitbucket` permission. Pass it with `--token` or `BB_TOKEN`; the exporter uses Bearer authentication, so no username or email is required. App passwords are no longer supported. See [using API tokens](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/) and [pull request API scopes](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/).

For Bitbucket Server/Data Center, generate a personal access token with pull request read access. See: Bitbucket Server personal access tokens.

## Request and Output Errors

HTTP connections and reads use a 30-second socket-operation timeout; this is not an overall export deadline. A transient HTTP 5xx response is retried once after two seconds. Timeouts, invalid responses, and rejected redirects are not retried.

Redirects and Cloud pagination links must stay on the original origin (scheme, hostname, and port). Cross-origin redirects, including HTTPS downgrades, are rejected before forwarding credentials. If your server redirects to another host, configure its final API base URL directly.

Network, response decoding, and output filesystem failures produce an error on stderr and exit code `1`.

## Output Format

The Markdown output starts with PR title, author, state, branch direction, creation date, and description. It then includes a review outcome table when reviewer decisions are available, followed by inline comments grouped by file and line, then general comments. Replies are nested under their parent comment.

The resulting `.md` file is designed to be pasted or attached as LLM context when asking for a review summary, unresolved issue list, implementation follow-up plan, or risk analysis.

## Why No External Dependencies?

The exporter uses only the Python standard library so it is easy to audit, simple to install, and safe to run locally in restricted environments. No data leaves your machine except requests sent directly to the Bitbucket API you configure.
