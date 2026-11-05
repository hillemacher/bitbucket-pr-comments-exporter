#!/usr/bin/env bash
# Local single-user Bitbucket MCP service for macOS / Rancher Desktop.

set -euo pipefail

DEFAULT_IMAGE="ghcr.io/hillemacher/bitbucket-pr-mcp:0.1.0"
CONFIG_DIR="${BB_CONFIG_DIR:-$HOME/.config/bitbucket-pr-mcp}"
HOST_PORT="${BB_MCP_PORT:-9002}"
IMAGE="${BB_MCP_IMAGE:-$DEFAULT_IMAGE}"
CONTAINER="bitbucket-pr-mcp"
NETWORK="bitbucket-pr-net"
LABEL="io.github.hillemacher.bitbucket-pr-mcp=1"
FINGERPRINT_LABEL="io.github.hillemacher.bitbucket-pr-mcp.fingerprint"
PREVIOUS="${CONTAINER}-previous"
TRANSACTION_ACTIVE=""
PREVIOUS_RUNNING=""
KEEP_STOPPED=""
JOURNAL="$CONFIG_DIR/.bitbucket-pr-mcp-previous-running"
CONFIG_FILES=(config.toml bitbucket.pat)

usage() {
  cat <<EOF
Usage: bitbucket-pr-mcp.sh <command>
  setup [--tokens]    Create config/PAT; --tokens rotates PAT
  start [--autostart]  Pull and start; optional unless-stopped restart policy
  stop                Remove the managed service and disable autostart
  status              Show status and restart policy
  logs [-f]           Show service logs
  check <PR_URL>      Test a complete export, reporting counts only
  doctor              Check Docker, permissions and MCP connectivity
Environment: BB_MCP_IMAGE (default $DEFAULT_IMAGE), BB_MCP_PORT (default 9002), BB_CONFIG_DIR (default ~/.config/bitbucket-pr-mcp).
EOF
}

die() { echo "error: $*" >&2; exit 1; }
warn() { echo "warning: $*" >&2; }

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker CLI not found; install Rancher Desktop"
  docker version >/dev/null 2>&1 ||
    die "the Docker engine is not reachable; start Rancher Desktop (container engine dockerd/moby)"
}

container_exists() {
  docker ps -a --filter "name=^${1:-$CONTAINER}\$" --format '{{.Names}}' | grep -qx "${1:-$CONTAINER}"
}

container_running() {
  docker ps --filter "name=^${CONTAINER}\$" --filter status=running --format '{{.Names}}' |
    grep -qx "$CONTAINER"
}

autostart_enabled() {
  [[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' "$CONTAINER" 2>/dev/null)" == \
    "unless-stopped" ]]
}

image_fingerprint() {
  docker image inspect "$IMAGE" | docker run --rm -i --entrypoint python3 \
    "$IMAGE" /app/entrypoint.py image-fingerprint
}

assert_owned() {
  [[ "$(label_of "$1" io.github.hillemacher.bitbucket-pr-mcp)" == "1" ]] ||
    die "container $1 is not managed by this launcher; leaving it untouched"
}

rollback() {
  if container_exists "$PREVIOUS"; then
    if container_exists; then
      if ! docker rm -f "$CONTAINER" >/dev/null; then
        warn "rollback failed; previous container remains at $PREVIOUS"
        return 1
      fi
    fi
    if ! docker rename "$PREVIOUS" "$CONTAINER"; then
      warn "rollback failed; previous container remains at $PREVIOUS"
      return 1
    fi
  fi
  if [[ -n "$PREVIOUS_RUNNING" && -z "$KEEP_STOPPED" ]]; then
    if ! docker start "$CONTAINER" >/dev/null; then
      warn "previous container/policy restored, but it could not start; see: $0 logs"
      return 1
    fi
  fi
  rm -f "$JOURNAL"
  warn "previous container and restart policy restored${KEEP_STOPPED:+; service kept stopped for safety}"
}

write_recovery_state() {
  local temporary
  temporary="$(mktemp "$CONFIG_DIR/.bitbucket-pr-recovery.XXXXXX")"
  printf '%s\n' "$1" >"$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$JOURNAL"
}

recover_previous() {
  if container_exists "$PREVIOUS"; then
    assert_owned "$PREVIOUS"
    if container_exists; then assert_owned "$CONTAINER"; fi
  elif [[ ! -f "$JOURNAL" ]]; then
    return 0
  elif ! container_exists; then
    die "recovery journal exists but no container; inspect $JOURNAL"
  else
    assert_owned "$CONTAINER"
  fi
  PREVIOUS_RUNNING=""
  KEEP_STOPPED=""
  if [[ -f "$JOURNAL" ]]; then
    case "$(cat "$JOURNAL")" in
      true) PREVIOUS_RUNNING=1 ;;
      false) ;;
      safe-stop) KEEP_STOPPED=1 ;;
      *) die "invalid recovery journal: $JOURNAL" ;;
    esac
  elif container_exists && [[ "$(label_of "$CONTAINER" io.github.hillemacher.bitbucket-pr-mcp.previous-running)" == "true" ]]; then
    PREVIOUS_RUNNING=1
  fi
  warn "recovering an interrupted replacement from $PREVIOUS"
  rollback || die "recovery failed; inspect $PREVIOUS before retrying"
  PREVIOUS_RUNNING=""
  KEEP_STOPPED=""
}

label_of() {
  docker inspect --format "{{with index .Config.Labels \"$2\"}}{{.}}{{end}}" "$1" 2>/dev/null ||
    true
}

file_mode() {
  # GNU first: GNU stat reads -f as "file system" and would print a dump before failing.
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1"
}

listeners() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR > 1 {print $9}' | sort -u || true
  fi
}

non_loopback_listeners() {
  listeners "$1" | grep -v -E '^(127\.0\.0\.1|\[::1\]|::1):' || true
}

port_open() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

service_ready() {
  docker exec "$CONTAINER" python3 -c \
    'import socket; socket.create_connection(("127.0.0.1", 9000), 1).close()' >/dev/null 2>&1
}

protect_config() {
  chmod 700 "$CONFIG_DIR"
  local name
  for name in "${CONFIG_FILES[@]}"; do
    [[ -f "$CONFIG_DIR/$name" ]] && chmod 600 "$CONFIG_DIR/$name"
  done
  return 0
}

require_config() {
  local name
  for name in "${CONFIG_FILES[@]}"; do
    [[ -f "$CONFIG_DIR/$name" ]] ||
      die "$CONFIG_DIR/$name is missing; run: $0 setup"
  done
}

pull_image() {
  docker pull "$IMAGE" || die "could not pull image $IMAGE; previous service kept"
}

ensure_image() {
  docker image inspect "$IMAGE" >/dev/null 2>&1 || pull_image
}

run_tool() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$CONFIG_DIR:/config:ro" "$IMAGE" "$@"
}

cmd_setup() {
  local setup_args=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --tokens) setup_args+=("$1") ;;
      *) die "unknown setup option: $1" ;;
    esac
    shift
  done
  local docker_args=(--rm -i --user "$(id -u):$(id -g)" -v "$CONFIG_DIR:/config" -e BB_TOKEN)
  [[ -t 0 ]] && docker_args+=(-t)

  require_docker
  mkdir -p "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"
  pull_image
  local candidate_image
  candidate_image="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
  local IMAGE="$candidate_image"
  local status=0
  docker run "${docker_args[@]}" "$IMAGE" setup ${setup_args[@]+"${setup_args[@]}"} || status=$?
  protect_config
  if [[ $status -eq 0 ]]; then
    echo "Setup complete. Start the service with: $0 start"
  fi
  return "$status"
}

cmd_start() {
  local restart_policy="no" saved_policy fingerprint previous_fingerprint existed="" was_running=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --autostart) restart_policy="unless-stopped" ;;
      *) die "unknown start option: $1" ;;
    esac
    shift
  done

  require_docker
  recover_previous
  require_config
  protect_config
  if container_exists; then
    assert_owned "$CONTAINER"
    existed=1
    saved_policy="$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}{{if .HostConfig.RestartPolicy.MaximumRetryCount}}:{{.HostConfig.RestartPolicy.MaximumRetryCount}}{{end}}' "$CONTAINER")" ||
      die "could not read previous restart policy; container kept"
    if [[ "$restart_policy" == "no" ]]; then restart_policy="$saved_policy"; fi
    if container_running; then was_running=1; fi
  fi
  pull_image
  # Freeze the candidate reference so a later retag cannot change the validated image.
  local candidate_image
  candidate_image="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
  local IMAGE="$candidate_image"
  fingerprint="$(image_fingerprint)" || die "could not fingerprint the candidate image; previous container kept"
  [[ "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || die "invalid image fingerprint; previous container kept"
  run_tool preflight || die "preflight failed; previous container/policy kept (see $0 setup)"
  previous_fingerprint="$(label_of "$CONTAINER" "$FINGERPRINT_LABEL")"
  if [[ -n "$was_running" && "$previous_fingerprint" == "$fingerprint" ]] && [[ "$(docker port "$CONTAINER" 9000/tcp)" == "127.0.0.1:$HOST_PORT" ]]; then
    docker update --restart "$restart_policy" "$CONTAINER" >/dev/null
    local exposed
    exposed="$(non_loopback_listeners "$HOST_PORT")"
    if [[ -n "$exposed" ]]; then
      docker stop "$CONTAINER" >/dev/null
      die "port $HOST_PORT has non-loopback listeners; service kept stopped"
    fi
    echo "bitbucket-pr-mcp is already running the current image on http://127.0.0.1:$HOST_PORT/mcp"
    echo "Autostart policy: $restart_policy"
    return 0
  fi

  docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null
  if [[ -n "$existed" ]]; then
    # A restart loop can recover while the pull runs; preserve the state at the handover.
    if container_running; then was_running=1; else was_running=""; fi
    PREVIOUS_RUNNING="$was_running"
    if [[ -n "$was_running" ]]; then write_recovery_state true; else write_recovery_state false; fi
    TRANSACTION_ACTIVE=1
    trap 'result=$?; trap - EXIT; if [[ -n "$TRANSACTION_ACTIVE" ]]; then rollback || result=1; fi; exit "$result"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    docker stop "$CONTAINER" >/dev/null
    docker rename "$CONTAINER" "$PREVIOUS"
  fi
  if port_open "$HOST_PORT"; then
    die "port $HOST_PORT is already in use ($(listeners "$HOST_PORT" | paste -sd, -)); stop the conflicting service or set BB_MCP_PORT"
  fi

  # Create first: the replacement already stores its policy if docker start fails. The old
  # container is retained until readiness and host-loopback checks have both succeeded.
  docker create --name "$CONTAINER" --label "$LABEL" --network "$NETWORK" \
    --label "$FINGERPRINT_LABEL=$fingerprint" \
    --label "io.github.hillemacher.bitbucket-pr-mcp.previous-running=${was_running:+true}" \
    --user "$(id -u):$(id -g)" --restart "$restart_policy" -p "127.0.0.1:$HOST_PORT:9000" -v "$CONFIG_DIR:/config:ro" \
    -e "BB_MCP_HOST_PORT=$HOST_PORT" \
    "$IMAGE" serve >/dev/null
  docker start "$CONTAINER" >/dev/null

  local attempt ready=""
  for attempt in $(seq 1 30); do
    if service_ready; then ready=1; break; fi
    if ! container_running; then
      docker logs --tail 30 "$CONTAINER" >&2 || true
      die "bitbucket-pr-mcp exited during start (log above)"
    fi
    sleep 1
  done
  [[ -n "$ready" ]] || die "bitbucket-pr-mcp did not start listening within 30 s; see: $0 logs"
  docker exec "$CONTAINER" python3 /app/entrypoint.py probe-mcp http://127.0.0.1:9000/mcp \
    --probe-label "inside service container" || die "MCP readiness check failed"
  port_open "$HOST_PORT" || die "port $HOST_PORT is not reachable on 127.0.0.1; run: $0 doctor"

  local exposed
  exposed="$(non_loopback_listeners "$HOST_PORT")"
  if [[ -n "$exposed" ]]; then
    KEEP_STOPPED=1
    if [[ -n "$existed" ]]; then write_recovery_state safe-stop; fi
    docker stop "$CONTAINER" >/dev/null || true
    die "port $HOST_PORT was published on $(echo "$exposed" | paste -sd, -), not only on loopback; service kept stopped"
  fi
  if [[ -n "$existed" ]]; then
    docker rm "$PREVIOUS" >/dev/null
    TRANSACTION_ACTIVE=""
    rm -f "$JOURNAL"
    trap - EXIT INT TERM
  fi
  docker run --rm "$IMAGE" probe-mcp "http://host.docker.internal:$HOST_PORT/mcp" \
    --probe-label "sandbox/container access" ||
    warn "the sandbox path check failed; run: $0 doctor"
  local autostart="off; enable with: $0 start --autostart"
  if [[ "$restart_policy" == "unless-stopped" ]]; then autostart="on"; fi
  cat <<EOF
bitbucket-pr-mcp is running.
  opencode on this machine:   http://127.0.0.1:$HOST_PORT/mcp
  opencode in a sandbox/container: http://host.docker.internal:$HOST_PORT/mcp
Autostart: $autostart
Stop it with: $0 stop
EOF
  if [[ -n "$was_running" ]]; then echo "Service replaced: restart opencode so it reconnects and reloads the tool list."; fi
  return 0
}

cmd_stop() {
  require_docker
  local name
  # Validate both names before making changes; never remove an unrelated container.
  for name in "$CONTAINER" "$PREVIOUS"; do
    if container_exists "$name"; then assert_owned "$name"; fi
  done
  for name in "$CONTAINER" "$PREVIOUS"; do
    if container_exists "$name"; then
      docker stop "$name" >/dev/null
      docker rm "$name" >/dev/null
    fi
  done
  rm -f "$JOURNAL"
  echo "bitbucket-pr-mcp stopped; autostart off"
}

cmd_status() {
  require_docker
  if container_running; then
    docker ps --filter "name=^${CONTAINER}\$" --format 'bitbucket-pr-mcp: {{.Status}}, {{.Ports}}'
    if autostart_enabled; then echo "autostart: on"; else echo "autostart: off"; fi
  elif container_exists; then
    # Exited, or restarting after failures (autostart).
    docker ps -a --filter "name=^${CONTAINER}\$" --format "bitbucket-pr-mcp: {{.Status}} (see: $0 logs)"
    if autostart_enabled; then echo "autostart: on"; else echo "autostart: off"; fi
    return 1
  else
    echo "bitbucket-pr-mcp: not running"
    return 1
  fi
}

cmd_logs() {
  require_docker
  container_exists || die "bitbucket-pr-mcp has not been started"
  docker logs "$@" "$CONTAINER"
}

cmd_check() {
  require_docker
  require_config
  ensure_image
  [[ $# -eq 1 ]] || die "usage: $0 check <PR_URL>"
  run_tool check "$1"
}

cmd_doctor() {
  local failures=0
  ok() { echo "[ok] $*"; }
  bad() { echo "[!!] $*"; failures=$((failures + 1)); }

  if ! command -v docker >/dev/null 2>&1; then
    bad "docker CLI not found -> install Rancher Desktop"
    return 1
  fi
  if docker version >/dev/null 2>&1; then
    ok "Docker engine reachable (context $(docker context show 2>/dev/null || echo '?'))"
  else
    bad "Docker engine not reachable -> start Rancher Desktop with the dockerd (moby) engine"
    return 1
  fi

  local name mode
  for name in "${CONFIG_FILES[@]}"; do
    if [[ ! -f "$CONFIG_DIR/$name" ]]; then
      bad "$CONFIG_DIR/$name missing -> $0 setup"
      continue
    fi
    mode="$(file_mode "$CONFIG_DIR/$name")"
    if [[ "$mode" == "600" ]]; then ok "$name present (600)"; else bad "$name has mode $mode -> chmod 600"; fi
  done

  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    ok "image $IMAGE available"
  else
    bad "image $IMAGE missing -> $0 start (pulls it)"
  fi

  if container_running; then
    ok "service running ($(docker port "$CONTAINER" 9000/tcp 2>/dev/null | paste -sd, -))"
    local addresses exposed
    addresses="$(listeners "$HOST_PORT" | paste -sd, -)"
    exposed="$(non_loopback_listeners "$HOST_PORT")"
    if [[ -n "$exposed" ]]; then
      bad "port $HOST_PORT reachable beyond loopback ($addresses) -> $0 stop, then $0 start"
    elif [[ -n "$addresses" ]]; then
      ok "port $HOST_PORT listens on loopback only ($addresses)"
    else
      echo "[??] could not list listeners on port $HOST_PORT (no usable lsof data); binding unverified"
    fi
    if docker run --rm "$IMAGE" probe-mcp "http://host.docker.internal:$HOST_PORT/mcp" \
      --probe-label "sandbox/container access"; then
      ok "MCP reachable from a container via host.docker.internal:$HOST_PORT (sandbox path)"
    else
      bad "MCP not reachable via host.docker.internal:$HOST_PORT -> $0 logs"
    fi

  else
    bad "service not running -> $0 start"
  fi

  if [[ -f "$CONFIG_DIR/config.toml" && -f "$CONFIG_DIR/bitbucket.pat" ]]; then
    if run_tool preflight; then ok "configuration readable"; else bad "configuration invalid"; fi
  fi

  if [[ "$HOST_PORT" != "9002" ]]; then
    echo "note: the sandbox allowlist must allow host.docker.internal on port $HOST_PORT"
  fi
  [[ $failures -eq 0 ]] && echo "All checks passed." || echo "$failures check(s) failed."
  [[ $failures -eq 0 ]]
}

main() {
  local command="${1:-}"
  [[ $# -gt 0 ]] && shift
  case "$command" in
    ""|-h|--help|help) ;;
    *)
      [[ "$(uname -s)" == "Darwin" ]] || die "only macOS is supported"
      [[ "$EUID" != "0" ]] || die "run as your normal user, without sudo"
      ;;
  esac
  [[ "$HOST_PORT" =~ ^[0-9]+$ ]] && [[ ${#HOST_PORT} -le 5 ]] &&
    ((10#$HOST_PORT >= 1 && 10#$HOST_PORT <= 65535)) || die "BB_MCP_PORT must be between 1 and 65535"
  case "$command" in
    setup) cmd_setup "$@" ;;
    start) cmd_start "$@" ;;
    stop) cmd_stop ;;
    status) cmd_status ;;
    logs) cmd_logs "$@" ;;
    check) cmd_check "$@" ;;
    doctor) cmd_doctor ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
