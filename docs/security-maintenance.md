# Security maintenance and publication

Keep runtime credentials outside checkouts and synced folders. Use HTTPS for
Bitbucket, a read-only PAT with minimal repository access, and hidden token input
or an existing environment. Do not put real tokens in command arguments, shell
history, examples, agent transcripts, or client configuration. CLI exports contain
private review content and are written atomically with private POSIX permissions;
protect the destination directory with an appropriate ACL on Windows.

The MCP service is for one local user. The standalone command defaults to
loopback; the container explicitly listens internally on all interfaces while the
launcher publishes its port only on loopback. Host/Origin checks do not replace
network isolation or authentication. Trust other containers on its Docker network
and clients permitted to reach it: each inherits the PAT's read access. Do not
publish this endpoint on a LAN or the internet.

## Check before publication

Build fresh artifacts into a dedicated directory and scan both their contents
and all reachable commits. Docker is required for the digest-pinned scanners:

```bash
python -m pip install build
python -m build --outdir dist/security-artifacts
python tools/build_skill.py --output dist/security-artifacts/bitbucket-pr-feedback.zip
python tools/build_mcp_bundle.py --preview --output dist/security-artifacts/bitbucket-pr-mcp-preview.zip
python tools/security_check.py secrets --artifacts dist/security-artifacts --output dist/security-reports
```

The preview is unpublished. Generate final MCP ZIPs only with the exact published
image digest and scan that ZIP before distribution. Scanner reports redact secret
values; still treat any report containing private paths as local material.
The scanner runs with source mounted read-only and without a Docker socket or
host credentials. Scan failures or scanner errors fail the check. Full-history
checks require a normal clone with complete history (`fetch-depth: 0` in CI).

Publish reviewed Git refs and allowlisted artifacts. Never upload a raw checkout
or `.git` directory: ignored reference documents, credentials, caches, and old
unreachable objects can remain local even when `git status` is clean. To prepare
a source-only review copy while preserving the original, clone the intended
branch with `--no-local --single-branch --no-tags`, then check its object database
and package contents. Do not rewrite or prune shared history as routine cleanup.
If an actual credential is found, revoke/rotate it before coordinating removal
from every published location; ignore rules do not erase existing history.

## Image gate and inventory

```bash
docker build --pull -f container/Dockerfile -t bitbucket-pr-mcp:security .
python tools/security_check.py image bitbucket-pr-mcp:security --output dist/image-security
```

The gate scans OS and Python packages, writes the complete vulnerability report
and CycloneDX SBOM, then fails on HIGH/CRITICAL findings, including unfixed ones.
Lower-severity findings remain visible for review. Candidate and stable workflows
run this gate on both native architectures before uploading either image. Reports
are retained even when the gate fails. No blanket ignore-unfixed setting or
unreviewed exception list is applied. Investigate embedded/vendored package
metadata as well as installed distributions when assessing a finding.

A waiver must be a separate reviewed change naming each advisory and affected
package, evidence about exploitability, compensating controls, an owner, and an
expiry date. Do not disable the gate to get a release through. Recheck a rebuilt
image after any dependency or base change, and run the HTTPS fixture smoke test.
The fixture creates temporary certificates and does not require live credentials.

## Updates and operational limits

Dependabot checks action SHAs, the Docker base digest, and Python dependencies
weekly. Scanner image digests in `tools/security_check.py` and the patched pip
build version in the Dockerfile need explicit review when their upstreams release
security fixes. Preserve multi-platform support and recheck both architectures.
The image uses a digest-pinned Alpine Python base, upgrades pip before building,
then removes pip and ensurepip from the final runtime. This avoids shipping
unused installers and their vendored dependencies. HTTPS trust and native wheels
are verified by smoke tests on both supported architectures.

Current-directory CLI configuration is trusted input and can select the Server
host and output path. In an unfamiliar checkout use an explicit trusted config
and PR URL before providing a token. The MCP service uses an explicit config and
requires each PR URL to match its configured instance.

The `[limits]` TOML table controls `timeout_seconds`, `max_pages`,
`max_response_bytes`, and `max_total_bytes` for both CLI and MCP. Defaults are
90 seconds, 1,000 pages, 8 MiB per response, and 64 MiB total. Budgets include
retries and error responses; repeated pagination URLs are rejected. A limit error
returns no partial export. Individual socket operations are capped at 30 seconds
and the remaining budget; platform DNS resolution can still overrun deadlines.
Keep client timeouts above the chosen export budget.
