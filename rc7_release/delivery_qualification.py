from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .package import PACKAGE_NAME


SCHEMA_VERSION = "pfc.aitest.rc7.delivery-qualification.v1"
GATE = "DELIVERY_PASS"
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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
    result = subprocess.run(
        list(command),
        cwd=str(cwd),
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
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


def _package_env(package_root: Path) -> Dict[str, str]:
    env = dict(os.environ)
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(package_root) + (os.pathsep + old if old else "")
    env["PFC_PYTHON"] = sys.executable
    return env


def _verify_package_local(package_root: Path, env: Mapping[str, str]) -> None:
    _run(
        [sys.executable, "-m", "rc7_release.package", "verify", "--package-root", str(package_root)],
        cwd=package_root,
        env=env,
        label="PACKAGE_LOCAL_VERIFY",
    )
    _run(
        [sys.executable, "-m", "compileall", "-q", "rc6_runtime", "rc6_release", "rc7_runtime", "rc7_release", "rc7_admin"],
        cwd=package_root,
        env=env,
        label="PACKAGE_LOCAL_COMPILE",
    )


def _verify_final_entrypoint(package_root: Path, env: Mapping[str, str], source_commit: str, work_root: Path) -> str:
    state = work_root / "final-entrypoint-state"
    local_env = dict(env)
    local_env["PFC_AITEST_STATE_DIR"] = str(state)
    local_env["PFC_RC7_SOURCE_COMMIT"] = source_commit
    local_env.pop("PFC_RC7_ENGINEERING_EVIDENCE", None)
    local_env.pop("PFC_RC7_ADMIN_EVIDENCE", None)
    local_env.pop("PFC_RC7_REAL_MISSION_EVIDENCE", None)
    local_env.pop("PFC_RC7_DELIVERY_EVIDENCE", None)
    local_env.pop("PFC_RC7_R1_PATH", None)
    local_env.pop("PFC_RC7_MISSION_ID", None)
    local_env.pop("PFC_RC7_REQUIRE_FINAL_PASS", None)

    if os.name == "nt":
        command = ["cmd", "/c", r"packaging\rc7\QUALIFY-FINAL.cmd"]
    else:
        command = ["bash", "packaging/rc7/QUALIFY-FINAL.sh"]
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


def _verify_admin_startup(package_root: Path, env: Mapping[str, str], work_root: Path) -> Dict[str, Any]:
    r1_path = work_root / "admin-smoke-r1.jsonl"
    port = _free_port()
    command = [
        sys.executable,
        "-m",
        "rc7_admin",
        "--r1",
        str(r1_path),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
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


def qualify_delivery(*, zip_path: str, source_commit: str) -> Dict[str, Any]:
    commit = source_commit.strip().lower() if isinstance(source_commit, str) else ""
    if not _SHA_RE.match(commit):
        raise ValueError("INVALID_SOURCE_COMMIT")
    archive_path = Path(zip_path).expanduser().resolve()
    if not archive_path.is_file():
        raise ValueError("DELIVERY_ZIP_NOT_FOUND")

    blockers: List[str] = []
    details: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="rc7-delivery-qualification-") as tmp:
        work_root = Path(tmp).resolve()
        try:
            with zipfile.ZipFile(str(archive_path), "r") as archive:
                _safe_extract(archive, work_root)
            package_root = work_root / PACKAGE_NAME
            if not package_root.is_dir():
                raise DeliveryQualificationError("CLEAN_UNPACK_PACKAGE_ROOT_MISSING")
            details["clean_windows_unpack"] = "PASS" if os.name == "nt" else "PASS_NON_WINDOWS_ENGINEERING"

            source_file = package_root / "SOURCE_COMMIT"
            if not source_file.is_file():
                raise DeliveryQualificationError("PACKAGE_SOURCE_COMMIT_MISSING")
            package_commit = source_file.read_text(encoding="utf-8").strip().lower()
            if package_commit != commit:
                raise DeliveryQualificationError("PACKAGE_SOURCE_COMMIT_MISMATCH")

            env = _package_env(package_root)
            _verify_package_local(package_root, env)
            details["package_verify"] = "PASS"

            entrypoint_result = _verify_final_entrypoint(package_root, env, commit, work_root)
            details["package_entrypoint_verify"] = "PASS"
            details["entrypoint_result_ref"] = "file://" + entrypoint_result

            health = _verify_admin_startup(package_root, env, work_root)
            details["admin_startup_verify"] = "PASS"
            details["admin_health"] = health
        except Exception as exc:
            blockers.append(str(exc))

    status = "PASS" if not blockers else "HOLD"
    return {
        "schema_version": SCHEMA_VERSION,
        "gate": GATE,
        "status": status,
        "source_commit": commit,
        "package_name": PACKAGE_NAME,
        "package_sha256": _sha256(archive_path),
        "clean_windows_unpack": details.get("clean_windows_unpack", "HOLD"),
        "package_verify": details.get("package_verify", "HOLD"),
        "package_entrypoint_verify": details.get("package_entrypoint_verify", "HOLD"),
        "admin_startup_verify": details.get("admin_startup_verify", "HOLD"),
        "admin_health": details.get("admin_health", {}),
        "evidence_refs": [
            "zip://%s#sha256:%s" % (archive_path.name, _sha256(archive_path)),
            details.get("entrypoint_result_ref", ""),
        ],
        "blocking_reasons": blockers,
        "qualification_kind": "CLEAN_TURNKEY_DELIVERY",
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
