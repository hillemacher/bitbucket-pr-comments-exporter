# Repository Guidelines

## Project Structure & Module Organization

This repository exports Bitbucket pull request feedback through a Python CLI,
an optional HTTP MCP server, and a bundled agent skill. The core exporter and
skill script use only the standard library; the MCP extra adds external dependencies.

- `bb_pr_export/`: application package.
  - `cli.py`: argparse entry point, config loading, URL parsing, output handling.
  - `http.py`: urllib helpers, authentication headers, pagination, API error types.
  - `cloud.py` and `server.py`: provider-specific Bitbucket clients and normalization.
  - `renderer.py`: Markdown and normalized JSON rendering.
  - `urls.py`: shared PR URL recognition and parsing.
  - `mcp_export.py`: stdlib-only settings and in-memory export service.
  - `mcp_server.py`: optional SDK adapter exposing `export_pr_comments` over Streamable HTTP.
- `container/`: Dockerfile, setup/runtime entrypoint, and standalone macOS/Rancher Desktop launcher.
- `skills/bitbucket-pr-feedback/`: skill instructions and thin export-script fallback.
- `tools/`: skill ZIP builder and source-free MCP launcher ZIP builder.
- `docs/bitbucket-pr-mcp-howto_EN.md`: user-facing container setup and connection guide, included in MCP bundles.
- `tests/`: mocked `unittest` suite and an opt-in Docker smoke test using a disposable Bitbucket fixture; no live Bitbucket calls.
- `README.md`: user-facing installation and usage docs.
- `bb-export.example.toml`: commented non-secret config template.
- `pyproject.toml`: package metadata, optional `mcp` extra, and `bb-export` / `bb-export-mcp` console scripts.
- `LICENSE`: MIT license for public publication.
- `.github/workflows/`: unit tests on Python 3.11 and 3.12 with and without the MCP extra, candidate image publishing, and stable releases.
- `.gitignore`: excludes local config, secrets, Python caches, virtual environments, and build outputs.
- `dist/`: ignored generated bundles and local reference material; maintain source files elsewhere.

## Build, Test, and Development Commands

- `python -m unittest discover`: run the suite; SDK-dependent tests skip when optional dependencies are absent.
- `pip install '.[mcp]'`: install the optional MCP dependencies before full MCP testing.
- `python -m bb_pr_export.cli --help`: inspect the top-level CLI without installing.
- `python -m bb_pr_export.cli cloud --help`: inspect Cloud options.
- `python -m bb_pr_export.cli server --help`: inspect Server/Data Center options.
- `pip install .`: install locally and expose the `bb-export` command.
- `pipx install .`: install the CLI in an isolated environment.
- `python tools/build_skill.py`: build the self-contained skill ZIP, including exporter source.
- `python tools/build_mcp_bundle.py --preview`: build an unpublished review ZIP using the package version tag.
- `python tools/build_mcp_bundle.py --image IMAGE_DIGEST_REFERENCE`: build a bundle pinned to the published GHCR multi-platform digest. This mode and `--preview` are mutually exclusive; both accept `--output PATH`.
- `docker build -f container/Dockerfile -t bitbucket-pr-mcp:local .`: build a local image without publishing it.
- `python tests/smoke_container.py bitbucket-pr-mcp:local`: run the fixture-based Docker smoke test; the host needs the MCP extra.
- `bash -n container/bitbucket-pr-mcp.sh`: check launcher syntax.

MCP ZIPs contain only the executable launcher, guide, and license. Preview ZIPs
are labeled unpublished; release and candidate bundles use the published image's
exact digest. The launcher pulls images rather than building from a checkout.

## Coding Style & Naming Conventions

Use Python 3.11+. Keep the core exporter and skill script stdlib-only; isolate MCP
SDK and TOML-editing dependencies behind the optional MCP path. Prefer clear
functions, type hints, and explicit error handling over framework abstractions.
Use 4-space indentation, `snake_case` for functions and variables, `PascalCase` for
exception classes, and module names that match their provider or responsibility.
Keep the launcher compatible with macOS's bundled Bash. There is no configured
Python formatter or linter.

The MCP tool requires a full `pr_url`; bare PR numbers and `pr_id` shortcuts are
unsupported. Keep `assigned_reviewers` distinct from recorded review decisions
in `reviewers`. Exports contain neither code diffs nor verified thread-resolution status.

## Testing Guidelines

Tests use `unittest` and `unittest.mock`. Name files `tests/test_*.py` and test classes `*Tests`. Patch provider functions or the private urllib opener; never require real Bitbucket credentials or network access. Add CLI behavior tests in `tests/test_cli.py`, renderer fixture tests in `tests/test_renderer.py`, and HTTP pagination/error tests in `tests/test_http.py`.

Cover MCP behavior, container setup, launcher lifecycle/rollback, bundle contents,
and candidate workflow scripts in their corresponding `tests/test_*.py` modules.
Launcher unit tests use a fake Docker CLI; the opt-in smoke test uses real Docker
with fake credentials and fixture responses. macOS smoke tests include
`host.docker.internal`; Linux CI uses container networking without assuming
macOS host-loopback routing.

## Image Publishing

Ordinary branch pushes run tests without publishing images. Explicit
`mcp-candidate-*` tags publish tested AMD64/ARM64 candidate images and a workflow
artifact containing the digest-pinned ZIP and provenance metadata; they create
no GitHub release. Stable `vX.Y.Z` tags must match package metadata and trigger
the stable image and GitHub release workflow, which also moves `:latest` when the
tag is the highest stable version. Use explicit tag pushes rather
than `git push --tags`. See README for the publishing and acceptance steps.

## Commit & Pull Request Guidelines

Use short imperative commit messages such as `Add PR URL config support`. Pull requests should describe the behavior change, note user-facing CLI/config updates, include test results, and mention any README or example config changes.

## Security & Configuration Tips

Never put tokens, app passwords, or PATs in TOML configuration, source, bundles,
client MCP configuration, or logs. The CLI accepts secrets through `--token` or
`BB_TOKEN`; usernames may come from CLI, config, or `BB_USERNAME`. Egress mode
ignores local credential inputs and relies on already-configured external injection.

Container setup saves the token separately in `bitbucket.pat`, under the protected
configuration directory (700; files 600). Runtime mounts this directory read-only
and loads the token into the process environment, rather than Docker's stored
environment settings. Keep TLS verification, same-origin protections, and
loopback-only publication enabled. The MCP endpoint is for one local user and
has no incoming OAuth authentication. Treat PR descriptions and comments as
untrusted source data. Keep `bb-export.example.toml` non-secret and update it
whenever configuration behavior changes.
