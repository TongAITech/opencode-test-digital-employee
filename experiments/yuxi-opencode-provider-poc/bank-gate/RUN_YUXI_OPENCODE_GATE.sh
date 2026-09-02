#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_WORKSPACE="$ROOT/.probe-workspace"
AGENT_SOURCE="$ROOT/yuxi-model-provider-proxy.md"
LOG_FILE="$ROOT/opencode-probe-server.log"
BASE_URL="${OPENCODE_SERVER_URL:-http://127.0.0.1:4096}"
OWN_SERVER=0
SERVER_PID=""

fail() {
  printf 'YUXI_OPENCODE_BANK_GATE bootstrap error: %s\n' "$1" >&2
  exit 1
}

command -v node >/dev/null 2>&1 || fail "Node.js 20+ not found in PATH"
NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
[ "$NODE_MAJOR" -ge 20 ] || fail "Node.js 20+ required; found $(node --version)"
[ -f "$AGENT_SOURCE" ] || fail "missing yuxi-model-provider-proxy.md"
[ -f "$ROOT/live_probe.mjs" ] || fail "missing live_probe.mjs"

mkdir -p "$PROBE_WORKSPACE/.opencode/agents" || fail "cannot create isolated probe workspace"
cp "$AGENT_SOURCE" "$PROBE_WORKSPACE/.opencode/agents/yuxi-model-provider-proxy.md" || fail "cannot stage provider-proxy agent"

# Resolve through Windows Node rather than shell path rules, then encode exactly
# as the official OpenCode v1.14.22 JS SDK does for x-opencode-directory.
PROBE_NATIVE="$(node -e 'const p=require("node:path"); console.log(p.resolve(process.argv[1]))' "$PROBE_WORKSPACE")"
PROBE_DIRECTORY_HEADER="$(node -e 'console.log(encodeURIComponent(process.argv[1]))' "$PROBE_NATIVE")"

server_reachable() {
  node - "$1" <<'NODE' >/dev/null 2>&1
const base = process.argv[2].replace(/\/+$/, "")
fetch(base + "/global/health")
  .then(() => process.exit(0))
  .catch(() => process.exit(1))
NODE
}

cleanup() {
  if [ "$OWN_SERVER" -eq 1 ] && [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

if ! server_reachable "$BASE_URL"; then
  command -v opencode >/dev/null 2>&1 || fail "OpenCode CLI not found and no server is reachable at $BASE_URL"
  PORT="${YUXI_OC_GATE_PORT:-4097}"
  BASE_URL="http://127.0.0.1:${PORT}"
  : >"$LOG_FILE"
  (
    cd "$PROBE_WORKSPACE" || exit 1
    opencode serve --port "$PORT" >>"$LOG_FILE" 2>&1
  ) &
  SERVER_PID=$!
  OWN_SERVER=1

  READY=0
  for _ in $(seq 1 30); do
    if server_reachable "$BASE_URL"; then
      READY=1
      break
    fi
    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if [ "$READY" -ne 1 ]; then
    printf 'Temporary OpenCode server did not become ready. Log: %s\n' "$LOG_FILE" >&2
    tail -n 40 "$LOG_FILE" >&2 2>/dev/null || true
    exit 1
  fi
fi

printf 'Running isolated Yuxi -> OpenCode bank gate against %s\n' "$BASE_URL" >&2
printf 'Probe workspace: %s\n' "$PROBE_NATIVE" >&2

node "$ROOT/live_probe.mjs" \
  --base-url "$BASE_URL" \
  --directory "$PROBE_DIRECTORY_HEADER" \
  "$@"
STATUS=$?

if [ "$STATUS" -eq 2 ]; then
  printf '\nThe probe returned NEEDS_MODEL_SELECTION. Re-run this same command with:\n' >&2
  printf '  --provider-id <providerID> --model-id <modelID>\n' >&2
fi

exit "$STATUS"
