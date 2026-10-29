#!/usr/bin/env bash
set -euo pipefail

PACKAGE_ROOT=""
SOURCE_COMMIT=""
RUNNER_KIND=""
RUNNER_IDENTITY=""
OUTPUT_DIR=""

usage() {
  cat >&2 <<'EOF'
Usage: Q3-FIELD-HANDOFF.sh --package-root <path> --source-commit <40-hex-sha> --runner-kind <kind> --runner-identity <identity> --output-dir <path>

Prepares Q3 target-Linux observation + transported-package evidence for a trusted external verifier.
It never approves the target environment and never sets Field/BANK_FINAL.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --package-root) [[ $# -ge 2 ]] || { usage; exit 64; }; PACKAGE_ROOT="$2"; shift 2 ;;
    --source-commit) [[ $# -ge 2 ]] || { usage; exit 64; }; SOURCE_COMMIT="$2"; shift 2 ;;
    --runner-kind) [[ $# -ge 2 ]] || { usage; exit 64; }; RUNNER_KIND="$2"; shift 2 ;;
    --runner-identity) [[ $# -ge 2 ]] || { usage; exit 64; }; RUNNER_IDENTITY="$2"; shift 2 ;;
    --output-dir) [[ $# -ge 2 ]] || { usage; exit 64; }; OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Q3_FIELD_HANDOFF_UNKNOWN_ARGUMENT:$1" >&2; usage; exit 64 ;;
  esac
done

[[ -n "$PACKAGE_ROOT" ]] || { echo 'Q3_FIELD_HANDOFF_PACKAGE_ROOT_REQUIRED' >&2; exit 2; }
[[ "$SOURCE_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || { echo 'Q3_FIELD_HANDOFF_SOURCE_COMMIT_INVALID' >&2; exit 2; }
[[ -n "$RUNNER_KIND" ]] || { echo 'Q3_FIELD_HANDOFF_RUNNER_KIND_REQUIRED' >&2; exit 2; }
[[ -n "$RUNNER_IDENTITY" ]] || { echo 'Q3_FIELD_HANDOFF_RUNNER_IDENTITY_REQUIRED' >&2; exit 2; }
[[ -n "$OUTPUT_DIR" ]] || { echo 'Q3_FIELD_HANDOFF_OUTPUT_DIR_REQUIRED' >&2; exit 2; }
[[ -d "$PACKAGE_ROOT" ]] || { echo 'Q3_FIELD_HANDOFF_PACKAGE_ROOT_MISSING' >&2; exit 3; }

PACKAGE_ROOT="$(cd "$PACKAGE_ROOT" && pwd)"
SOURCE_COMMIT="$(printf '%s' "$SOURCE_COMMIT" | tr '[:upper:]' '[:lower:]')"
SOURCE_FILE="$PACKAGE_ROOT/SOURCE_COMMIT"
PROBE="$PACKAGE_ROOT/packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh"
HANDOFF="$PACKAGE_ROOT/packaging/rc7.2/Q3-FIELD-HANDOFF.sh"
AITEST="$PACKAGE_ROOT/packaging/rc7.2/AITEST.sh"
ATTESTATION_MODULE="$PACKAGE_ROOT/rc7_release/rc72_target_linux_attestation.py"
REALITY_MODULE="$PACKAGE_ROOT/rc7_release/rc72_target_linux_reality.py"

for required in "$SOURCE_FILE" "$PROBE" "$HANDOFF" "$AITEST" "$ATTESTATION_MODULE" "$REALITY_MODULE"; do
  [[ -f "$required" ]] || { echo "Q3_FIELD_HANDOFF_REQUIRED_FILE_MISSING:$required" >&2; exit 3; }
done
PACKAGE_SOURCE="$(tr -d '\r\n[:space:]' < "$SOURCE_FILE" | tr '[:upper:]' '[:lower:]')"
[[ "$PACKAGE_SOURCE" == "$SOURCE_COMMIT" ]] || { echo 'Q3_FIELD_HANDOFF_PACKAGE_SOURCE_MISMATCH' >&2; exit 4; }

bash -n "$PROBE"
bash -n "$HANDOFF"
bash -n "$AITEST"

PYTHON_ORIGIN=""
if [[ -n "${PFC_RC72_PACKAGE_PYTHON:-}" && -x "${PFC_RC72_PACKAGE_PYTHON}" ]]; then
  PYTHON_BIN="${PFC_RC72_PACKAGE_PYTHON}"
  PYTHON_ORIGIN="PACKAGE_LOCAL_OVERRIDE"
elif [[ -x "$PACKAGE_ROOT/workspace-template/runtime/python/python" ]]; then
  PYTHON_BIN="$PACKAGE_ROOT/workspace-template/runtime/python/python"
  PYTHON_ORIGIN="PACKAGE_LOCAL"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
  PYTHON_ORIGIN="TARGET_HOST_RUNTIME"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
  PYTHON_ORIGIN="TARGET_HOST_RUNTIME"
else
  echo 'Q3_FIELD_HANDOFF_PYTHON_REQUIRED' >&2
  exit 5
fi

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
OBSERVATION="$OUTPUT_DIR/q3-target-observation.json"
REQUEST="$OUTPUT_DIR/q3-target-attestation-request.json"
PACKAGE_EVIDENCE="$OUTPUT_DIR/q3-target-package-evidence.json"
MANIFEST="$OUTPUT_DIR/q3-target-handoff-manifest.json"

chmod +x "$PROBE"
PFC_RC72_PACKAGE_PYTHON="$PYTHON_BIN" "$PROBE" \
  --source-commit "$SOURCE_COMMIT" \
  --runner-kind "$RUNNER_KIND" \
  --runner-identity "$RUNNER_IDENTITY" \
  --output "$OBSERVATION"

export PACKAGE_ROOT SOURCE_COMMIT PACKAGE_SOURCE RUNNER_KIND RUNNER_IDENTITY PYTHON_BIN PYTHON_ORIGIN
"$PYTHON_BIN" - "$PACKAGE_EVIDENCE" <<'PY'
from __future__ import print_function
import hashlib
import json
import os
import sys

output = sys.argv[1]
root = os.environ["PACKAGE_ROOT"]
critical_paths = (
    "SOURCE_COMMIT",
    "packaging/rc7.2/Q3-FIELD-HANDOFF.sh",
    "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
    "packaging/rc7.2/AITEST.sh",
    "rc7_release/rc72_target_linux_attestation.py",
    "rc7_release/rc72_target_linux_reality.py",
)

def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

payload = {
    "schema": "pfc.aitest.rc7.2.q3-target-package-evidence.v1",
    "source_commit": os.environ["SOURCE_COMMIT"],
    "package_source_commit": os.environ["PACKAGE_SOURCE"],
    "package_source_match": os.environ["SOURCE_COMMIT"] == os.environ["PACKAGE_SOURCE"],
    "package_root": root,
    "probe": "packaging/rc7.2/Q3-TARGET-LINUX-PROBE.sh",
    "attestation_module": "rc7_release/rc72_target_linux_attestation.py",
    "reality_module": "rc7_release/rc72_target_linux_reality.py",
    "shell_entrypoint": "packaging/rc7.2/AITEST.sh",
    "shell_syntax_verified": True,
    "python_runtime": os.environ["PYTHON_BIN"],
    "python_origin": os.environ["PYTHON_ORIGIN"],
    "runner_kind": os.environ["RUNNER_KIND"],
    "runner_identity": os.environ["RUNNER_IDENTITY"],
    "critical_files": {rel: digest(os.path.join(root, rel)) for rel in critical_paths},
    "network_install_performed": False,
    "target_linux_verified": False,
    "field_verified": False,
    "bank_final": False,
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
PY

(
  cd "$PACKAGE_ROOT"
  "$PYTHON_BIN" -m rc7_release.rc72_target_linux_attestation request \
    --observation "$OBSERVATION" \
    --package-evidence "$PACKAGE_EVIDENCE" \
    --output "$REQUEST"
)

"$PYTHON_BIN" - "$OBSERVATION" "$REQUEST" "$PACKAGE_EVIDENCE" "$MANIFEST" <<'PY'
from __future__ import print_function
import hashlib
import json
import os
import sys

observation_path, request_path, package_evidence_path, manifest_path = sys.argv[1:]

def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def canonical_digest(payload):
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()

observation = load(observation_path)
request = load(request_path)
package_evidence = load(package_evidence_path)
package_digest = canonical_digest(package_evidence)
assert observation["source_commit"] == os.environ["SOURCE_COMMIT"]
assert request["source_commit"] == os.environ["SOURCE_COMMIT"]
assert package_evidence["package_source_match"] is True
assert request["state"] == "AWAITING_EXTERNAL_ATTESTATION"
assert request["package_evidence_bound"] is True
assert request["package_evidence_digest"] == package_digest

payload = {
    "schema": "pfc.aitest.rc7.2.q3-target-field-handoff.v1",
    "source_commit": os.environ["SOURCE_COMMIT"],
    "runner_kind": os.environ["RUNNER_KIND"],
    "runner_identity": os.environ["RUNNER_IDENTITY"],
    "qualification_state": "AWAITING_EXTERNAL_ATTESTATION",
    "next_action": "OBTAIN_TRUSTED_EXTERNAL_ATTESTATION",
    "trusted_verifier_required": True,
    "observation_digest": request["observation_digest"],
    "package_evidence_digest": package_digest,
    "files": {
        "observation": {"path": os.path.basename(observation_path), "sha256": file_digest(observation_path)},
        "attestation_request": {"path": os.path.basename(request_path), "sha256": file_digest(request_path)},
        "package_evidence": {"path": os.path.basename(package_evidence_path), "sha256": file_digest(package_evidence_path)},
    },
    "target_linux_verified": False,
    "field_verified": False,
    "bank_final": False,
}
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY

echo "Q3_FIELD_HANDOFF_READY output_dir=$OUTPUT_DIR state=AWAITING_EXTERNAL_ATTESTATION"
