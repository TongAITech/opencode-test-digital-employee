"""C12 one-shot Windows ZIP from an independently approved local DSH executable.

This exists because the GitHub-hosted transport workflow supports a HTTPS
secret but not bank-custodied local executable bytes. It is a controlled
Windows *build-host* entrypoint, not a way to mark Q3-Q9 or BANK_FINAL passed.
No fake PE, source URL, self-approval, or accidental PATH DSH is accepted.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile

from . import rc72_dsh_main_payload as dsh_main

_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


class LocalC12Error(RuntimeError):
    pass


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def preflight(*, source_commit, dsh_file, dsh_sha256, approval_record):
    """Read-only source check BEFORE any package download or GB-scale ZIP."""
    if not isinstance(source_commit, str) or not _SHA.fullmatch(source_commit):
        raise LocalC12Error("C12_EXACT_40_HEX_SOURCE_REQUIRED")
    if not isinstance(dsh_sha256, str) or not _HASH.fullmatch(dsh_sha256):
        raise LocalC12Error("C12_INDEPENDENT_64_HEX_MAIN_HASH_REQUIRED")
    exe = Path(dsh_file).expanduser().absolute()
    approval = Path(approval_record).expanduser().absolute()
    if exe.is_symlink() or not exe.is_file():
        raise LocalC12Error("C12_REAL_LOCAL_MAIN_FILE_REQUIRED")
    if approval.is_symlink() or not approval.is_file():
        raise LocalC12Error("C12_EXTERNAL_APPROVAL_DOCUMENT_REQUIRED")
    if approval.stat().st_size < 1 or approval.stat().st_size > 10 * 1024 * 1024:
        raise LocalC12Error("C12_EXTERNAL_APPROVAL_DOCUMENT_SIZE_INVALID")
    if exe == approval:
        raise LocalC12Error("C12_APPROVAL_RECORD_MUST_BE_DISTINCT_FROM_EXE")
    try:
        dsh_main._approved_executable(exe)
    except (OSError, dsh_main.DshMainPayloadError):
        raise LocalC12Error("C12_REAL_WINDOWS_X64_PE_REQUIRED") from None
    observed = _hash(exe)
    if observed != dsh_sha256.lower():
        raise LocalC12Error("C12_INDEPENDENT_MAIN_SHA256_MISMATCH")
    # Hash the external approval document for traceability. A local file alone
    # cannot establish its signer's authority or legal bank redistributability.
    return {
        "status": "SOURCE_BYTES_PRECHECK_ONLY",
        "source_commit": source_commit.lower(),
        "dsh_main_sha256": observed,
        "external_approval_record_sha256": _hash(approval),
        "external_approval_authenticity_verified": False,
        "package_built": False,
        "field_verified": False,
        "bank_final": False,
    }


def _git_head(repo):
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=str(repo),
            stderr=subprocess.DEVNULL, timeout=15)
        return raw.decode("ascii").strip().lower()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, UnicodeError):
        raise LocalC12Error("C12_REAL_GIT_HEAD_REQUIRED") from None


def _verify_source_root(repo, commit):
    if not repo.is_dir() or not (repo / "rc7_release/rc72_package.py").is_file():
        raise LocalC12Error("C12_REAL_RC72_SOURCE_ROOT_REQUIRED")
    if _git_head(repo) != commit:
        raise LocalC12Error("C12_CHECKOUT_SOURCE_COMMIT_MISMATCH")
    # Local modifications are not approved by source-commit verification.
    # Untracked output artifacts are allowed, tracked source changes are not.
    try:
        changed = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=str(repo),
            stderr=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise LocalC12Error("C12_SOURCE_WORKTREE_STATUS_UNAVAILABLE") from None
    if changed.strip():
        raise LocalC12Error("C12_CHECKOUT_HAS_UNCOMMITTED_TRACKED_CHANGES")


def _run(*args, cwd, env=None):
    cmd = [str(v) for v in args]
    result = subprocess.run(
        cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=2400, check=False, env=env)
    if result.returncode:
        # Never emit runner process stdout: upstream tools can accidentally
        # include credential-bearing URLs/headers in their exception messages.
        raise LocalC12Error("C12_OFFLINE_Q2_CHECK_FAILED")
    return result.stdout.decode("utf-8", "replace")


def _powershell(script, *, cwd):
    # UTF-16LE encoded command protects against PowerShell command-line
    # quoting errors. Dynamic paths are additionally single-quote escaped.
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return _run("powershell.exe", "-NoProfile", "-NonInteractive",
                "-EncodedCommand", encoded, cwd=cwd)


@contextmanager
def _isolated_node_outbound_block(*, node, cwd):
    """Scoped Windows Defender outbound rule, removed even on Q2 failure.

    Requires an admin-authorized, ephemeral build VM with Firewall enabled.
    Never disable a firewall or silently skip a blocked-network check.
    """
    executable = Path(node)
    if not executable.is_file():
        raise LocalC12Error("C12_EXTRACTED_NODE_EXECUTABLE_MISSING")
    name = "RC72-C12-NODE-" + secrets.token_hex(10)
    # No untrusted PowerShell arguments: paths are escaped as literal strings.
    quoted = "'" + str(executable).replace("'", "''") + "'"
    add = (
        "$ErrorActionPreference='Stop';"
        "$profiles=@(Get-NetFirewallProfile);"
        "if ($profiles.Count -lt 1 -or @($profiles | Where-Object { -not $_.Enabled }).Count -gt 0)"
        "{throw 'C12_WINDOWS_FIREWALL_DISABLED'};"
        "New-NetFirewallRule -Name '" + name + "'"
        " -DisplayName 'RC72 C12 temporary offline Q2 Node block'"
        " -Program " + quoted +
        " -Direction Outbound -Action Block -Profile Any -Enabled True | Out-Null"
    )
    remove = (
        "$ErrorActionPreference='Stop';"
        "Get-NetFirewallRule -Name '" + name + "' -ErrorAction SilentlyContinue"
        " | Remove-NetFirewallRule -ErrorAction Stop"
    )
    try:
        _powershell(add, cwd=cwd)
        yield
    finally:
        # On both success/failure, do not leave a machine-wide firewall rule
        # or claim Q2 completed if its cleanup fails.
        _powershell(remove, cwd=cwd)


def _safe_extract_zip(archive, destination, required_folder):
    with zipfile.ZipFile(str(archive)) as inp:
        members = inp.infolist()
        if not members:
            raise LocalC12Error("C12_FINAL_ZIP_EMPTY")
        for member in members:
            parts = member.filename.replace("\\", "/").split("/")
            if (not parts or parts[0] != required_folder
                    or any(item in ("", ".", "..") for item in parts[:-1])
                    or (parts[-1] in (".", ".."))
                    or member.filename.startswith(("/", "\\"))):
                raise LocalC12Error("C12_ZIP_ENTRY_OUTSIDE_PACKAGE")
            # tar/unix symlinks and Windows reparse payloads are not permitted.
            if (member.create_system == 3 and
                    ((member.external_attr >> 16) & 0o170000) == 0o120000):
                raise LocalC12Error("C12_ZIP_SYMLINK_FORBIDDEN")
        inp.extractall(str(destination))


def _within(path, directory):
    try:
        return os.path.commonpath([str(Path(path).resolve()),
                                   str(Path(directory).resolve())]) == str(Path(directory).resolve())
    except ValueError:
        # Windows drive letters may differ. Different drives are not nested.
        return False


def _qualify_extracted(*, python, extracted, repo, source_commit, evidence_path,
                       zip_path=None, original_stage=None):
    _run(python, "-m", "rc7_release.rc72_package", "verify",
         "--package-root", extracted,
         "--expected-source-commit", source_commit, cwd=extracted)
    _run(python, "-m", "rc7_release.runtime_delivery_contract",
         "--package-root", extracted, cwd=extracted)
    _run(python, "-m", "rc7_release.rc72_complete_payload_inventory",
         "--package-root", extracted, cwd=extracted)
    _run(python, "-m", "rc7_release.rc72_windows_clean_qualification",
         "--package-root", extracted,
         "--output", evidence_path,
         "--require-pass", cwd=extracted)
    # The official Q2 also requires a real isolated execution node, complete
    # package-owned Python/document capability and a Windows pip mirror check.
    # No force-PASS. The controlled Windows build host must have a verified
    # outbound-block rule for the extracted Node executable; we do not silently
    # alter a bank operator's host firewall.
    _run(python, "-I", extracted / "rc7_release/python_full_capability_probe.py",
         "--runtime-root", python.parent,
         "--output", evidence_path.parent / "c12-full-python-offline.json",
         cwd=extracted)
    _run(python, "-m", "rc7_release.rc72_execution_node_qualification",
         "--package-root", extracted,
         "--evidence-root", evidence_path.parent / "c12-execution-node",
         "--require-windows-outbound-block", "--require-full-text-search",
         cwd=extracted)
    _run(sys.executable, str(repo / "tools/rc72_qa_offline_audit.py"),
         "--package-root", extracted,
         "--expected-source-commit", source_commit, cwd=repo)
    if zip_path is None or original_stage is None:
        raise LocalC12Error("C12_PIP_MIRROR_SOURCE_AND_ARCHIVE_REQUIRED")
    environment = os.environ.copy()
    environment.update({
        "RC72_PIP_MIRROR_COMPONENT": "1",
        "RC72_PIP_MIRROR_PACKAGE_ROOT": str(extracted),
        "RC72_PIP_MIRROR_PACKAGE_ARCHIVE": str(zip_path),
        "RC72_PIP_MIRROR_ORIGINAL_STAGE": str(original_stage),
        "RC72_PIP_MIRROR_EVIDENCE": str(evidence_path.parent / "c12-pip-mirror"),
    })
    _run(python, "-m", "pytest",
         repo / "tests/test_rc72_bank_pc_pip_mirror_windows.py", "-q",
         "--junitxml=" + str(evidence_path.parent / "c12-pip-mirror.xml"),
         cwd=repo, env=environment)


def build(*, repo_root, output, source_commit, dsh_file, dsh_sha256,
          approval_record):
    inspection = preflight(
        source_commit=source_commit, dsh_file=dsh_file,
        dsh_sha256=dsh_sha256, approval_record=approval_record)
    if os.name != "nt":
        raise LocalC12Error("C12_REAL_WINDOWS_BUILD_HOST_REQUIRED")
    repo = Path(repo_root).expanduser().resolve()
    out = Path(output).expanduser().absolute()
    commit = inspection["source_commit"]
    _verify_source_root(repo, commit)
    if out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise LocalC12Error("C12_OUTPUT_PATH_SYMLINK_FORBIDDEN")
    from . import rc72_package, plugin_payload, runtime_payload_materializer
    package_name = rc72_package.RC72_PACKAGE_NAME
    zip_path = out / ("RC72-PORTABLE-WIN10-" + commit[:12] + ".zip")
    package_root = out / package_name
    receipt_path = out / ("RC72-PORTABLE-WIN10-" + commit[:12] + ".receipt.json")
    if (package_root.exists() or zip_path.exists()
            or Path(str(zip_path) + ".sha256").exists() or receipt_path.exists()):
        raise LocalC12Error("C12_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
    if _within(dsh_file, out):
        raise LocalC12Error("C12_MAIN_SOURCE_CANNOT_BE_IN_BUILD_OUTPUT")
    if _within(approval_record, out):
        raise LocalC12Error("C12_APPROVAL_CANNOT_BE_IN_BUILD_OUTPUT")
    out.mkdir(parents=True, exist_ok=True)
    # Same real pipeline as GitHub-hosted rc7.2-portable-transport.yml.
    # The build host must have approved egress/mirror and the pinned runtime
    # acquisition prerequisites; this is not intended for offline bank PCs.
    plugin_payload.acquire(repo)
    package_root = rc72_package.build_package(repo, out, commit, make_zip=False)
    dsh_receipt = dsh_main.materialize(
        package_root, expected_sha256=inspection["dsh_main_sha256"],
        source_file=dsh_file)
    runtime_payload_materializer.materialize(package_root)
    for source, target in (
        ("start-rc7.2.cmd", "start-rc7.2.cmd"),
        ("TRANSPORT-README.md", "READ-ME-FIRST.md"),
    ):
        shutil.copy2(str(repo / "packaging/rc7.2" / source),
                     str(package_root / target))
    rc72_package._rewrite_manifest(package_root, repo, commit)
    rc72_package.verify_package(package_root, expected_source_commit=commit)
    try:
        runtime_payload_materializer._repack(package_root, zip_path)
        with tempfile.TemporaryDirectory(prefix="rc72-c12-clean-", dir=str(out)) as scratch:
            clean = Path(scratch)
            _safe_extract_zip(zip_path, clean, package_name)
            extracted = clean / package_name
            py = extracted / "workspace-template/runtime/python/python.exe"
            if not py.is_file():
                raise LocalC12Error("C12_PACKAGE_LOCAL_PYTHON_MISSING")
            # The official CI installs a scoped outbound firewall block for
            # the fresh package-owned Node path. Reproduce it on a controlled
            # Windows build VM, never skip it on an ordinary operator PC.
            with _isolated_node_outbound_block(
                    node=extracted / "workspace-template/runtime/node/node.exe",
                    cwd=extracted):
                _qualify_extracted(
                    python=py, extracted=extracted, repo=repo,
                    source_commit=commit, evidence_path=out / "c12-clean-runtime.json",
                    zip_path=zip_path, original_stage=package_root)
        if _hash(approval_record) != inspection["external_approval_record_sha256"]:
            raise LocalC12Error("C12_APPROVAL_RECORD_CHANGED_DURING_BUILD")
        receipt = dict(
            inspection, schema="RC72_LOCAL_APPROVED_WINDOWS_Q2_V1",
            status="PHYSICAL_Q2_CANDIDATE_ONLY",
            package_built=True,
            dsh_payload_status=dsh_receipt["status"],
            zip_sha256=_hash(zip_path),
            zip_name=zip_path.name,
            field_verified=False,
            bank_final=False,
        )
        # Output record is outside the sealed package and carries only hashes.
        with receipt_path.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        return receipt
    except Exception:
        # Never leave a misleading apparently deliverable ZIP on Q2 failure.
        zip_path.unlink(missing_ok=True)
        Path(str(zip_path) + ".sha256").unlink(missing_ok=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="RC7.2 C12 approved local Windows DSH ZIP builder")
    parser.add_argument("mode", choices=("preflight", "build"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="dist")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--dsh-file", required=True)
    parser.add_argument("--dsh-sha256", required=True)
    parser.add_argument("--approval-record", required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            result = preflight(
                source_commit=args.source_commit, dsh_file=args.dsh_file,
                dsh_sha256=args.dsh_sha256, approval_record=args.approval_record)
        else:
            result = build(
                repo_root=args.repo_root, output=args.output,
                source_commit=args.source_commit, dsh_file=args.dsh_file,
                dsh_sha256=args.dsh_sha256, approval_record=args.approval_record)
    except (LocalC12Error, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, LocalC12Error) else "C12_LOCAL_BUILD_FAILED"
        result = dict(status="HOLD", reason=reason,
                      field_verified=False, bank_final=False)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in ("SOURCE_BYTES_PRECHECK_ONLY",
                                     "PHYSICAL_Q2_CANDIDATE_ONLY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
