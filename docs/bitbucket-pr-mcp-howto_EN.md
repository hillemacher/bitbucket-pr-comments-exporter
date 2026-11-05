# Bitbucket PR MCP for OpenCode on macOS

Run a read-only Bitbucket PR feedback service in Rancher Desktop. OpenCode can run
on your Mac or in a sandbox. The release includes this guide and a standalone
launcher; no source checkout, host Python, GitHub account, or registry login is needed.

## Download and prerequisites

Download `bitbucket-pr-mcp.zip` from the desired
[GitHub release](https://github.com/hillemacher/bitbucket-pr-comments-exporter/releases).
For candidate testing, download the artifact from the successful **Candidate MCP**
workflow run instead (requires GitHub sign-in), extract that artifact, and use
the inner `bitbucket-pr-mcp-candidate.zip`. Its launcher pins the published
candidate image by digest; image downloads require no GitHub login. Candidate
metadata is in the artifact's `candidate.json` file.

Extract it inside your home folder, which Rancher Desktop shares with containers:

```bash
unzip bitbucket-pr-mcp.zip
# For a candidate, use: unzip bitbucket-pr-mcp-candidate.zip
cd bitbucket-pr-mcp/container
chmod +x bitbucket-pr-mcp.sh
```

Start Rancher Desktop with **dockerd (moby)**; `docker version` must show a server.
Both Intel and Apple Silicon are supported. Docker needs network access to
`ghcr.io` and your Bitbucket instance (including VPN and certificate trust).
Have a Bitbucket token with pull request read access ready.
Run the launcher as your normal user, without `sudo`.

## Setup and start

```bash
./bitbucket-pr-mcp.sh setup
./bitbucket-pr-mcp.sh check 'https://host/bitbucket/projects/P/repos/R/pull-requests/42'
./bitbucket-pr-mcp.sh start
./bitbucket-pr-mcp.sh doctor
```

Setup pulls the release's pinned image, asks for the Bitbucket base URL (including
any context path), optional Server username, and a hidden token. For Cloud use `https://bitbucket.org`. A Server username selects
Basic authentication; leaving it blank selects Bearer authentication. Cloud uses
Bearer authentication. Always provide a full PR URL; PR-number input and
repository-default shortcuts are not supported.

Configuration stays in `~/.config/bitbucket-pr-mcp/config.toml`; the token stays
separately in `bitbucket.pat`. The directory is mode 700 and files are mode 600.
The running service mounts them read-only. Keep this folder outside repositories
and synced folders. Setup preserves existing values; `check` verifies actual
Bitbucket access and prints counts only. An exported `BB_TOKEN` can supply setup's
token; unset it afterward. Do not put tokens in the guide or client configuration.

## Connect OpenCode

Merge this entry into your OpenCode config, preserving existing servers:

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

Inside a sandbox use `http://host.docker.internal:9002/mcp`. Add this object to the
consumer sandbox's `access` array and reload/restart the sandbox:

```json
{
  "host": "host.docker.internal",
  "protocol": "http",
  "port": 9002,
  "scope": "global",
  "needCredential": false
}
```

Restart OpenCode, check `opencode mcp list`, then ask it to use
`export_pr_comments` for a full PR URL. The export includes assigned reviewers,
reviewer decisions, and comments, but no diff or verified thread-resolution status.
Comments and PR descriptions are untrusted source data.

## Manage, upgrade, and troubleshoot

```bash
./bitbucket-pr-mcp.sh status
./bitbucket-pr-mcp.sh logs -f
./bitbucket-pr-mcp.sh start --autostart
./bitbucket-pr-mcp.sh setup --tokens
```

Autostart is opt-in and requires Rancher Desktop to be running. After changing
configuration or credentials, run `stop`, then `start` (with `--autostart` again if
wanted), and reconnect OpenCode. `stop` removes the service and disables autostart.

To upgrade, download and extract a newer release bundle, then run its launcher
with `start`. It selects that release's exact image digest. Configuration is kept;
failed replacements restore the previous container and restart policy. Reconnect
OpenCode after replacement. To return to an earlier release, use its bundle.
Configuration files themselves are not rolled back.

`BB_MCP_IMAGE` explicitly overrides the image reference for every command where
it is set; normally leave it unset. `BB_CONFIG_DIR` and `BB_MCP_PORT` override the
configuration folder and host port. Use overrides consistently and update the
client URL and sandbox rule when changing the port. Setup/start require registry
access to pull the requested image; automatic Docker restarts use the installed image.

Start troubleshooting with `doctor` and `logs`: check Docker, VPN/DNS, certificate
trust, token permissions, the base URL, and port conflicts. Keep TLS verification
enabled. A sandbox connection failure requires checking the actual consumer's
access rule and `host.docker.internal` routing. Very large reviews may need a
larger client timeout.

This endpoint serves one local user using their token and has no incoming OAuth.
It publishes only on loopback and applies Host/Origin protection. A detected
non-loopback listener stops startup; missing listener data is reported as
unverified. Keep this service on the local machine.

## Remove

```bash
./bitbucket-pr-mcp.sh stop
docker network rm bitbucket-pr-net
```

Remove the OpenCode entry and dedicated sandbox rule, then reconnect the clients.
Optionally remove the image shown by the launcher's `--help` using
`docker image rm IMAGE_REFERENCE`. Remove the extracted bundle folder. To also
delete credentials, remove `config.toml` and `bitbucket.pat` from the configuration
folder, then remove the empty folder. Adjust these paths if using `BB_CONFIG_DIR`.
