#!/usr/bin/env bash
# Native Ubuntu 22.04 RC7.2 field transport: Linux assets only; no DSH host binary.
set -euo pipefail

set -euo pipefail
uv python install 3.11
MANAGED_PYBIN="$(uv python find 3.11 --managed-python)"
MANAGED_PYROOT="$(dirname "$(dirname "$(readlink -f "$MANAGED_PYBIN")")")"
# uv's managed distribution is externally managed. Never mutate it: copy it
# into an isolated build-owned runtime, then provision packages into that copy.
PYROOT="$RUNNER_TEMP/rc72-linux-input/python"
mkdir -p "$PYROOT"
cp -a "$MANAGED_PYROOT"/. "$PYROOT"/
rm -f "$PYROOT/lib/python3.11/EXTERNALLY-MANAGED"
PYBIN="$PYROOT/bin/python3.11"
[[ -x "$PYBIN" ]] || { echo "LINUX_COPIED_PYTHON_NOT_EXECUTABLE" >&2; exit 3; }
uv pip install --python "$PYBIN" "pip==25.2" \
  "pytest==8.3.5" "requests==2.34.2" "openpyxl==3.1.5" \
  "python-docx==1.2.0" "python-pptx==1.0.2" \
  "pypdf==7.0.1" "pillow==12.0.0"
"$PYBIN" -B -c "import requests,pytest,openpyxl,docx,pptx,pypdf,PIL,ssl,sqlite3;print('NATIVE_LINUX_PACKAGE_PYTHON_PASS')"
NODEBIN="$(readlink -f "$(command -v node)")"
NODEROOT="$(dirname "$(dirname "$NODEBIN")")"
node --version | grep -x 'v24.9.0'

python -m rc7_release.plugin_payload acquire --repo-root .
mkdir -p "$RUNNER_TEMP/rc72-linux-input/bsk" \
  "$RUNNER_TEMP/rc72-linux-input/extension" \
  "$RUNNER_TEMP/rc72-linux-input/node-execution" \
  "$RUNNER_TEMP/rc72-linux-input/pw-browsers"
BSK_URL="https://github.com/Tencent/BrowserSkill/releases/download/cli-v0.4.1/bsk-v0.4.1-x86_64-unknown-linux-musl.tar.gz"
EXT_URL="https://github.com/Tencent/BrowserSkill/releases/download/ext-v0.4.1/browser-skill-extension-v0.4.1-chrome.zip"
curl -fL --retry 3 --retry-delay 2 "$BSK_URL" -o "$RUNNER_TEMP/rc72-linux-input/bsk.tar.gz"
curl -fL --retry 3 --retry-delay 2 "$EXT_URL" -o "$RUNNER_TEMP/rc72-linux-input/extension.zip"
tar -xzf "$RUNNER_TEMP/rc72-linux-input/bsk.tar.gz" -C "$RUNNER_TEMP/rc72-linux-input/bsk"
unzip -q "$RUNNER_TEMP/rc72-linux-input/extension.zip" -d "$RUNNER_TEMP/rc72-linux-input/extension"
BSK_BIN="$(find "$RUNNER_TEMP/rc72-linux-input/bsk" -type f -name bsk -print -quit)"
[[ -n "$BSK_BIN" ]] || { echo "NATIVE_LINUX_BSK_NOT_FOUND" >&2; exit 3; }
chmod +x "$BSK_BIN"
"$BSK_BIN" --version | grep -F '0.4.1'
EXT_MANIFEST="$(find "$RUNNER_TEMP/rc72-linux-input/extension" -type f -name manifest.json -print -quit)"
[[ -n "$EXT_MANIFEST" ]] || { echo "NATIVE_LINUX_BSK_EXTENSION_NOT_FOUND" >&2; exit 3; }
EXT_ROOT="$(dirname "$EXT_MANIFEST")"

NODE_EXEC="$RUNNER_TEMP/rc72-linux-input/node-execution"
npm install --prefix "$NODE_EXEC" --save-exact --omit=dev --ignore-scripts --no-audit --no-fund "playwright@1.65.0"
PLAYWRIGHT_BROWSERS_PATH="$RUNNER_TEMP/rc72-linux-input/pw-browsers" \
  node "$NODE_EXEC/node_modules/playwright/cli.js" install chromium

{
  echo "RC72_LINUX_PY_ROOT=$PYROOT"
  echo "RC72_LINUX_NODE_ROOT=$NODEROOT"
  echo "RC72_LINUX_BSK_BIN=$BSK_BIN"
  echo "RC72_LINUX_EXT_ROOT=$EXT_ROOT"
  echo "RC72_LINUX_NODE_EXEC=$NODE_EXEC"
  echo "RC72_LINUX_BROWSER_ROOT=$RUNNER_TEMP/rc72-linux-input/pw-browsers"
} >> "$GITHUB_ENV"
printf '{"status":"PASS","source_commit":"%s","target":"ubuntu-22.04-x86_64","native_python":true,"native_node":true,"browserskill_041":true,"linux_chromium":true,"field_verified":false,"bank_final":false}\n' "$GITHUB_SHA" > "$RUNNER_TEMP/linux-input-acquisition.json"

# Environment variables saved by the acquisition phase become available in this shell.
set -a
. "$GITHUB_ENV"
set +a

set -euo pipefail
mkdir -p "$RUNNER_TEMP/rc72-linux-stage" "$RUNNER_TEMP/rc72-linux-dist"
python -m rc7_release.rc72_linux_field_portable stage \
  --repo-root . --output "$RUNNER_TEMP/rc72-linux-stage" --source-commit "$GITHUB_SHA" \
  --python-root "$RC72_LINUX_PY_ROOT" \
  --node-root "$RC72_LINUX_NODE_ROOT" \
  --bsk-cli "$RC72_LINUX_BSK_BIN" \
  --browser-root "$RC72_LINUX_BROWSER_ROOT" \
  --extension-root "$RC72_LINUX_EXT_ROOT" \
  --node-execution-root "$RC72_LINUX_NODE_EXEC" | tee "$RUNNER_TEMP/linux-stage-evidence.json"
PACKAGE="$RUNNER_TEMP/rc72-linux-stage/PFC-AITest-DSH-RC7.2-UBUNTU22-X64-FIELD"
ARCHIVE="$RUNNER_TEMP/rc72-linux-dist/RC72-LINUX-FIELD-UBUNTU22-X64-${GITHUB_SHA:0:12}.tar.gz"
python -m rc7_release.rc72_linux_field_portable archive \
  --package-root "$PACKAGE" --output "$ARCHIVE" | tee "$RUNNER_TEMP/linux-archive-evidence.json"
echo "RC72_LINUX_ARCHIVE=$ARCHIVE" >> "$GITHUB_ENV"

# Same one-shot job independently extracts and proves the exact just-built archive.
set -euo pipefail
cd "$RUNNER_TEMP/rc72-linux-dist"
sha256sum -c "$(basename "$RC72_LINUX_ARCHIVE").sha256"
mkdir -p "$RUNNER_TEMP/rc72-linux-clean"
tar -xzf "$RC72_LINUX_ARCHIVE" -C "$RUNNER_TEMP/rc72-linux-clean"
ROOT="$RUNNER_TEMP/rc72-linux-clean/PFC-AITest-DSH-RC7.2-UBUNTU22-X64-FIELD"
PY="$ROOT/workspace-template/runtime/python/bin/python3"
NODE="$ROOT/workspace-template/runtime/node/bin/node"
BSK="$ROOT/workspace-template/runtime/browser/browserskill/bsk"
cd "$ROOT"
"$PY" -B -m rc7_release.rc72_linux_field_portable verify \
  --package-root "$ROOT" --expected-source-commit "$GITHUB_SHA" | tee "$RUNNER_TEMP/linux-clean-identity.json"
"$PY" -B -c "import sys,ssl,sqlite3,pytest,requests,openpyxl,docx,pptx,pypdf,PIL,rc7_runtime,rc7_release;assert sys.executable.startswith('$ROOT/');print('LINUX_PACKAGE_LOCAL_PYTHON_AND_MODULE_IMPORT_PASS')"
"$NODE" --version | grep -x 'v24.9.0'
"$BSK" --version | grep -F '0.4.1'
PFC_RC72_LINUX_PROBE_ONLY=1 bash packaging/rc7.2/LINUX-FIELD-AITEST.sh | tee "$RUNNER_TEMP/linux-launch-probe.txt"
( cd "$ROOT/workspace-template/runtime/node-execution" && \
  PLAYWRIGHT_BROWSERS_PATH="$ROOT/workspace-template/runtime/browser/pw-browsers" \
  "$NODE" -e 'const {chromium}=require("playwright"); (async()=>{const browser=await chromium.launch({headless:true,args:["--no-sandbox"]});const page=await browser.newPage();await page.goto("data:text/html,<title>RC72 Linux Offline</title>");if((await page.title())!=="RC72 Linux Offline")throw Error("NO_BROWSER_OFFLINE_PROOF");await browser.close();console.log("LINUX_PLAYWRIGHT_CHROMIUM_OFFLINE_PASS")})().catch(x=>{console.error(x);process.exit(1)})' ) | tee "$RUNNER_TEMP/linux-browser-smoke.txt"
"$PY" -B -m rc7_release.rc72_target_linux_reality probe \
  --source-commit "$GITHUB_SHA" --runner-kind GITHUB_HOSTED_GENERIC \
  --runner-identity "github-hosted-ubuntu22-x86_64" \
  --output "$RUNNER_TEMP/linux-q3-generic-hold.json" --require-hold
# Explicitly verify what this package cannot assert:
"$PY" -B -c 'import json; m=json.load(open("LINUX_FIELD_PACKAGE.json")); assert m["field_verified"] is False and m["bank_final"] is False; assert m["dsh_main_payload"]["bundled"] is False; assert m["restricted_graph_component"]["gitnexus_bundled"] is False;print("LINUX_FIELD_HOLD_BOUNDARIES_PASS")'
