from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .package import PACKAGE_LOCAL_BROWSER, PACKAGE_LOCAL_CODEGRAPH, PACKAGE_LOCAL_PYTHON, PACKAGE_NAME


SCHEMA_VERSION = "pfc.aitest.rc7.delivery-qualification.v1"
GATE = "DELIVERY_PASS"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_BROWSER_SMOKE_MARKER = "PFC_RC7_BROWSER_SMOKE_OK"


class DeliveryQualificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination_resolved = destination.resolve()
    for member in archive.infolist():
        member_path = (destination / member.filename).resolve()
        try:
            member_path.relative_to(destination_resolved)
        except ValueError as exc:
            raise DeliveryQualificationError("ZIP_PATH_TRAVERSAL_FORBIDDEN:%s" % member.filename) from exc
    archive.extractall(str(destination))


def _run(command: Sequence[str], *, cwd: Path, env: Mapping[str, str], label: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise DeliveryQualificationError("%s_TIMEOUT" % label) from exc
    if result.returncode != 0:
        raise DeliveryQualificationError(
            "%s_FAILED:rc=%s:stdout=%s:stderr=%s"
            % (label, result.returncode, result.stdout[-2000:], result.stderr[-2000:])
        )
    return result


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _package_env(package_root: Path, python_executable: Path) -> Dict[str, str]:
    env = dict(os.environ)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(package_root) + (os.pathsep + old if old else "")
    env["PFC_PYTHON"] = str(python_executable)
    package_codegraph = package_root / PACKAGE_LOCAL_CODEGRAPH
    if package_codegraph.is_file():
        env["PFC_CODEGRAPH_BIN"] = str(package_codegraph)
    package_browser = package_root / PACKAGE_LOCAL_BROWSER
    if package_browser.is_file():
        env["PFC_BROWSER_BIN"] = str(package_browser)
        env["PFC_CHROME_BIN"] = str(package_browser)
    return env


def _verify_package_local(
    package_root: Path,
    env: Mapping[str, str],
    python_executable: Path,
) -> None:
    _run(
        [str(python_executable), "-m", "rc7_release.package", "verify", "--package-root", str(package_root)],
        cwd=package_root,
        env=env,
        label="PACKAGE_LOCAL_VERIFY",
    )
    _run(
        [str(python_executable), "-m", "compileall", "-q", "rc6_runtime", "rc6_release", "rc7_runtime", "rc7_release", "rc7_admin"],
        cwd=package_root,
        env=env,
        label="PACKAGE_LOCAL_COMPILE",
    )


def _runtime_payload(
    package_root: Path,
    *,
    field: str,
    expected_path: Path,
    label: str,
) -> tuple:
    manifest_path = package_root / "PACKAGE_MANIFEST.json"
    if not manifest_path.is_file():
        raise DeliveryQualificationError("PACKAGE_MANIFEST_MISSING_FOR_%s" % label)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = manifest.get(field)
    if not isinstance(payload, dict):
        raise DeliveryQualificationError("PACKAGE_%s_MANIFEST_MISSING" % label)
    if payload.get("path") != expected_path.as_posix():
        raise DeliveryQualificationError("PACKAGE_%s_MANIFEST_PATH_INVALID" % label)
    if payload.get("bundled") is not True:
        raise DeliveryQualificationError("PACKAGE_%s_NOT_BUNDLED" % label)
    expected_hash = payload.get("sha256")
    if not isinstance(expected_hash, str) or not re.match(r"^[0-9a-fA-F]{64}$", expected_hash):
        raise DeliveryQualificationError("PACKAGE_%s_MANIFEST_HASH_INVALID" % label)
    binary = package_root / expected_path
    if not binary.is_file():
        raise DeliveryQualificationError("PACKAGE_LOCAL_%s_RUNTIME_MISSING" % label)
    actual_hash = _sha256(binary)
    if actual_hash.lower() != expected_hash.lower():
        raise DeliveryQualificationError("PACKAGE_LOCAL_%s_HASH_MISMATCH" % label)
    return payload, binary, actual_hash


def _verify_package_codegraph(package_root: Path, env: Mapping[str, str], details: Dict[str, Any]) -> None:
    payload, binary, actual_hash = _runtime_payload(
        package_root,
        field="package_local_codegraph",
        expected_path=PACKAGE_LOCAL_CODEGRAPH,
        label="CODEGRAPH",
    )
    if os.name == "nt":
        _run([str(binary), "--help"], cwd=package_root, env=env, label="PACKAGE_LOCAL_CODEGRAPH_SMOKE")
    details["package_local_codegraph_verify"] = "PASS" if os.name == "nt" else "HOLD_NON_WINDOWS"
    details["package_codegraph_ref"] = "file://" + str(binary)
    details["package_codegraph_sha256"] = actual_hash
    details["package_codegraph_version"] = payload.get("resolved_version")


def _browser_smoke_command(binary: Path, profile: Path) -> List[str]:
    return [
        str(binary),
        "--headless",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--user-data-dir=%s" % profile,
        "--dump-dom",
        "data:text/html,%s" % _BROWSER_SMOKE_MARKER,
    ]


def _verify_package_browser(package_root: Path, env: Mapping[str, str], details: Dict[str, Any]) -> None:
    payload, binary, actual_hash = _runtime_payload(
        package_root,
        field="package_local_browser",
        expected_path=PACKAGE_LOCAL_BROWSER,
        label="BROWSER",
    )
    if os.name == "nt":
        with tempfile.TemporaryDirectory(prefix="rc7-browser-smoke-") as profile:
            result = _run(
                _browser_smoke_command(binary, Path(profile)),
                cwd=package_root,
                env=env,
                label="PACKAGE_LOCAL_BROWSER_SMOKE",
            )
        if _BROWSER_SMOKE_MARKER not in result.stdout:
            raise DeliveryQualificationError("PACKAGE_LOCAL_BROWSER_SMOKE_OUTPUT_INVALID")
    details["package_local_browser_verify"] = "PASS" if os.name == "nt" else "HOLD_NON_WINDOWS"
    details["package_browser_ref"] = "file://" + str(binary)
    details["package_browser_sha256"] = actual_hash
    details["package_browser_version"] = payload.get("resolved_version")


def _verify_final_entrypoint(package_root: Path, env: Mapping[str, str], source_commit: str, work_root: Path) -> str:
    state = work_root / "final-entrypoint-state"
    local_env = dict(env)
    local_env["PFC_AITEST_STATE_DIR"] = str(state)
    local_env["PFC_RC7_SOURCE_COMMIT"] = source_commit
    for key in (
        "PFC_RC7_ENGINEERING_EVIDENCE",
        "PFC_RC7_ADMIN_EVIDENCE",
        "PFC_RC7_REAL_MISSION_EVIDENCE",
        "PFC_RC7_DELIVERY_EVIDENCE",
        "PFC_RC7_R1_PATH",
        "PFC_RC7_MISSION_ID",
        "PFC_RC7_REQUIRE_FINAL_PASS",
    ):
        local_env.pop(key, None)

    command = ["cmd", "/c", r"packaging\rc7\QUALIFY-FINAL.cmd"] if os.name == "nt" else ["bash", "packaging/rc7/QUALIFY-FINAL.sh"]
    _run(command, cwd=package_root, env=local_env, label="PACKAGE_FINAL_ENTRYPOINT")
    result_path = state / "rc7-final-qualification.json"
    if not result_path.is_file():
        raise DeliveryQualificationError("PACKAGE_FINAL_ENTRYPOINT_RESULT_MISSING")
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    if result.get("status") != "HOLD":
        raise DeliveryQualificationError("PACKAGE_FINAL_ENTRYPOINT_MUST_FAIL_CLOSED")
    if result.get("source_commit") != source_commit:
        raise DeliveryQualificationError("PACKAGE_FINAL_ENTRYPOINT_COMMIT_MISMATCH")
    return str(result_path)


def _verify_admin_startup(
    package_root: Path,
    env: Mapping[str, str],
    work_root: Path,
    python_executable: Path,
) -> Dict[str, Any]:
    r1_path = work_root / "admin-smoke-r1.jsonl"
    port = _free_port()
    process = subprocess.Popen(
        [
            str(python_executable),
            "-m",
            "rc7_admin",
            "--r1",
            str(r1_path),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(package_root),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    url = "http://127.0.0.1:%d/api/health" % port
    last_error = ""
    try:
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=2)
                raise DeliveryQualificationError(
                    "ADMIN_STARTUP_EXITED:rc=%s:stdout=%s:stderr=%s"
                    % (process.returncode, stdout[-2000:], stderr[-2000:])
                )
            try:
                with urllib.request.urlopen(url, timeout=1.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") != "UP" or payload.get("truth") != "R1_EVENT_STREAM":
                    raise DeliveryQualificationError("ADMIN_HEALTH_CONTRACT_INVALID")
                return {"url": url, "status": "UP", "truth": "R1_EVENT_STREAM"}
            except DeliveryQualificationError:
                raise
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.2)
        raise DeliveryQualificationError("ADMIN_STARTUP_TIMEOUT:%s" % last_error)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _select_qualification_python(package_root: Path, blockers: List[str], details: Dict[str, Any]) -> Path:
    package_python = package_root / PACKAGE_LOCAL_PYTHON
    if os.name == "nt":
        if not package_python.is_file():
            raise DeliveryQualificationError("PACKAGE_LOCAL_PYTHON_RUNTIME_MISSING")
        details["package_local_python_verify"] = "PASS"
        details["package_python_ref"] = "file://" + str(package_python)
        return package_python

    blockers.append("PACKAGE_LOCAL_PYTHON_REQUIRES_WINDOWS_RUNTIME")
    details["package_local_python_verify"] = "HOLD_NON_WINDOWS"
    details["package_python_ref"] = "host-diagnostic://" + sys.executable
    return Path(sys.executable)


def qualify_delivery(*, zip_path: str, source_commit: str) -> Dict[str, Any]:
    commit = source_commit.strip().lower() if isinstance(source_commit, str) else ""
    if not _SHA_RE.match(commit):
        raise ValueError("INVALID_SOURCE_COMMIT")
    archive_path = Path(zip_path).expanduser().resolve()
    if not archive_path.is_file():
        raise ValueError("DELIVERY_ZIP_NOT_FOUND")

    blockers: List[str] = []
    details: Dict[str, Any] = {}
    if os.name != "nt":
        blockers.extend(
            [
                "CLEAN_WINDOWS_UNPACK_REQUIRES_WINDOWS_RUNTIME",
                "PACKAGE_LOCAL_CODEGRAPH_REQUIRES_WINDOWS_RUNTIME",
                "PACKAGE_LOCAL_BROWSER_REQUIRES_WINDOWS_RUNTIME",
            ]
        )
    with tempfile.TemporaryDirectory(prefix="rc7-delivery-qualification-") as tmp:
        work_root = Path(tmp).resolve()
        try:
            with zipfile.ZipFile(str(archive_path), "r") as archive:
                _safe_extract(archive, work_root)
            package_root = work_root / PACKAGE_NAME
            if not package_root.is_dir():
                raise DeliveryQualificationError("CLEAN_UNPACK_PACKAGE_ROOT_MISSING")
            details["clean_windows_unpack"] = "PASS" if os.name == "nt" else "HOLD_NON_WINDOWS"

            source_file = package_root / "SOURCE_COMMIT"
            if not source_file.is_file():
                raise DeliveryQualificationError("PACKAGE_SOURCE_COMMIT_MISSING")
            package_commit = source_file.read_text(encoding="utf-8").strip().lower()
            if package_commit != commit:
                raise DeliveryQualificationError("PACKAGE_SOURCE_COMMIT_MISMATCH")

            python_executable = _select_qualification_python(package_root, blockers, details)
            env = _package_env(package_root, python_executable)
            _run(
                [str(python_executable), "-c", "import sys; print(sys.executable)"],
                cwd=package_root,
                env=env,
                label="PACKAGE_LOCAL_PYTHON_SMOKE",
            )
            _verify_package_local(package_root, env, python_executable)
            details["package_verify"] = "PASS"

            _verify_package_codegraph(package_root, env, details)
            _verify_package_browser(package_root, env, details)

            entrypoint_result = _verify_final_entrypoint(package_root, env, commit, work_root)
            details["package_entrypoint_verify"] = "PASS"
            details["entrypoint_result_ref"] = "file://" + entrypoint_result

            health = _verify_admin_startup(package_root, env, work_root, python_executable)
            details["admin_startup_verify"] = "PASS"
            details["admin_health"] = health
        except Exception as exc:
            blockers.append(str(exc))

    digest = _sha256(archive_path)
    refs = ["zip://%s#sha256:%s" % (archive_path.name, digest)]
    for ref_key, hash_key in (
        ("package_codegraph_ref", "package_codegraph_sha256"),
        ("package_browser_ref", "package_browser_sha256"),
    ):
        if details.get(ref_key):
            refs.append(str(details[ref_key]) + "#sha256:" + str(details.get(hash_key, "")))
    if details.get("entrypoint_result_ref"):
        refs.append(details["entrypoint_result_ref"])
    if details.get("package_python_ref"):
        refs.append(details["package_python_ref"])

    status = "PASS" if not blockers else "HOLD"
    return {
        "schema_version": SCHEMA_VERSION,
        "gate": GATE,
        "status": status,
        "source_commit": commit,
        "package_name": PACKAGE_NAME,
        "package_sha256": digest,
        "clean_windows_unpack": details.get("clean_windows_unpack", "HOLD"),
        "package_local_python_verify": details.get("package_local_python_verify", "HOLD"),
        "package_local_codegraph_verify": details.get("package_local_codegraph_verify", "HOLD"),
        "package_local_codegraph_version": details.get("package_codegraph_version"),
        "package_local_codegraph_sha256": details.get("package_codegraph_sha256"),
        "package_local_browser_verify": details.get("package_local_browser_verify", "HOLD"),
        "package_local_browser_version": details.get("package_browser_version"),
        "package_local_browser_sha256": details.get("package_browser_sha256"),
        "package_verify": details.get("package_verify", "HOLD"),
        "package_entrypoint_verify": details.get("package_entrypoint_verify", "HOLD"),
        "admin_startup_verify": details.get("admin_startup_verify", "HOLD"),
        "admin_health": details.get("admin_health", {}),
        "evidence_refs": refs,
        "blocking_reasons": blockers,
        "qualification_kind": "CLEAN_TURNKEY_DELIVERY_PACKAGE_LOCAL_RUNTIME",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.delivery_qualification")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)
    result = qualify_delivery(zip_path=args.zip, source_commit=args.source_commit)
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.require_pass and result["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())