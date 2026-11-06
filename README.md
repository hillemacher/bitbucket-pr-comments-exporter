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

Load a token using hidden input in Bash or Zsh:

```bash
printf 'Bitbucket token: '
read -r -s BB_TOKEN
printf '\n'
export BB_TOKEN
```

Bitbucket Cloud:

```bash
bb-export cloud --workspace WORKSPACE --repo REPO --pr 42
bb-export cloud --url https://bitbucket.org/WORKSPACE/REPO/pull-requests/42
```

Bitbucket Server/Data Center:

```bash
bb-export server --server https://bitbucket.example.com --project PROJECT --repo REPO --pr 42 --username USERNAME
bb-export server --url https://bitbucket.example.com/projects/PROJECT/repos/REPO/pull-requests/42/overview --username USERNAME
```

Run `unset BB_TOKEN` when finished. `--token` remains available for compatibility,
but real token values in command arguments or inline environment assignments can
appear in process listings or shell history. Avoid shell tracing when handling tokens.

Exports are written atomically with owner-only permissions (`0600` on POSIX).
New output directories use `0700`; existing directory permissions are preserved.
Symlink and special-file destinations are rejected. On Windows, protect the
output directory with an appropriate ACL.

Use `--output FILE` to choose the destination and `--format json` to write normalized JSON instead of Markdown. Deleted comments are omitted in both formats by default. With `--include-deleted`, Markdown shows `~~[deleted]~~`; JSON includes the normalized records with `deleted: true` and any body supplied by Bitbucket. Visible replies are retained even when their deleted parent is omitted.

## Agent Skill

The self-contained **bitbucket-pr-feedback** skill lets a local coding agent
retrieve feedback from one PR URL and summarize reviewer decisions, discussion
threads, candidate action items, and open questions. It supports Bitbucket Cloud
and Server/Data Center. The skill prefers a connected `export_pr_comments` MCP
tool whose advertised instance matches the PR URL, passing the full URL as
`pr_url`. Otherwise, it uses the bundled script. After an MCP failure, it reports
the error without automatically switching to the script or other authentication.
The skill does not set up or reconfigure the service.

The MCP path uses the service's authentication and configuration and needs no
local Python or credentials. The script path requires Python 3.11+; installing
`bb-export` separately is unnecessary.

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

The bundled script defaults to `--auth-mode egress`, for sandboxes whose egress
server injects credentials. Python sends no Authorization header and ignores local
credential inputs, including `BB_TOKEN` and `BB_USERNAME`. Routing, proxy settings,
and certificate trust must already be configured. The egress policy must enforce
allowed destinations and HTTP methods (GET-only for this exporter); the skill
does not configure or enforce those restrictions. Normal Bitbucket URLs are used.

For local use outside that sandbox, explicitly append `--auth-mode token` to
the bundled command and configure `BB_TOKEN` in the agent's shell environment.
Server/Data Center can also use `BB_USERNAME`. There is no automatic fallback
from egress to token authentication. Never paste credentials into chat or put
them in the skill or TOML config. Then ask, for example:

```text
Use $bitbucket-pr-feedback to summarize the feedback on https://bitbucket.org/WORKSPACE/REPO/pull-requests/42
What follow-up actions do reviewers suggest on https://host/projects/PROJECT/repos/REPO/pull-requests/42/overview?
```

When using the script path, the agent runs the bundled entry point with a unique
temporary output path:

```bash
python3 /absolute/path/to/bitbucket-pr-feedback/scripts/export_pr.py \
  'https://bitbucket.org/WORKSPACE/REPO/pull-requests/42' \
  --output /absolute/path/to/temporary-directory/review.json
```

Only one HTTP(S) PR URL is accepted, with a numeric PR ID. Bare PR numbers and
embedded credentials are rejected. For the script, local TOML configuration is
optional. Existing config discovery uses the caller's working directory; URL
values supply the PR identity, JSON output is forced, and deleted-comment
inclusion follows config (false by default). The MCP path uses the service's
deleted-comment setting.

Both paths use the same interpretation rules: read all discussions, disclose
incomplete retrieval or reading, and analyze only successful exports. The brief
lists assigned reviewers separately from recorded decisions, treating empty
assignments as none reported and null or missing assignments as unknown. It
references comment IDs and file locations. It interprets replies but
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
bb-export server --config bb-export.toml --pr 500
```

Treat current-directory TOML as trusted input: it can select the Server host and
output location. In an unfamiliar checkout, pass an explicit trusted `--config`
and PR URL before using an ambient token.

CLI flags override values parsed from `--url`; URL values override config; config fills missing defaults. Credentials are never read from config files. Use `--token` or `BB_TOKEN`.

## Authentication modes

The standalone CLI defaults to `--auth-mode token`, preserving local credential
handling. To use an already-configured credential-injecting egress server:

```bash
bb-export cloud --url https://bitbucket.org/WORKSPACE/REPO/pull-requests/42 --auth-mode egress
bb-export server --url https://host/projects/PROJECT/repos/REPO/pull-requests/42 --auth-mode egress
```

Egress mode bypasses the token requirement and ignores local token and username
inputs, including explicit flags and environment variables. Python sends neither
Bearer nor Basic authentication. Authentication failures should be resolved in
the egress access rules or injection configuration; token mode is never selected
as a fallback. Authentication mode is selected only through command-line options,
not TOML configuration. The bundled skill defaults to egress mode instead.

## Tokens

Use a minimally scoped, read-only token. Any permitted local MCP client can read
PR feedback accessible to that token across the configured instance. The service
does not provide per-client or per-repository authorization.

For Bitbucket Cloud, create a scoped API token with `read:pullrequest:bitbucket` permission. Pass it with `--token` or `BB_TOKEN`; the exporter uses Bearer authentication, so no username or email is required. App passwords are no longer supported. See [using API tokens](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/) and [pull request API scopes](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/).

For Bitbucket Server/Data Center, generate a personal access token with pull request read access. See: Bitbucket Server personal access tokens.

## Request and Output Errors

HTTP operations use a 30-second timeout within a shared 90-second export budget.
The budget covers requests, reads, retries, and pagination. DNS resolution may
exceed the socket timeout on some systems. A transient HTTP 5xx response is retried once after two seconds. Timeouts, invalid responses, and rejected redirects are not retried.

Authenticated Bitbucket requests require HTTPS, including the initial URL. MCP
setup rejects plaintext instance URLs. Redirects and Cloud pagination links must stay on the original origin (scheme, hostname, and port). Cross-origin redirects, including HTTPS downgrades, are rejected before forwarding credentials. If your server redirects to another host, configure its final API base URL directly.

Network, response decoding, and output filesystem failures produce an error on stderr and exit code `1`.

## Output Format

The Markdown output starts with PR title, author, state, branch direction, creation date, and description. It then lists assigned reviewers and includes a review outcome table when reviewer decisions are available, followed by inline comments grouped by file and line, then general comments. Replies are nested under their parent comment.

The resulting `.md` file is designed to be pasted or attached as LLM context when asking for a review summary, unresolved issue list, implementation follow-up plan, or risk analysis.

## Why No External Dependencies?

The exporter uses only the Python standard library so it is easy to audit, simple to install, and safe to run locally in restricted environments. No data leaves your machine except requests sent directly to the Bitbucket API you configure.

## Container MCP for OpenCode and sandboxes

The MCP service runs independently in Rancher Desktop on macOS (dockerd/moby).
The standalone `bb-export-mcp --config PATH` command listens on `127.0.0.1:9000`
by default. `--listen-host 0.0.0.0` is reserved for containers whose host port is
published on loopback. Host/Origin checks protect against browser attacks; they
do not authenticate a network client. Keep this unauthenticated service local.

It exposes exactly one read-only tool,
`export_pr_comments`, requiring one full PR URL as `pr_url` and returning the
`provider`, `pr`, `assigned_reviewers`, `reviewers`, and `comments` JSON. All Python dependencies run inside the image; the Mac needs
only Docker and its bundled Bash. Both Apple Silicon and Intel use native images.

The tool exports general/Overview comments, inline comments, replies, and reviewer
decisions. For Bitbucket Server/Data Center, comments come from the PR activities
API; activities without comments are omitted. Deleted comments are excluded by
default unless configured otherwise.

`assigned_reviewers` lists assigned reviewers as `{"reviewer": "Display name"}`
objects, including people who have not commented or recorded a decision. An empty
list means no assignments reported; `null` means assignment data is unavailable.
Older exports without this field also leave assignments unknown. Use only this
field for assignment claims. The historical `reviewers` field contains recorded
review decisions, so `reviewers: []` does not mean nobody is assigned. Comments,
assignments, and decisions are independent. Markdown shows assignments before
review outcomes, using “None reported” for an empty list and “Unknown” for `null`;
it omits the assignment section for older exports without the field.

Download `bitbucket-pr-mcp.zip` from a [GitHub release](https://github.com/hillemacher/bitbucket-pr-comments-exporter/releases),
extract it inside your home folder, and open the extracted `bitbucket-pr-mcp/` folder.
The ZIP contains a [short guide](docs/bitbucket-pr-mcp-howto_EN.md), a standalone launcher,
and the license. No source checkout, host Python, GitHub account, or registry login is required.
Each released launcher pins the public image to an exact multi-platform digest.

From the extracted folder:

```bash
./container/bitbucket-pr-mcp.sh setup
./container/bitbucket-pr-mcp.sh check 'https://host/bitbucket/projects/P/repos/R/pull-requests/42'
./container/bitbucket-pr-mcp.sh start
./container/bitbucket-pr-mcp.sh doctor
```

Setup provides brief guidance and examples for the Bitbucket base URL, optional
Server username and token. For Server/Data Center,
use a base URL such as `https://bitbucket.example.com/bitbucket`, including any
context path; for Cloud, use `https://bitbucket.org`. A Server username such as
`jane.doe` selects the exporter's existing Basic authentication; omit it for Bearer/PAT.
Cloud does not use this username.

The full PR URL supplies the repository and PR number. Bare PR numbers and MCP
`pr_id` input are no longer supported. Repository defaults in existing config
files are ignored for request targeting; standalone CLI defaults still work.
Repeat setup preserves existing files; `setup --tokens` rotates the PAT.
An exported
`BB_TOKEN` can supply setup's token without typing it. Setup acknowledges this
without displaying the value; otherwise, token input is hidden. The launcher transfers an exported token through a temporary owner-only file,
mounts it read-only for setup, and removes it on exit. It never passes the token
as a Docker environment setting. The token is saved separately from configuration. Unset `BB_TOKEN` afterward.

Configuration lives in `~/.config/bitbucket-pr-mcp/`: `config.toml` contains
non-secret settings, while `bitbucket.pat` is a separate secret file. The folder
has mode 700 and files have mode 600. Runtime mounts it read-only and reads the
PAT into `BB_TOKEN` inside the process, rather than Docker's stored environment.
Keep this folder outside repositories and synced folders. If a deliberate local
checkout override is needed, use `BB_CONFIG_DIR="$PWD/.bitbucket-pr-mcp"`; this
repository ignores that entire directory. Setup validates local
configuration; `check <PR_URL>` verifies actual API access and prints counts only.

```toml
[mcp]
base_url = "https://host/bitbucket"
[server]
# username = "optional.username"
[defaults]
include_deleted = false
```

A full URL determines the repository and PR; its instance must match the configured
base. Missing URLs and bare numbers fail before Bitbucket access. The tool
advertises the configured instance and accepts no repository-default shortcut.

Server/Data Center can reuse an exporter configuration without an `[mcp]` table:

```toml
[server]
server = "https://host/bitbucket"
project = "P"
repo = "R"
# username = "optional.username"
[defaults]
include_deleted = false
```

For Cloud, new configuration should specify the instance explicitly:

```toml
[mcp]
base_url = "https://bitbucket.org"
[defaults]
include_deleted = false
```

`[mcp].base_url` takes precedence; otherwise the server URL or legacy Cloud defaults
identify the instance. Legacy repository identifiers are used only for this
instance inference, never to select the requested repository or PR. If both providers are populated, set `[mcp].base_url`
explicitly. Server usernames resolve from `[server].username`, then
`[defaults].username`, then the MCP process's `BB_USERNAME`. Host environment
variables are not automatically forwarded to the container; use TOML for the
container username. Output path and format settings remain CLI-specific.

Existing installations can keep their config and separate PAT file unchanged.
The service reads that explicit file rather than searching the agent's working
directory. `setup --defaults` has been removed. After pulling the image with `start`,
reconnect OpenCode (or your MCP client) to refresh the required URL-only schema.
`preflight` and `doctor` report the configured instance.

Cloud uses the existing `api.bitbucket.org` client. PR paths with encoded segments,
backslashes or dot segments are rejected. Output is returned in memory; CLI
output-file/format defaults do not apply. Visible replies to omitted deleted
parents retain their `parent_id`. Comments and descriptions are untrusted source
data, and exports contain no diff or verified thread-resolution status.

The image installs the optional MCP extra (SDK v2 and TOML Kit for setup) (`pip install '.[mcp]'`). Ordinary
CLI and bundled skill use still require only the standard library. The MCP
container uses its own PAT directly, independently of the skill's egress mode.
Ensure Rancher Desktop has VPN/network access and trusts your Bitbucket server's
certificate chain. TLS verification and same-origin redirect protections remain
enabled. Authentication errors require checking the PAT and repository access.

### Connect OpenCode

Merge this entry into your OpenCode config, preserving other servers:

```json
{
  "mcp": {
    "bitbucket-pr": {
      "type": "remote",
      "enabled": true,
      "url": "http://127.0.0.1:9002/mcp",
      "oauth": false,
      "timeout": 120000
    }
  }
}
```

Inside a sandbox, use `http://host.docker.internal:9002/mcp` instead. Add this to the
consumer sandbox's access rules and reload/restart it:

```json
{
  "host": "host.docker.internal",
  "protocol": "http",
  "port": 9002,
  "scope": "global",
  "needCredential": false
}
```

Restart OpenCode, check `opencode mcp list`, and ask it to export feedback from a
PR URL. No token belongs in OpenCode or the sandbox access rule.

### Manage the service

```bash
./container/bitbucket-pr-mcp.sh status
./container/bitbucket-pr-mcp.sh logs -f
./container/bitbucket-pr-mcp.sh stop
./container/bitbucket-pr-mcp.sh start --autostart
```

`setup` and `start` pull the configured image from GHCR. `start` preflights configuration and publishes
`127.0.0.1:9002` to container port 9000. An unchanged running image/port is kept.
Failed replacements restore the previous container and restart policy; the next
start recovers interrupted replacements. Commands only alter containers bearing
the launcher's management label. Configuration files are not rolled back.
After configuration/token changes, stop and start the service, then reconnect
OpenCode. Pull failures leave the existing service available.

When upgrading from a version with different container management labels, stop
the service using that version's launcher before switching versions, then run
`start` with the new launcher. The new launcher refuses containers with older
management labels; the configuration and PAT files can be reused.

Autostart is opt-in (`unless-stopped`); `stop` removes the service and disables
it. Pulls occur on manual starts, not automatic Docker restarts.
`BB_CONFIG_DIR` overrides the configuration folder and `BB_MCP_PORT` overrides
host port 9002; use overrides consistently and update OpenCode/access rules.
`BB_MCP_IMAGE` explicitly overrides the image reference. To upgrade normally, download
a newer release bundle and run its launcher with `start`, then reconnect OpenCode.
The existing configuration and restart policy are retained. Use an earlier bundle
to return to its pinned image; configuration files are not rolled back.

This is a single-user, single-machine endpoint with access through your PAT.
It has no incoming OAuth/authentication. Loopback publication limits host exposure;
`start` and `doctor` check listeners with `lsof` and stop/refuse a detected exposed
listener. Missing listener data is reported as unverified. `doctor` also tests
MCP from a container through `host.docker.internal`; fix routing/access rules if
that probe fails, keeping the host port bound to loopback.

Exports default to a 90-second budget, 1,000 pagination pages, 8 MiB per response,
and 64 MiB of total response data. Repeated pagination URLs are rejected. Limit
failures return an error without a partial export. Configure `[limits]` in TOML
for larger reviews and increase the client's timeout to match. Both CLI and MCP
use these settings; see `bb-export.example.toml`.

### Prepare a local MCP preview

Build a source-free review ZIP without publishing an image:

```bash
python3 tools/build_mcp_bundle.py --preview
```

This writes `dist/bitbucket-pr-mcp-preview.zip`; `--output PATH` overrides the
destination. It contains only the executable standalone launcher, guide, and
license. The launcher uses the planned GHCR version tag from `pyproject.toml`.
The guide labels the bundle as unpublished: setup/start cannot pull that image
until it is published. Review the extracted launcher with `--help`; test local
images with the fixture smoke test below. Regenerate the final release ZIP with
`--image` and the published multi-platform digest. The two modes are mutually
exclusive; release bundles continue to require an exact digest.

To build and test local images for both architectures, including emulation when
needed, run from the checkout (the host needs the optional MCP extra):

```bash
docker build --platform linux/arm64 --build-arg VERSION=0.1.0 --build-arg REVISION="$(git rev-parse HEAD)-dirty" -f container/Dockerfile -t bitbucket-pr-mcp:preview-arm64 .
docker build --platform linux/amd64 --build-arg VERSION=0.1.0 --build-arg REVISION="$(git rev-parse HEAD)-dirty" -f container/Dockerfile -t bitbucket-pr-mcp:preview-amd64 .
python3 tests/smoke_container.py bitbucket-pr-mcp:preview-arm64
python3 tests/smoke_container.py bitbucket-pr-mcp:preview-amd64
```

These commands build and test locally; they do not push images or start a release.
The revision suffix identifies a working-tree preview rather than a tagged build.

### Publish a candidate image

The `Candidate MCP` workflow publishes Docker images only for explicit
`mcp-candidate-*` tags. Pushing a branch runs normal tests without
publishing images. Candidate rollout is separate from the stable `v*` workflow.

Push the commit you want to test and wait for its Tests workflow to pass.
Then create a new tag at that tested commit, for example
`mcp-candidate-001`, and push that tag explicitly. Do not reuse an existing tag
or use `git push --tags`.

The workflow runs the unit suite, builds native AMD64 and ARM64 images, and
smoke-tests each before upload. It publishes
`ghcr.io/hillemacher/bitbucket-pr-mcp:candidate-<full-commit-sha>` plus architecture
tags, without changing the package version or publishing a GitHub release.
The job summary records the exact source commit, package version, and combined
image digest. Candidate builds for the same commit run sequentially. Reruns may
rebuild that commit's candidate tag; use the recorded digest for exact pinning.

Both architectures must download anonymously by digest before the workflow
uploads its bundle artifact. If this check fails because the recreated GHCR
package is private, make it public in package settings and rerun the failed
publish job. Other registry failures require fixing connectivity or permissions.

Download `bitbucket-pr-mcp-candidate-<full-commit-sha>` from the successful
workflow run's **Artifacts** section (GitHub sign-in is required for Actions
artifact downloads). It contains `bitbucket-pr-mcp-candidate.zip` and
`candidate.json`; the artifact is retained for 30 days. The inner ZIP contains
only the guide, executable launcher, and license, pinned to the published image
digest. Docker image pulls themselves require no GitHub account.

Extract the inner ZIP and follow its guide on macOS: run `setup`, `start`,
`doctor`, and `check` with a full PR URL. Confirm assigned reviewers and comments,
then copy the guide and launcher into the harness and verify sandbox access.
Use fake credentials only for fixture smoke tests; keep real tokens in the
existing protected configuration folder. For fixes, commit the change and tag
the new tested commit as a new candidate. Stable release planning follows
acceptance; the existing draft release is not used for this rollout.

### Publish an MCP release

The `Release MCP` workflow runs on stable `vX.Y.Z` tags matching the version in
`pyproject.toml`. It runs the unit suite, builds and smoke-tests native Linux
AMD64 and ARM64 images using fake Bitbucket responses, then publishes
`ghcr.io/hillemacher/bitbucket-pr-mcp:X.Y.Z`. OCI labels record source, version,
revision, and license. The two tested architecture images are combined into a
multi-platform image. The workflow attaches a source-free launcher ZIP to the
matching GitHub release, pinned to the combined image's digest.

For the **first release**, change the GHCR package visibility to **public** in
GitHub package settings after the image is pushed. Public repository visibility
does not automatically make the package public. If anonymous verification fails,
make the package public and rerun the failed publish job. The workflow verifies
both platforms can be pulled with an empty Docker configuration before attaching
the bundle to a GitHub release. Publishing uses the workflow's `GITHUB_TOKEN`
with `packages: write`; users need no registry credentials.

For a release, update the package version and the checkout launcher's default
version tag together, push the changes, then push the matching `vX.Y.Z` tag.
Release ZIPs embed a digest instead of the checkout's version tag. Never move a
published release tag; issue a new version for fixes. Confirm `setup`, `start`,
`check`, and `doctor` from an extracted bundle on macOS before announcing a release.

To build the same bundle manually after publishing an image:

```bash
python3 tools/build_mcp_bundle.py --image 'ghcr.io/hillemacher/bitbucket-pr-mcp@sha256:REPLACE_WITH_PUBLISHED_DIGEST'
```

This writes `dist/bitbucket-pr-mcp.zip`; `--output PATH` chooses another destination.
Only the guide, launcher, and license are included. Keep the extracted folder
together when copying it into a harness repository. Generated bundles remain
ignored by Git; `dist/example` is reference material only.

For local image development, build directly from this checkout:

```bash
docker build -f container/Dockerfile -t bitbucket-pr-mcp:local .
python3 tests/smoke_container.py bitbucket-pr-mcp:local
```

The smoke-test host needs the optional MCP extra. The macOS smoke check includes
`host.docker.internal`; Linux CI checks host exports and container networking
without assuming macOS host-loopback forwarding.

## Security and publication checks

See [the security maintenance guide](docs/security-maintenance.md) for credential
scanning, image scans/SBOMs, dependency updates, artifact review, and safe source
publication. Source and artifact secret checks run on branch/PR builds. Candidate
and stable publishing also require an image vulnerability gate before upload.
