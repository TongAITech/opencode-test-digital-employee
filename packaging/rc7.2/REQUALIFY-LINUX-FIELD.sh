#!/usr/bin/env bash
# Requalify the already-built exact-source native Linux tarball.
# Never rebuild this 491MB artifact, change its SHA, or claim a bank field PASS.
set -euo pipefail

SOURCE_COMMIT="90865252ccf8fd55ab126195413741311ec84567"
ARTIFACT_RUN="42991119342"
ARTIFACT_NAME="RC72-LINUX-FIELD-UBUNTU22-X64-$SOURCE_COMMIT"
EXPECTED_TARBALL_SHA256="2dc9029f1f36ba78b08b9a1223256d3219a1d2d5d73d1748b8567a4d20e7818a"
ROOT_NAME="PFC-AITest-DSH-RC7.2-UBUNTU22-X64-FIELD"
DEST="$RUNNER_TEMP/rc72-linux-independent-requalification"
mkdir -p "$DEST/download" "$DEST/clean" "$DEST/evidence"
command -v gh >/dev/null || { echo "GITHUB_CLI_REQUIRED" >&2; exit 3; }

gh run download "$ARTIFACT_RUN" --repo TongAITech/opencode-test-digital-employee \
  --name "$ARTIFACT_NAME" --dir "$DEST/download"
ARCHIVE="$(find "$DEST/download" -type f -name "RC72-LINUX-FIELD-UBUNTU22-X64-*.tar.gz" -print -quit)"
[[ -n "$ARCHIVE" ]] || { echo "LINUX_SOURCE_ARTIFACT_TARBALL_MISSING" >&2; exit 3; }
[[ -f "$ARCHIVE.sha256" ]] || { echo "LINUX_SOURCE_ARTIFACT_CHECKSUM_MISSING" >&2; exit 3; }
ACTUAL_TARBALL_SHA256="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
[[ "$ACTUAL_TARBALL_SHA256" == "$EXPECTED_TARBALL_SHA256" ]] || {
  echo "LINUX_SOURCE_ARTIFACT_INDEPENDENT_SHA256_MISMATCH" >&2; exit 4;
}
(cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$ARCHIVE").sha256")
tar -xzf "$ARCHIVE" -C "$DEST/clean"
PKG="$DEST/clean/$ROOT_NAME"
[[ -d "$PKG" ]] || { echo "LINUX_CLEAN_EXTRACT_MISSING" >&2; exit 4; }
PY="$PKG/workspace-template/runtime/python/bin/python3"
NODE="$PKG/workspace-template/runtime/node/bin/node"
BSK="$PKG/workspace-template/runtime/browser/browserskill/bsk"
[[ -x "$PY" && -x "$NODE" && -x "$BSK" ]] || {
  echo "LINUX_CLEAN_PACKAGE_NATIVE_RUNTIME_MISSING" >&2; exit 4;
}

cd "$PKG"
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
"$PY" -B -m rc7_release.rc72_linux_field_portable verify \
  --package-root "$PKG" --expected-source-commit "$SOURCE_COMMIT" \
  | tee "$DEST/evidence/clean-identity.json"
"$PY" -B -c 'import sys,ssl,sqlite3,pytest,requests,openpyxl,docx,pptx,pypdf,PIL,rc7_runtime,rc7_release;print("LINUX_PORTABLE_PYTHON_MODULES_PASS",sys.version)'
"$NODE" --version | grep -x 'v24.9.0'
"$BSK" --version | grep -F '0.4.1'
PFC_RC72_LINUX_PROBE_ONLY=1 bash packaging/rc7.2/LINUX-FIELD-AITEST.sh \
  | tee "$DEST/evidence/isolated-launch-plan.txt"
(
  cd "$PKG/workspace-template/runtime/node-execution"
  PLAYWRIGHT_BROWSERS_PATH="$PKG/workspace-template/runtime/browser/pw-browsers" \
    "$NODE" -e 'const {chromium}=require("playwright");(async()=>{const b=await chromium.launch({headless:true,args:["--no-sandbox"]});const p=await b.newPage();await p.goto("data:text/html,<title>RC72 Linux Offline</title>");if(await p.title()!=="RC72 Linux Offline")throw Error("OFFLINE_CHROMIUM_SMOKE_FAILED");await b.close();console.log("LINUX_CHROMIUM_OFFLINE_PASS")})().catch(e=>{console.error(e);process.exit(1)})' \
    | tee "$DEST/evidence/offline-chromium.txt"
)
"$PY" -B -m rc7_release.rc72_target_linux_reality probe \
  --source-commit "$SOURCE_COMMIT" \
  --runner-kind GITHUB_HOSTED_GENERIC \
  --runner-identity github-hosted-ubuntu22-x86_64 \
  --output "$DEST/evidence/q3-generic-hold.json" --require-hold
"$PY" -B - <<'PY'
import json
from pathlib import Path
m=json.loads(Path("LINUX_FIELD_PACKAGE.json").read_text())
assert m["bank_final"] is False and m["field_verified"] is False
assert m["dsh_main_payload"]["bundled"] is False
assert m["restricted_graph_component"]["gitnexus_bundled"] is False
assert not Path("workspace-template/runtime/node-execution/node_modules/gitnexus").exists()
print("LINUX_LICENSE_AND_DSH_HOLD_BOUNDARIES_PASS")
PY

export DEST SOURCE_COMMIT ARTIFACT_RUN ACTUAL_TARBALL_SHA256
"$PY" -B - <<'PY'
import json, os, pathlib
dest=pathlib.Path(os.environ["DEST"])
report={
    "schema":"RC72_LINUX_INDEPENDENT_REQUALIFICATION_V1",
    "status":"PASS",
    "package_source_commit":os.environ["SOURCE_COMMIT"],
    "original_artifact_run_id":int(os.environ["ARTIFACT_RUN"]),
    "source_archive_sha256":os.environ["ACTUAL_TARBALL_SHA256"],
    "qualification_runner":"GITHUB_HOSTED_UBUNTU_22_04_X86_64",
    "transport_identity":"PASS","full_sha256_coverage":"PASS",
    "native_python_imports":"PASS","node_24_9":"PASS",
    "browserskill_0_4_1":"PASS","offline_playwright_chromium":"PASS",
    "gitnexus_bundled":False,"dsh_main_bundled":False,
    "q3_target_linux_verified":False,"field_verified":False,"bank_final":False,
}
(dest/"evidence/independent-qualification.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
print(json.dumps(report,sort_keys=True))
PY
