"""Turnkey runtime qualification certificate for RC7 transport packages.

A certificate is issued only after the already-materialized transport ZIP has
been clean-extracted and its package-local runtime has passed the full runtime
smoke.  The certificate is then written into the original package tree, the
package checksums are regenerated, and the transport ZIP/sidecar are rebuilt.

The certificate deliberately binds the *pre-certificate* transport SHA256: that
is the exact ZIP whose extracted runtime was executed.  The final ZIP SHA256
sidecar protects the certificate and the rest of the post-certificate package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .package import sha256_file, write_checksums
from .runtime_delivery_contract import verify_runtime_delivery


SCHEMA_VERSION = "pfc.aitest.rc7.turnkey-runtime-qualification.v1"
CERTIFICATE_FILE = "TURNKEY_RUNTIME_QUALIFICATION.json"
INVENTORY_FILE = "RUNTIME_PAYLOADS.json"
LOCK_FILE = "runtime-lock.json"
EVIDENCE_SCOPE = "CLEAN_EXTRACT_PACKAGE_LOCAL_RUNTIME_SMOKE"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class TurnkeyRuntimeCertificateError(RuntimeError):
    pass


def _load_json(path: Path, error: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise TurnkeyRuntimeCertificateError("%s:%s" % (error, path))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TurnkeyRuntimeCertificateError("%s:%s" % (error, exc)) from exc
    if not isinstance(value, Mapping):
        raise TurnkeyRuntimeCertificateError(error)
    return value


def _source_commit(root: Path) -> str:
    path = root / "SOURCE_COMMIT"
    if not path.is_file():
        raise TurnkeyRuntimeCertificateError("SOURCE_COMMIT_REQUIRED")
    value = path.read_text(encoding="utf-8").strip().lower()
    if not _SHA_RE.fullmatch(value):
        raise TurnkeyRuntimeCertificateError("SOURCE_COMMIT_INVALID")
    return value


def _same_file_digest(left: Path, right: Path, label: str) -> str:
    if not left.is_file() or not right.is_file():
        raise TurnkeyRuntimeCertificateError("%s_REQUIRED" % label)
    left_digest = sha256_file(left)
    right_digest = sha256_file(right)
    if left_digest != right_digest:
        raise TurnkeyRuntimeCertificateError("%s_CLEAN_EXTRACT_MISMATCH" % label)
    return left_digest


def _canonical_smoke_summary(smoke: Mapping[str, Any]) -> Dict[str, Any]:
    if smoke.get("status") != "PASS":
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_NOT_PASS")
    if smoke.get("delivery_runtime_complete") is not True:
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_DELIVERY_NOT_COMPLETE")
    try:
        required = int(smoke.get("required_payload_count") or 0)
        smoke_count = int(smoke.get("smoke_count") or 0)
    except Exception as exc:
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_COUNTS_INVALID") from exc
    rows = smoke.get("smokes")
    if not isinstance(rows, list) or required <= 0 or smoke_count <= 0 or len(rows) != smoke_count:
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_EVIDENCE_INVALID")
    capabilities = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") != "PASS":
            raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_CAPABILITY_NOT_PASS")
        capability = str(row.get("capability") or "").strip()
        if not capability or capability in capabilities:
            raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_CAPABILITY_INVALID")
        capabilities.append(capability)
    if smoke_count != required:
        raise TurnkeyRuntimeCertificateError(
            "CLEAN_RUNTIME_SMOKE_COUNT_MISMATCH:required=%s:smokes=%s" % (required, smoke_count)
        )
    normalized = {
        "delivery_runtime_complete": True,
        "required_payload_count": required,
        "smoke_count": smoke_count,
        "capabilities": sorted(capabilities),
    }
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    normalized["summary_sha256"] = hashlib.sha256(canonical).hexdigest()
    return normalized


def _run_clean_smoke(clean_root: Path) -> Mapping[str, Any]:
    package_python = clean_root / "workspace-template/runtime/python/python.exe"
    if not package_python.is_file():
        raise TurnkeyRuntimeCertificateError("CLEAN_PACKAGE_LOCAL_PYTHON_REQUIRED")
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    proc = subprocess.run(
        [str(package_python), "-m", "rc7_release.runtime_clean_smoke", "--package-root", str(clean_root)],
        cwd=str(clean_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
        check=False,
    )
    output = proc.stdout or ""
    if proc.returncode != 0:
        raise TurnkeyRuntimeCertificateError(
            "CLEAN_RUNTIME_SMOKE_PROCESS_FAILED:rc=%s:%s" % (proc.returncode, output[-4000:])
        )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_OUTPUT_EMPTY")
    try:
        payload = json.loads(lines[-1])
    except Exception as exc:
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_OUTPUT_INVALID") from exc
    if not isinstance(payload, Mapping):
        raise TurnkeyRuntimeCertificateError("CLEAN_RUNTIME_SMOKE_OUTPUT_INVALID")
    return payload


def _check_zip_sidecar(zip_path: Path) -> str:
    if not zip_path.is_file():
        raise TurnkeyRuntimeCertificateError("TRANSPORT_ZIP_REQUIRED:%s" % zip_path)
    actual = sha256_file(zip_path)
    sidecar = Path(str(zip_path) + ".sha256")
    if not sidecar.is_file():
        raise TurnkeyRuntimeCertificateError("TRANSPORT_ZIP_SIDECAR_REQUIRED")
    first = sidecar.read_text(encoding="utf-8").strip().split()
    if not first or first[0].lower() != actual:
        raise TurnkeyRuntimeCertificateError("TRANSPORT_ZIP_SIDECAR_MISMATCH")
    return actual


def _repack_transport(package_root: Path, zip_path: Path) -> str:
    write_checksums(package_root)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(str(zip_path), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                arc = Path(package_root.name) / path.relative_to(package_root)
                archive.write(str(path), arc.as_posix())
    digest = sha256_file(zip_path)
    Path(str(zip_path) + ".sha256").write_text(
        "%s  %s\n" % (digest, zip_path.name), encoding="utf-8", newline="\n"
    )
    return digest


def issue_turnkey_certificate(
    package_root: Path | str,
    clean_package_root: Path | str,
    transport_zip: Path | str,
) -> Dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    clean = Path(clean_package_root).expanduser().resolve()
    zip_path = Path(transport_zip).expanduser().resolve()
    if not root.is_dir() or not clean.is_dir():
        raise TurnkeyRuntimeCertificateError("PACKAGE_ROOTS_REQUIRED")

    source_commit = _source_commit(root)
    if _source_commit(clean) != source_commit:
        raise TurnkeyRuntimeCertificateError("SOURCE_COMMIT_CLEAN_EXTRACT_MISMATCH")
    runtime_lock_sha256 = _same_file_digest(root / LOCK_FILE, clean / LOCK_FILE, "RUNTIME_LOCK")
    inventory_sha256 = _same_file_digest(root / INVENTORY_FILE, clean / INVENTORY_FILE, "RUNTIME_INVENTORY")
    pre_certificate_zip_sha256 = _check_zip_sidecar(zip_path)

    built_delivery = verify_runtime_delivery(root)
    clean_delivery = verify_runtime_delivery(clean)
    if built_delivery.get("status") != "PASS" or clean_delivery.get("status") != "PASS":
        raise TurnkeyRuntimeCertificateError("RUNTIME_DELIVERY_CONTRACT_NOT_PASS")
    if int(built_delivery.get("required_payload_count") or 0) != int(clean_delivery.get("required_payload_count") or 0):
        raise TurnkeyRuntimeCertificateError("RUNTIME_DELIVERY_REQUIRED_COUNT_MISMATCH")

    smoke_summary = _canonical_smoke_summary(_run_clean_smoke(clean))
    if smoke_summary["required_payload_count"] != int(clean_delivery.get("required_payload_count") or 0):
        raise TurnkeyRuntimeCertificateError("RUNTIME_SMOKE_REQUIRED_COUNT_MISMATCH")

    certificate = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "qualification_kind": "TURNKEY_RUNTIME",
        "evidence_scope": EVIDENCE_SCOPE,
        "source_commit": source_commit,
        "runtime_lock_sha256": runtime_lock_sha256,
        "runtime_payload_inventory_sha256": inventory_sha256,
        "pre_certificate_transport_zip_sha256": pre_certificate_zip_sha256,
        "delivery_runtime_contract_schema": str(clean_delivery.get("schema_version") or ""),
        "delivery_runtime_complete": True,
        "required_payload_count": smoke_summary["required_payload_count"],
        "smoke_count": smoke_summary["smoke_count"],
        "smoke_capabilities": smoke_summary["capabilities"],
        "smoke_summary_sha256": smoke_summary["summary_sha256"],
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
    }
    cert_path = root / CERTIFICATE_FILE
    cert_path.write_text(
        json.dumps(certificate, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    manifest_path = root / "PACKAGE_MANIFEST.json"
    manifest = dict(_load_json(manifest_path, "PACKAGE_MANIFEST_REQUIRED"))
    manifest["turnkey_runtime_qualification"] = {
        "path": CERTIFICATE_FILE,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source_commit": source_commit,
        "runtime_lock_sha256": runtime_lock_sha256,
        "runtime_payload_inventory_sha256": inventory_sha256,
        "pre_certificate_transport_zip_sha256": pre_certificate_zip_sha256,
        "required_payload_count": smoke_summary["required_payload_count"],
        "smoke_count": smoke_summary["smoke_count"],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    final_zip_sha256 = _repack_transport(root, zip_path)
    verified = verify_turnkey_certificate(root, rerun_smoke=False)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "certificate": str(cert_path),
        "source_commit": source_commit,
        "pre_certificate_transport_zip_sha256": pre_certificate_zip_sha256,
        "final_transport_zip_sha256": final_zip_sha256,
        "required_payload_count": verified["required_payload_count"],
        "smoke_count": verified["smoke_count"],
    }


def verify_turnkey_certificate(package_root: Path | str, *, rerun_smoke: bool = False) -> Dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    if not root.is_dir():
        raise TurnkeyRuntimeCertificateError("PACKAGE_ROOT_NOT_FOUND:%s" % root)
    cert = _load_json(root / CERTIFICATE_FILE, "TURNKEY_RUNTIME_CERTIFICATE_REQUIRED")
    if cert.get("schema_version") != SCHEMA_VERSION or cert.get("status") != "PASS":
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_CERTIFICATE_INVALID")
    if cert.get("evidence_scope") != EVIDENCE_SCOPE:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_EVIDENCE_SCOPE_INVALID")
    source_commit = _source_commit(root)
    if cert.get("source_commit") != source_commit:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_SOURCE_COMMIT_MISMATCH")

    lock_digest = sha256_file(root / LOCK_FILE)
    inventory_digest = sha256_file(root / INVENTORY_FILE)
    if cert.get("runtime_lock_sha256") != lock_digest:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_LOCK_HASH_MISMATCH")
    if cert.get("runtime_payload_inventory_sha256") != inventory_digest:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_INVENTORY_HASH_MISMATCH")
    pre_zip = str(cert.get("pre_certificate_transport_zip_sha256") or "")
    if not _SHA256_RE.fullmatch(pre_zip):
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_PRE_CERTIFICATE_ZIP_HASH_INVALID")

    delivery = verify_runtime_delivery(root)
    required = int(delivery.get("required_payload_count") or 0)
    if cert.get("delivery_runtime_complete") is not True or int(cert.get("required_payload_count") or 0) != required:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_DELIVERY_BINDING_MISMATCH")

    capabilities = cert.get("smoke_capabilities")
    smoke_count = int(cert.get("smoke_count") or 0)
    if not isinstance(capabilities, list) or smoke_count != len(capabilities) or smoke_count != required:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_SMOKE_BINDING_INVALID")
    normalized = {
        "delivery_runtime_complete": True,
        "required_payload_count": required,
        "smoke_count": smoke_count,
        "capabilities": sorted(str(value) for value in capabilities),
    }
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if cert.get("smoke_summary_sha256") != hashlib.sha256(canonical).hexdigest():
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_SMOKE_SUMMARY_HASH_MISMATCH")

    manifest = _load_json(root / "PACKAGE_MANIFEST.json", "PACKAGE_MANIFEST_REQUIRED")
    pointer = manifest.get("turnkey_runtime_qualification")
    if not isinstance(pointer, Mapping):
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_MANIFEST_POINTER_REQUIRED")
    for key in (
        "schema_version",
        "status",
        "source_commit",
        "runtime_lock_sha256",
        "runtime_payload_inventory_sha256",
        "pre_certificate_transport_zip_sha256",
        "required_payload_count",
        "smoke_count",
    ):
        if pointer.get(key) != cert.get(key):
            raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_MANIFEST_POINTER_MISMATCH:%s" % key)
    if pointer.get("path") != CERTIFICATE_FILE:
        raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_MANIFEST_PATH_INVALID")

    rerun = None
    if rerun_smoke:
        rerun = _canonical_smoke_summary(_run_clean_smoke(root))
        if rerun["required_payload_count"] != required:
            raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_RERUN_REQUIRED_COUNT_MISMATCH")
        if rerun["capabilities"] != normalized["capabilities"]:
            raise TurnkeyRuntimeCertificateError("TURNKEY_RUNTIME_RERUN_CAPABILITY_SET_MISMATCH")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source_commit": source_commit,
        "certificate_path": str((root / CERTIFICATE_FILE).resolve()),
        "required_payload_count": required,
        "smoke_count": smoke_count,
        "smoke_capabilities": normalized["capabilities"],
        "rerun_smoke": bool(rerun_smoke),
        "pre_certificate_transport_zip_sha256": pre_zip,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.runtime_turnkey_certificate")
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--package-root", required=True)
    issue.add_argument("--clean-package-root", required=True)
    issue.add_argument("--transport-zip", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--package-root", required=True)
    verify.add_argument("--rerun-smoke", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "issue":
            result = issue_turnkey_certificate(args.package_root, args.clean_package_root, args.transport_zip)
        else:
            result = verify_turnkey_certificate(args.package_root, rerun_smoke=bool(args.rerun_smoke))
    except Exception as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
