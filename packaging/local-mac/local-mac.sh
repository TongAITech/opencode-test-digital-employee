#!/bin/bash
set -euo pipefail

SELF="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASELINE_SHA="4edd78536633d4258705c6083fe55b44e51f54bb"
PLAYWRIGHT_VERSION="1.62.0"
PYTHON_VERSION="3.12.10"
PYTHON_RELEASE="20250529"
OPENCODE_VERSION="1.18.3"
CHROME_VERSION="151.0.7922.34"
CODEGRAPH_VERSION="0.20.1"
RIPGREP_VERSION="15.1.0"

fail() { printf '[LOCAL MAC FAIL] %s\n' "$1" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing tool: $1"; }
sha_file() { shasum -a 256 "$1" | awk '{print $1}'; }
verify_sha() {
  local path="$1" expected="$2" label="$3" actual
  actual="$(sha_file "$path")"
  [[ "$actual" == "$expected" ]] || fail "$label sha256 mismatch: expected=$expected actual=$actual"
}
download() { curl --fail --location --retry 3 --connect-timeout 20 "$1" -o "$2"; }

normalize_arch() {
  case "${1:-}" in
    arm64|aarch64) printf 'arm64\n' ;;
    x86_64|amd64|x64) printf 'x64\n' ;;
    *) fail "unsupported Mac architecture: ${1:-UNKNOWN}" ;;
  esac
}

select_profile() {
  ARCH="$(normalize_arch "${PFC_MAC_ARCH:-$(uname -m)}")"
  case "$ARCH" in
    arm64)
      PY_ARCH="aarch64"
      OPENCODE_ASSET="opencode-darwin-arm64.zip"
      OPENCODE_SHA="946f62b155638b911144b7bef520ee4a6442f696297907873463bca3524e40ef"
      CHROME_PLATFORM="mac-arm64"
      CODEGRAPH_ASSET="codegraph-server-darwin-arm64"
      CODEGRAPH_SHA="460d830e93467efb9270bfe6ac01f34e32d3369041e3a93699a9887053d18cc3"
      RG_ASSET="ripgrep-15.1.0-aarch64-apple-darwin.tar.gz"
      RG_DIR="ripgrep-15.1.0-aarch64-apple-darwin"
      RG_SHA="378e973289176ca0c6054054ee7f631a065874a352bf43f0fa60ef079b6ba715"
      LOCK_SOURCE="$HERE/runtime-lock.mac-arm64.json"
      ;;
    x64)
      PY_ARCH="x86_64"
      OPENCODE_ASSET="opencode-darwin-x64.zip"
      OPENCODE_SHA="4ea147867ba19e4ec03559df557811f1674f40788aea4d10326dc563b7667c6d"
      CHROME_PLATFORM="mac-x64"
      CODEGRAPH_ASSET="codegraph-server-darwin-x64"
      CODEGRAPH_SHA="5aa863ea529afcf6664cf40fcd7079d4121e8348acc1c9e0ebbc0c4675246ddd"
      RG_ASSET="ripgrep-15.1.0-x86_64-apple-darwin.tar.gz"
      RG_DIR="ripgrep-15.1.0-x86_64-apple-darwin"
      RG_SHA="64811cb24e77cac3057d6c40b63ac9becf9082eedd54ca411b475b755d334882"
      LOCK_SOURCE="$HERE/runtime-lock.mac-x64.json"
      ;;
  esac
}

runtime_tree_sha() {
  local python_bin="$1" runtime_root="$2"
  "$python_bin" - "$runtime_root" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
records = []
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(root).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    records.append(f"{digest}  {rel}")
payload = ("\n".join(records) + "\n").encode("utf-8")
print(hashlib.sha256(payload).hexdigest())
PY
}

cmd_build() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "offline package assembly must run on macOS"
  for tool in curl tar unzip shasum git; do need "$tool"; done
  select_profile

  local repo_root source_sha output_dir package_name build_root staging downloads runtime
  repo_root="$(cd -- "$HERE/../.." && pwd)"
  [[ -d "$repo_root/workspace-template" ]] || fail "build must run from Git source packaging/local-mac"
  source_sha="$(git -C "$repo_root" rev-parse HEAD)"
  output_dir="${PFC_MAC_OUTPUT_DIR:-$HERE/dist}"
  package_name="PFC-LOCAL-MAC-R1R4-${ARCH}-${source_sha:0:12}"
  build_root="$(mktemp -d "${TMPDIR:-/tmp}/pfc-local-mac-build.XXXXXX")"
  BUILD_ROOT="$build_root"
  trap '[[ -z "${BUILD_ROOT:-}" ]] || rm -rf "$BUILD_ROOT"' EXIT
  staging="$build_root/$package_name"
  downloads="$build_root/downloads"
  mkdir -p "$staging" "$downloads" "$output_dir"

  printf 'LOCAL_MAC_BUILD_SOURCE=%s\n' "$source_sha"
  printf 'LOCAL_MAC_BUILD_BASELINE=%s\n' "$BASELINE_SHA"
  printf 'LOCAL_MAC_BUILD_ARCH=%s\n' "$ARCH"

  cp -a "$repo_root/workspace-template" "$staging/workspace-template"
  cp "$SELF" "$staging/local-mac.sh"
  cp "$LOCK_SOURCE" "$staging/runtime-lock.json"
  chmod +x "$staging/local-mac.sh"

  runtime="$staging/workspace-template/runtime"
  rm -rf "$runtime"
  mkdir -p "$runtime/python" "$runtime/opencode" "$runtime/browser" \
    "$runtime/code-intelligence/codegraph" "$runtime/ripgrep" "$runtime/shell"

  local py_asset py_asset_url py_expected python_bin
  py_asset="cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-${PY_ARCH}-apple-darwin-install_only.tar.gz"
  py_asset_url="${py_asset/+/%2B}"
  download "https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/${py_asset_url}" \
    "$downloads/$py_asset"
  download "https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/${py_asset_url}.sha256" \
    "$downloads/$py_asset.sha256"
  py_expected="$(awk '{print $1}' "$downloads/$py_asset.sha256")"
  [[ "$py_expected" =~ ^[0-9a-fA-F]{64}$ ]] || fail "portable Python upstream sha256 sidecar invalid"
  verify_sha "$downloads/$py_asset" "$py_expected" "portable Python"
  tar -xzf "$downloads/$py_asset" -C "$runtime/python" --strip-components=1
  python_bin="$runtime/python/bin/python3"
  [[ -x "$python_bin" ]] || fail "portable Python executable missing after extraction"
  ln -sfn "bin/python3" "$runtime/python/python.exe"
  "$python_bin" -m ensurepip --upgrade >/dev/null 2>&1 || true
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 "$python_bin" -m pip install \
    --disable-pip-version-check --no-cache-dir "playwright==${PLAYWRIGHT_VERSION}"
  "$python_bin" -c 'from playwright.sync_api import sync_playwright; print("PFC_MAC_PLAYWRIGHT_IMPORT=PASS")'

  local opencode_url open_version
  opencode_url="https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/${OPENCODE_ASSET}"
  download "$opencode_url" "$downloads/$OPENCODE_ASSET"
  verify_sha "$downloads/$OPENCODE_ASSET" "$OPENCODE_SHA" "OpenCode"
  unzip -q "$downloads/$OPENCODE_ASSET" -d "$runtime/opencode"
  [[ -f "$runtime/opencode/opencode" ]] || fail "OpenCode binary missing after extraction"
  chmod +x "$runtime/opencode/opencode"
  open_version="$("$runtime/opencode/opencode" --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
  [[ "$open_version" == "$OPENCODE_VERSION" ]] || fail "OpenCode version mismatch after extraction: $open_version"

  local chrome_asset chrome_url chrome_sha chrome_bin
  chrome_asset="chrome-${CHROME_PLATFORM}.zip"
  chrome_url="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/${CHROME_PLATFORM}/${chrome_asset}"
  download "$chrome_url" "$downloads/$chrome_asset"
  chrome_sha="$(sha_file "$downloads/$chrome_asset")"
  if [[ -n "${PFC_MAC_CHROME_SHA256:-}" ]]; then
    [[ "$chrome_sha" == "$PFC_MAC_CHROME_SHA256" ]] || fail "Chrome sha256 mismatch"
  fi
  unzip -q "$downloads/$chrome_asset" -d "$runtime/browser"
  chrome_bin="$runtime/browser/chrome-${CHROME_PLATFORM}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
  [[ -x "$chrome_bin" ]] || fail "Chrome for Testing executable missing after extraction"

  local codegraph_url
  codegraph_url="https://github.com/codegraph-ai/CodeGraph/releases/download/v${CODEGRAPH_VERSION}/${CODEGRAPH_ASSET}"
  download "$codegraph_url" "$downloads/$CODEGRAPH_ASSET"
  verify_sha "$downloads/$CODEGRAPH_ASSET" "$CODEGRAPH_SHA" "CodeGraph"
  cp "$downloads/$CODEGRAPH_ASSET" "$runtime/code-intelligence/codegraph/$CODEGRAPH_ASSET"
  chmod +x "$runtime/code-intelligence/codegraph/$CODEGRAPH_ASSET"

  local rg_url
  rg_url="https://github.com/BurntSushi/ripgrep/releases/download/${RIPGREP_VERSION}/${RG_ASSET}"
  download "$rg_url" "$downloads/$RG_ASSET"
  verify_sha "$downloads/$RG_ASSET" "$RG_SHA" "ripgrep"
  tar -xzf "$downloads/$RG_ASSET" -C "$downloads"
  cp "$downloads/$RG_DIR/rg" "$runtime/ripgrep/rg"
  chmod +x "$runtime/ripgrep/rg"

  cat >"$runtime/shell/bash" <<'BASH_WRAPPER'
#!/bin/bash
set -e
RUNTIME_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ "${1:-}" == "-lc" && $# -ge 2 ]]; then
  CMD="$2"
  exec /bin/bash -lc "export PATH='$RUNTIME_ROOT/opencode:$RUNTIME_ROOT/ripgrep:/usr/bin:/bin:/usr/sbin:/sbin':\"\${PATH:-}\"; $CMD"
fi
export PATH="$RUNTIME_ROOT/opencode:$RUNTIME_ROOT/ripgrep:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
exec /bin/bash "$@"
BASH_WRAPPER
  chmod +x "$runtime/shell/bash"

  local runtime_identity
  runtime_identity="$(runtime_tree_sha "$python_bin" "$runtime")"
  [[ "$runtime_identity" =~ ^[0-9a-f]{64}$ ]] || fail "runtime tree identity generation failed"

  "$python_bin" - "$staging" "$source_sha" "$BASELINE_SHA" "$ARCH" \
    "$py_expected" "$OPENCODE_SHA" "$chrome_sha" "$CODEGRAPH_SHA" "$RG_SHA" "$runtime_identity" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
source_sha, baseline, arch = sys.argv[2:5]
hashes = dict(zip(
    ("python_archive", "opencode_archive", "chrome_archive", "codegraph_binary", "ripgrep_archive"),
    sys.argv[5:10],
))
runtime_tree_sha256 = sys.argv[10]
identity = {
    "schema_version": "pfc.local-mac.package-identity.v1",
    "package_id": f"PFC_LOCAL_MAC_R1_R4_{arch.upper()}",
    "source_commit": source_sha,
    "baseline_commit": baseline,
    "architecture_baseline": "v7/FROZEN/UNCHANGED",
    "platform": "macOS",
    "arch": arch,
    "opencode_version": "1.18.3",
    "runtime_truth": "R1_EVENT_STREAM",
    "bank_field_validation_package": False,
    "local_validation_package": True,
}
(root / "PACKAGE_IDENTITY.json").write_text(
    json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
manifest = {
    "schema_version": "pfc.local-mac.package-manifest.v1",
    "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "identity": identity,
    "payload_sha256": hashes,
    "runtime_tree_sha256": runtime_tree_sha256,
    "chrome_archive_verification": (
        "PREPINNED_AND_VERIFIED"
        if os.environ.get("PFC_MAC_CHROME_SHA256")
        else "RECORDED_AT_ASSEMBLY_NOT_PREPINNED"
    ),
    "target_runtime_policy": {
        "internet_required": False,
        "dependency_install_allowed": False,
        "system_python_fallback": False,
    },
}
(root / "PACKAGE_MANIFEST.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
profile = {
    "schema_version": "pfc.local-reference-profile.v1",
    "project": "PFC",
    "mode": "LOCAL_REFERENCE_TARGET",
    "target_root": None,
    "target_binding": "PENDING",
    "credentials_bundled": False,
    "bank_source_truth": False,
}
(root / "PFC_PROJECT_PROFILE.json").write_text(
    json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

  local archive archive_sha
  archive="$output_dir/$package_name.tar.gz"
  tar -czf "$archive" -C "$build_root" "$package_name"
  archive_sha="$(sha_file "$archive")"
  printf '%s  %s\n' "$archive_sha" "$(basename "$archive")" >"$archive.sha256"
  printf 'LOCAL_MAC_OFFLINE_PACKAGE_BUILD=PASS\n'
  printf 'PACKAGE=%s\n' "$archive"
  printf 'PACKAGE_SHA256=%s\n' "$archive_sha"
  printf 'RUNTIME_TREE_SHA256=%s\n' "$runtime_identity"
  printf 'CHROME_ARCHIVE_SHA256=%s\n' "$chrome_sha"
}

project_paths() {
  PROJECT_ROOT="${PFC_LOCAL_VALIDATION_ROOT:-$HOME/OpenCode-Digital-Employee-Local-Validation}"
  WORKSPACE="$PROJECT_ROOT/workspace"
  DURABLE_ROOT="$PROJECT_ROOT/durable"
  CONTROL_ROOT="$PROJECT_ROOT/control"
  CURRENT_POINTER="$CONTROL_ROOT/current.json"
}

cmd_install() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "this package can only be installed on macOS"
  [[ -f "$HERE/PACKAGE_IDENTITY.json" ]] || fail "run install from the extracted offline package"
  [[ -f "$HERE/PACKAGE_MANIFEST.json" ]] || fail "PACKAGE_MANIFEST.json missing"
  [[ -f "$HERE/runtime-lock.json" ]] || fail "runtime-lock.json missing"
  [[ -d "$HERE/workspace-template" ]] || fail "workspace-template missing"

  local python_source package_meta package_id source_commit package_arch host_arch expected_runtime actual_runtime
  python_source="$HERE/workspace-template/runtime/python/bin/python3"
  [[ -x "$python_source" ]] || fail "portable Python missing from offline package"
  host_arch="$(normalize_arch "$(uname -m)")"

  package_meta="$("$python_source" - "$HERE/PACKAGE_IDENTITY.json" "$HERE/PACKAGE_MANIFEST.json" "$host_arch" <<'PY'
import json
import sys
from pathlib import Path

identity = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if identity.get("arch") != sys.argv[3]:
    raise SystemExit(f"ARCH_MISMATCH package={identity.get('arch')} host={sys.argv[3]}")
if manifest.get("identity") != identity:
    raise SystemExit("PACKAGE_IDENTITY_MANIFEST_MISMATCH")
runtime_sha = manifest.get("runtime_tree_sha256")
if not isinstance(runtime_sha, str) or len(runtime_sha) != 64:
    raise SystemExit("RUNTIME_TREE_IDENTITY_MISSING")
print(identity["package_id"])
print(identity["source_commit"])
print(identity["arch"])
print(runtime_sha)
PY
)" || fail "package architecture/identity validation failed"
  package_id="$(printf '%s\n' "$package_meta" | sed -n '1p')"
  source_commit="$(printf '%s\n' "$package_meta" | sed -n '2p')"
  package_arch="$(printf '%s\n' "$package_meta" | sed -n '3p')"
  expected_runtime="$(printf '%s\n' "$package_meta" | sed -n '4p')"
  actual_runtime="$(runtime_tree_sha "$python_source" "$HERE/workspace-template/runtime")"
  [[ "$actual_runtime" == "$expected_runtime" ]] ||
    fail "offline runtime tree identity mismatch: expected=$expected_runtime actual=$actual_runtime"

  project_paths
  if [[ -f "$WORKSPACE/.PFC_READY" && "${PFC_LOCAL_INSTALL_REPLACE:-0}" != "1" ]]; then
    printf 'LOCAL_MAC_INSTALL=ALREADY_READY\nPROJECT_ROOT=%s\n' "$PROJECT_ROOT"
    return 0
  fi
  if [[ -e "$WORKSPACE" && "${PFC_LOCAL_INSTALL_REPLACE:-0}" != "1" ]]; then
    fail "workspace exists but is not READY; set PFC_LOCAL_INSTALL_REPLACE=1 to replace it"
  fi
  [[ "${PFC_LOCAL_INSTALL_REPLACE:-0}" != "1" ]] || rm -rf "$WORKSPACE"
  mkdir -p "$PROJECT_ROOT" "$DURABLE_ROOT/state" "$DURABLE_ROOT/logs" "$CONTROL_ROOT" "$WORKSPACE"
  touch "$WORKSPACE/.PFC_INSTALLING"

  cp -a "$HERE/workspace-template/." "$WORKSPACE/"
  cp "$HERE/PACKAGE_IDENTITY.json" "$WORKSPACE/PACKAGE_IDENTITY.json"
  cp "$HERE/PACKAGE_MANIFEST.json" "$WORKSPACE/PACKAGE_MANIFEST.json"
  cp "$HERE/PFC_PROJECT_PROFILE.json" "$WORKSPACE/PFC_PROJECT_PROFILE.json"
  cp "$HERE/runtime-lock.json" "$WORKSPACE/runtime-lock.json"

  local python_bin installed_runtime
  python_bin="$WORKSPACE/runtime/python/bin/python3"
  ln -sfn "bin/python3" "$WORKSPACE/runtime/python/python.exe"
  [[ -x "$python_bin" ]] || fail "installed portable Python missing"
  installed_runtime="$(runtime_tree_sha "$python_bin" "$WORKSPACE/runtime")"
  [[ "$installed_runtime" == "$expected_runtime" ]] ||
    fail "installed runtime tree identity mismatch: expected=$expected_runtime actual=$installed_runtime"

  "$python_bin" - "$WORKSPACE" "$PROJECT_ROOT" "$DURABLE_ROOT" "$package_id" "$source_commit" "$package_arch" "$expected_runtime" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

workspace, project, durable = map(Path, sys.argv[1:4])
package_id, source_commit, arch, runtime_tree_sha256 = sys.argv[4:8]
payload = {
    "schema_version": "pfc.local-mac.installation.v1",
    "package_id": package_id,
    "source_commit": source_commit,
    "installed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "platform": "macOS",
    "arch": arch,
    "project_root": str(project.resolve()),
    "runtime_workspace": str(workspace.resolve()),
    "durable_root": str(durable.resolve()),
    "runtime_tree_sha256": runtime_tree_sha256,
    "runtime_truth": "R1_EVENT_STREAM",
    "local_pfc_target_binding": "PENDING",
    "bank_field_validation_package": False,
}
(workspace / "PFC_R1_R4_INSTALLATION.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

  export AITEST_WORKSPACE_ROOT="$WORKSPACE"
  export AITEST_RUNTIME_SPINE_DB="$DURABLE_ROOT/state/runtime-spine.db"
  export PFC_LOCAL_STATE_ROOT="$DURABLE_ROOT"
  export PFC_REPO_ROOT="${PFC_LOCAL_TARGET_ROOT:-$PROJECT_ROOT/targets/PFC}"
  export PYTHONPATH="$WORKSPACE/ai-test/runtime${PYTHONPATH:+:$PYTHONPATH}"
  export AITEST_RUNTIME_LOCK="$WORKSPACE/runtime-lock.json"
  export AITEST_RUNTIME_PYTHON="$WORKSPACE/runtime/python/python.exe"

  local truth_tmp
  truth_tmp="$DURABLE_ROOT/state/local-mac-truth.tmp.json"
  "$python_bin" -m aitest_runtime.product_entry interactive-truth --target status >"$truth_tmp" ||
    fail "R1 Event Stream initialization failed"
  "$python_bin" - "$truth_tmp" "$DURABLE_ROOT/state/local-mac-truth.json" <<'PY'
import json
import os
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:])
payload = json.loads(source.read_text(encoding="utf-8"))
if payload.get("truth_source") != "R1_EVENT_STREAM":
    raise SystemExit("truth source mismatch")
if payload.get("conversation_is_not_truth") is not True:
    raise SystemExit("conversation truth guard failed")
if (payload.get("legacy_store") or {}).get("product_runtime_writes_allowed") is not False:
    raise SystemExit("legacy write guard failed")
if int(payload.get("extension_count") or 0) < 25:
    raise SystemExit("canonical extension composition incomplete")
os.replace(source, target)
PY
  [[ -f "$AITEST_RUNTIME_SPINE_DB" ]] || fail "runtime-spine.db was not created"

  "$python_bin" - "$CURRENT_POINTER" "$WORKSPACE" "$DURABLE_ROOT" "$package_id" "$source_commit" "$package_arch" "$expected_runtime" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

pointer, workspace, durable = map(Path, sys.argv[1:4])
package_id, source_commit, arch, runtime_tree_sha256 = sys.argv[4:8]
payload = {
    "schema_version": "pfc.local-mac.current-pointer.v1",
    "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "package_id": package_id,
    "source_commit": source_commit,
    "arch": arch,
    "active_workspace": str(workspace.resolve()),
    "durable_root": str(durable.resolve()),
    "workspace_identity": "PFC_LOCAL_MAC_R1_R4_VALIDATION_WORKSPACE",
    "runtime_tree_sha256": runtime_tree_sha256,
    "runtime_truth": "R1_EVENT_STREAM",
}
pointer.parent.mkdir(parents=True, exist_ok=True)
tmp = pointer.with_suffix(".tmp")
tmp.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.replace(tmp, pointer)
PY

  cat >"$WORKSPACE/.PFC_READY" <<EOF
PFC_LOCAL_MAC_READY=YES
PACKAGE_ID=$package_id
SOURCE_COMMIT=$source_commit
ARCH=$package_arch
RUNTIME_TREE_SHA256=$expected_runtime
RUNTIME_TRUTH=R1_EVENT_STREAM
EOF
  rm -f "$WORKSPACE/.PFC_INSTALLING"
  cp "$SELF" "$PROJECT_ROOT/local-mac.sh"
  chmod +x "$PROJECT_ROOT/local-mac.sh"

  printf 'LOCAL_MAC_INSTALL=PASS\n'
  printf 'RUNTIME_TREE_IDENTITY=PASS\n'
  printf 'R1_EVENT_STREAM=READY\n'
  printf 'PROJECT_ROOT=%s\n' "$PROJECT_ROOT"
  printf 'NEXT=cd %q && ./local-mac.sh bind /absolute/path/to/local/PFC\n' "$PROJECT_ROOT"
}

runtime_env() {
  project_paths
  [[ "$(uname -s)" == "Darwin" ]] || fail "macOS required"
  local python_bin
  python_bin="$WORKSPACE/runtime/python/bin/python3"
  [[ -x "$python_bin" ]] || fail "portable Python missing: $python_bin"
  [[ -f "$WORKSPACE/.PFC_READY" ]] || fail ".PFC_READY missing"
  [[ -f "$CURRENT_POINTER" ]] || fail "current pointer missing"

  if [[ -f "$PROJECT_ROOT/local-pfc.env" ]]; then
    # Generated by cmd_bind and contains only one shell-escaped absolute path.
    # shellcheck source=/dev/null
    source "$PROJECT_ROOT/local-pfc.env"
  fi

  export AITEST_WORKSPACE_ROOT="$WORKSPACE"
  export AITEST_RUNTIME_SPINE_DB="$DURABLE_ROOT/state/runtime-spine.db"
  export PFC_LOCAL_STATE_ROOT="$DURABLE_ROOT"
  export PFC_REPO_ROOT="${PFC_LOCAL_TARGET_ROOT:-$PROJECT_ROOT/targets/PFC}"
  export PYTHONPATH="$WORKSPACE/ai-test/runtime${PYTHONPATH:+:$PYTHONPATH}"
  export AITEST_RUNTIME_LOCK="$WORKSPACE/runtime-lock.json"
  export AITEST_RUNTIME_PYTHON="$WORKSPACE/runtime/python/python.exe"

  local path_lines
  path_lines="$("$python_bin" - "$WORKSPACE/runtime-lock.json" "$WORKSPACE" <<'PY'
import json
import sys
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(sys.argv[2])
for key in ("codegraph", "chromium"):
    rel = (lock.get("payloads", {}).get(key, {}) or {}).get("relative_target")
    if not rel:
        raise SystemExit(f"missing relative_target for {key}")
    print(str((root / rel).resolve()))
PY
)" || fail "runtime lock path resolution failed"
  AITEST_CODEGRAPH_BINARY="$(printf '%s\n' "$path_lines" | sed -n '1p')"
  AITEST_BROWSER_EXECUTABLE="$(printf '%s\n' "$path_lines" | sed -n '2p')"
  export AITEST_CODEGRAPH_BINARY AITEST_BROWSER_EXECUTABLE
  [[ -x "$AITEST_CODEGRAPH_BINARY" ]] || fail "CodeGraph binary missing"
  [[ -x "$AITEST_BROWSER_EXECUTABLE" ]] || fail "Chrome for Testing missing"

  export PATH="$WORKSPACE/runtime/shell:$WORKSPACE/runtime/opencode:$WORKSPACE/runtime/ripgrep:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
  RUNTIME_PYTHON="$python_bin"
}

cmd_bind() {
  project_paths
  [[ $# -eq 1 ]] || fail "usage: $0 bind /absolute/path/to/local/PFC"
  local target="$1" python_bin canonical
  [[ "$target" == /* ]] || fail "PFC target root must be an absolute path"
  [[ -d "$target" ]] || fail "PFC target root does not exist: $target"
  python_bin="$WORKSPACE/runtime/python/bin/python3"
  [[ -x "$python_bin" ]] || fail "install package first"

  canonical="$("$python_bin" - "$target" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
  printf 'export PFC_LOCAL_TARGET_ROOT=%q\n' "$canonical" >"$PROJECT_ROOT/local-pfc.env"

  "$python_bin" - "$WORKSPACE/PFC_PROJECT_PROFILE.json" "$canonical" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["target_root"] = sys.argv[2]
payload["target_binding"] = "BOUND"
payload["bound_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
tmp = path.with_suffix(".tmp")
tmp.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.replace(tmp, path)
PY

  printf 'LOCAL_PFC_BINDING=PASS\n'
  printf 'PFC_LOCAL_TARGET_ROOT=%s\n' "$canonical"
  printf 'CREDENTIALS_PERSISTED=NO\n'
}

cmd_start() {
  runtime_env
  local open_version
  open_version="$("$WORKSPACE/runtime/opencode/opencode" --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
  [[ "$open_version" == "$OPENCODE_VERSION" ]] || fail "OpenCode version mismatch: ${open_version:-UNAVAILABLE}"

  "$RUNTIME_PYTHON" -m aitest_runtime.product_entry interactive-truth --target status \
    >"$DURABLE_ROOT/state/local-mac-start-truth.json" || fail "canonical truth preflight failed"

  printf 'LOCAL_MAC_CANONICAL_RUNTIME=PASS\n'
  printf 'LOCAL_MAC_OPENCODE=%s\n' "$open_version"
  if [[ -d "$PFC_REPO_ROOT" ]]; then
    printf 'LOCAL_PFC_TARGET=%s\n' "$PFC_REPO_ROOT"
  else
    printf 'LOCAL_PFC_TARGET=UNBOUND_OR_MISSING\n'
  fi
  exec "$RUNTIME_PYTHON" "$WORKSPACE/pfc-field-validation/pfc_web_runtime.py" start
}

cmd_status() {
  runtime_env
  exec "$RUNTIME_PYTHON" "$WORKSPACE/pfc-field-validation/pfc_web_runtime.py" status
}

cmd_stop() {
  runtime_env
  exec "$RUNTIME_PYTHON" "$WORKSPACE/pfc-field-validation/pfc_web_runtime.py" stop
}

cmd_doctor() {
  runtime_env
  local ok=1
  "$RUNTIME_PYTHON" -c 'import playwright; print("PLAYWRIGHT=PASS")' || ok=0
  "$WORKSPACE/runtime/opencode/opencode" --version || ok=0
  "$WORKSPACE/runtime/ripgrep/rg" --version | head -n 1 || ok=0
  [[ -f "$AITEST_RUNTIME_SPINE_DB" ]] || ok=0
  [[ -x "$AITEST_BROWSER_EXECUTABLE" ]] || ok=0
  [[ -x "$AITEST_CODEGRAPH_BINARY" ]] || ok=0
  if [[ "$ok" == "1" ]]; then
    printf 'LOCAL_MAC_DOCTOR=PASS\n'
    return 0
  fi
  printf 'LOCAL_MAC_DOCTOR=FAIL\n'
  return 1
}

usage() {
  cat <<'EOF'
Usage:
  ./local-mac.sh build
  ./local-mac.sh install
  ./local-mac.sh bind /absolute/path/to/local/PFC
  ./local-mac.sh doctor
  ./local-mac.sh start
  ./local-mac.sh status
  ./local-mac.sh stop

Build is the only command that requires internet/dependency installation.
Install/start/status/stop/bind/doctor are offline target-host operations.
EOF
}

command_name="${1:-}"
shift || true
case "$command_name" in
  build) cmd_build "$@" ;;
  install) cmd_install "$@" ;;
  bind) cmd_bind "$@" ;;
  doctor) cmd_doctor "$@" ;;
  start) cmd_start "$@" ;;
  status) cmd_status "$@" ;;
  stop) cmd_stop "$@" ;;
  *) usage; exit 2 ;;
esac
