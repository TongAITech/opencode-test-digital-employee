#!/usr/bin/env bash
# Install the five pinned, licensed additions from package-local archives only.
# This uses a bank-approved DSH binary and existing isolated profile.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PY="$ROOT/workspace-template/runtime/python/bin/python3"
NODE_ROOT="$ROOT/workspace-template/runtime/node"
PNPM_CLI="$ROOT/workspace-template/runtime/node-execution/node_modules/pnpm/bin/pnpm.cjs"
ARCHIVE="$ROOT/rc7_release/vendor/dsh-additional-plugins-payload.zip"
PROFILE="${PFC_RC72_DSH_PROFILE:-rc7.2-bank-native}"
DSH_BIN="${PFC_RC72_DSH_HOST_BIN:-}"
STATE="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
case "$PROFILE" in web|headless|sdk|sdk-minimal|acp) echo "NATIVE_PLUGIN_PROFILE_PROTECTED:$PROFILE" >&2; exit 4;; esac
[[ -x "$PY" && -x "$NODE_ROOT/bin/node" && -f "$PNPM_CLI" && -f "$ARCHIVE" ]] || { echo "NATIVE_PLUGIN_PAYLOAD_OR_RUNTIME_MISSING" >&2; exit 4; }
[[ -n "$DSH_BIN" && -x "$DSH_BIN" ]] || { echo "NATIVE_BANK_DSH_HOST_REQUIRED" >&2; exit 4; }
export PATH="$NODE_ROOT/bin:$ROOT/workspace-template/runtime/node-execution/node_modules/.bin:$PATH"
export npm_config_offline=true
export PNPM_CONFIG_OFFLINE=true
export PNPM_HOME="$STATE/pnpm"
mkdir -p "$STATE"
export PFC_AITEST_STATE_DIR="$STATE"
cd "$ROOT"
"$PY" -B -m rc7_release.rc72_native_additional_plugins inspect --repo-root "$ROOT"
DEST="$STATE/plugin-runtime/dsh-additions"
if [[ ! -f "$DEST/.verified-source.sha256" ]]; then
  [[ ! -e "$DEST" ]] || { echo "NATIVE_PLUGIN_RUNTIME_UNVERIFIED_EXISTS:$DEST" >&2; exit 4; }
  mkdir -p "$DEST"
  "$PY" - "$ARCHIVE" "$DEST" <<'PY'
import pathlib,sys,zipfile
archive=pathlib.Path(sys.argv[1]); root=pathlib.Path(sys.argv[2]).resolve()
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        if item.is_dir(): continue
        rel=pathlib.Path(item.filename)
        if rel.is_absolute() or ".." in rel.parts: raise SystemExit("NATIVE_PLUGIN_ZIP_TRAVERSAL")
        dest=(root/rel).resolve()
        if not dest.is_relative_to(root): raise SystemExit("NATIVE_PLUGIN_ZIP_ESCAPE")
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(z.read(item))
PY
  "$PY" - "$ARCHIVE" "$DEST/.verified-source.sha256" <<'PY'
import hashlib,pathlib,sys
path=pathlib.Path(sys.argv[1])
out=pathlib.Path(sys.argv[2]);out.write_text(hashlib.sha256(path.read_bytes()).hexdigest()+"\n")
PY
fi
"$NODE_ROOT/bin/node" "$PNPM_CLI" --version
for module in \
  "@michengai/dsh-skills-manager" \
  "dsh-mnemon" \
  "dsh-archify" \
  "@liustack/modlens" \
  "graph-memory"
do
  PACKAGE="$DEST/node_modules/$module"
  [[ -f "$PACKAGE/package.json" ]] || { echo "NATIVE_PLUGIN_PACKAGE_MISSING:$module" >&2; exit 4; }
  echo "[RC7.2] Installing licensed plugin $module into isolated profile $PROFILE (offline link)."
  "$DSH_BIN" plugin --profile "$PROFILE" add "link:$PACKAGE" --offline --ignore-scripts
done
echo "RC72_NATIVE_ADDON_PROFILE_INSTALL_PASS; restart DSH host, then verify profile bundle activation and tool calls."
