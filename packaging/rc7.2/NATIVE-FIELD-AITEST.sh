#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
PY="$ROOT/workspace-template/runtime/python/bin/python3"
NODE="$ROOT/workspace-template/runtime/node/bin/node"
BSK="$ROOT/workspace-template/runtime/browser/browserskill/bsk"
[[ -x "$PY" ]] || { echo "NATIVE_PACKAGE_PYTHON_MISSING:$PY" >&2; exit 2; }
[[ -x "$NODE" ]] || { echo "NATIVE_PACKAGE_NODE_MISSING:$NODE" >&2; exit 2; }
[[ -x "$BSK" ]] || { echo "NATIVE_PACKAGE_BROWSERSKILL_MISSING:$BSK" >&2; exit 2; }

case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:aarch64|Darwin:x86_64|Darwin:arm64) ;;
  *) echo "NATIVE_PACKAGE_PLATFORM_UNSUPPORTED:$(uname -s):$(uname -m)" >&2; exit 2 ;;
esac
"$PY" - "$ROOT/NATIVE_FIELD_PACKAGE.json" "$(uname -s)" "$(uname -m)" <<'PY'
import json,sys
m=json.load(open(sys.argv[1],encoding="utf-8"))
os_name="linux" if sys.argv[2]=="Linux" else "darwin"
arch={"x86_64":"x86_64","aarch64":"arm64","arm64":"arm64"}.get(sys.argv[3])
if m.get("platform")!=os_name or m.get("architecture")!=arch:
    raise SystemExit("NATIVE_PACKAGE_HOST_IDENTITY_MISMATCH")
PY
if [[ "$(uname -s)" == "Linux" ]]; then
  GLIBC="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"
  "$PY" - "$GLIBC" "$(uname -r)" <<'PY'
import sys
def v(s): return tuple(int(x) for x in s.split(".")[:2])
if v(sys.argv[1]) < (2,34): raise SystemExit("LINUX_GLIBC_2_34_REQUIRED")
if v(sys.argv[2]) < (4,18): raise SystemExit("LINUX_KERNEL_4_18_REQUIRED")
PY
  CHROMIUM_CHECK="$(find "$ROOT/workspace-template/runtime/browser/pw-browsers" -type f -name chrome -print -quit)"
  [[ -n "$CHROMIUM_CHECK" ]] || { echo "NATIVE_CHROMIUM_MISSING" >&2; exit 2; }
  if ldd "$CHROMIUM_CHECK" 2>&1 | grep -q 'not found'; then
    echo "NATIVE_CHROMIUM_HOST_SHARED_LIBRARY_MISSING" >&2
    ldd "$CHROMIUM_CHECK" >&2
    exit 2
  fi
else
  MACOS_VERSION="$(sw_vers -productVersion)"
  "$PY" - "$MACOS_VERSION" <<'PY'
import sys
v=tuple(int(x) for x in sys.argv[1].split(".")[:2])
if v < (14,0): raise SystemExit("MACOS_14_REQUIRED")
PY
fi

export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PFC_AITEST_HOME="$ROOT"
export PFC_AITEST_STATE_DIR="${PFC_AITEST_STATE_DIR:-$ROOT/runtime-state}"
export PFC_RC7_DSH_PROFILE="${PFC_RC72_DSH_PROFILE:-rc7.2-bank-native}"
export PFC_RC72_TEAM_CAPACITY32=1
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/workspace-template/runtime/browser/pw-browsers"
export PFC_PYTHON="$PY"
export PFC_NODE_BIN="$NODE"
export PFC_BROWSERSKILL_BIN="$BSK"
if [[ "$(uname -s)" == "Linux" ]]; then
  CHROMIUM="$(find "$ROOT/workspace-template/runtime/browser/pw-browsers" -type f -name chrome -print -quit)"
else
  CHROMIUM="$(find "$ROOT/workspace-template/runtime/browser/pw-browsers" -type f -name Chromium -print -quit)"
fi
[[ -n "$CHROMIUM" ]] || { echo "NATIVE_CHROMIUM_MISSING" >&2; exit 2; }
export PFC_CHROMIUM_BIN="$CHROMIUM"
CODEGRAPH="$(find "$ROOT/workspace-template/runtime/code-intelligence/codegraph" -maxdepth 1 -type f -name 'codegraph-server-*' -print -quit)"
[[ -n "$CODEGRAPH" ]] || { echo "NATIVE_CODEGRAPH_MISSING" >&2; exit 2; }
export PFC_CODEGRAPH_BIN="$CODEGRAPH"
export PFC_RIPGREP_BIN="$ROOT/workspace-template/runtime/ripgrep/rg"
export PFC_JAVA_BIN="$ROOT/workspace-template/runtime/java/bin/java"
export PFC_MAVEN_BIN="$ROOT/workspace-template/runtime/maven/bin/mvn"
export PFC_ALLURE_BIN="$ROOT/workspace-template/runtime/allure/bin/allure"
export PFC_K6_BIN="$ROOT/workspace-template/runtime/k6/k6"
export PFC_ZAP_BIN="$(find "$ROOT/workspace-template/runtime/zap" -type f -name zap.sh -print -quit)"
export PFC_MAVEN_REPO="$ROOT/workspace-template/runtime/maven-repository"
export PFC_MAVEN_SETTINGS="$ROOT/packaging/rc7/maven-offline-settings.xml"
export MAVEN_ARGS="-o -s \"$PFC_MAVEN_SETTINGS\" -Dmaven.legacyLocalRepo=true -Dmaven.repo.local=\"$PFC_MAVEN_REPO\""
export JAVA_HOME="$ROOT/workspace-template/runtime/java"
export MAVEN_HOME="$ROOT/workspace-template/runtime/maven"
export PATH="$ROOT/workspace-template/runtime/node/bin:$ROOT/workspace-template/runtime/browser/browserskill:$ROOT/workspace-template/runtime/ripgrep:$ROOT/workspace-template/runtime/java/bin:$ROOT/workspace-template/runtime/maven/bin:$ROOT/workspace-template/runtime/allure/bin:$ROOT/workspace-template/runtime/k6:$PATH"

if [[ "$(uname -s)" == "Linux" ]]; then
  export LD_LIBRARY_PATH="$ROOT/workspace-template/runtime/syslib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

SOURCE="$(tr -d '\r\n' < "$ROOT/SOURCE_COMMIT")"
cd "$ROOT"
"$PY" -B -m rc7_release.rc72_native_field_portable verify --package-root "$ROOT" --expected-source-commit "$SOURCE"

if [[ "${1:-}" == "--verify-only" || "${PFC_RC72_NATIVE_PROBE_ONLY:-0}" == "1" ]]; then
  echo "RC72_NATIVE_FIELD_PROBE source=$SOURCE platform=$(uname -s) arch=$(uname -m) node=$("$NODE" --version) bsk=$("$BSK" --version) field_verified=false bank_final=false"
  exit 0
fi

if [[ "$PFC_RC7_DSH_PROFILE" == "${PFC_RC7_DSH_BASE_PROFILE:-web}" ]]; then
  echo "NATIVE_PROTECTED_DSH_PROFILE_REFUSED" >&2
  exit 4
fi

HOST_BIN="${PFC_RC72_DSH_HOST_BIN:-}"
if [[ -z "$HOST_BIN" || ! -f "$HOST_BIN" || ! -x "$HOST_BIN" ]]; then
  echo "[RC7.2] Set PFC_RC72_DSH_HOST_BIN to the absolute path of the bank-approved native DSH CLI." >&2
  echo "[RC7.2] This package does not redistribute the DSH main executable." >&2
  exit 4
fi
"$PY" - "$HOST_BIN" "$(uname -s)" "$(uname -m)" <<'PY'
import os, pathlib, subprocess, sys
path = pathlib.Path(sys.argv[1]).expanduser()
if not path.is_absolute():
    raise SystemExit("DSH_HOST_ABSOLUTE_PATH_REQUIRED")
path = path.resolve()
system, machine = sys.argv[2], sys.argv[3]
if not path.is_file() or not os.access(str(path), os.X_OK):
    raise SystemExit("DSH_HOST_NOT_EXECUTABLE")
data = path.read_bytes()[:4096]
if data.startswith(b"#!"):
    print("DSH_HOST_SHEBANG_CANDIDATE")
elif system == "Linux":
    if data[:4] != b"\x7fELF" or len(data) < 20 or data[4] != 2:
        raise SystemExit("DSH_HOST_NOT_ELF64")
    expected = 62 if machine == "x86_64" else 183
    if int.from_bytes(data[18:20], "little") != expected:
        raise SystemExit("DSH_HOST_ELF_ARCH_MISMATCH")
    print("DSH_HOST_ELF64_ARCH_PASS")
elif system == "Darwin":
    expected_arch = machine
    if data[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
        endian = "little" if data[:4] == b"\xcf\xfa\xed\xfe" else "big"
        cpu = int.from_bytes(data[4:8], endian)
        expected = 0x01000007 if machine == "x86_64" else 0x0100000c
        if cpu != expected:
            raise SystemExit("DSH_HOST_MACHO_ARCH_MISMATCH")
    elif data[:4] in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
        result = subprocess.run(["lipo", "-archs", str(path)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode or expected_arch not in result.stdout.split():
            raise SystemExit("DSH_HOST_FAT_MACHO_ARCH_MISMATCH")
    else:
        raise SystemExit("DSH_HOST_NOT_MACHO")
    print("DSH_HOST_MACHO_ARCH_PASS")
else:
    raise SystemExit("DSH_HOST_PLATFORM_UNSUPPORTED")
PY
if [[ -n "${PFC_RC72_DSH_HOST_SHA256:-}" ]]; then
  if command -v sha256sum >/dev/null 2>&1; then ACTUAL="$(sha256sum "$HOST_BIN" | awk '{print $1}')"; else ACTUAL="$(shasum -a 256 "$HOST_BIN" | awk '{print $1}')"; fi
  EXPECTED="$(printf '%s' "$PFC_RC72_DSH_HOST_SHA256" | tr '[:upper:]' '[:lower:]')"
  [[ "$ACTUAL" == "$EXPECTED" ]] || { echo "DSH_HOST_SHA256_MISMATCH" >&2; exit 4; }
fi

echo "[RC7.2] Package verified. Starting external bank-approved DSH with profile $PFC_RC7_DSH_PROFILE."
exec "$HOST_BIN" --profile "$PFC_RC7_DSH_PROFILE" "$@"
