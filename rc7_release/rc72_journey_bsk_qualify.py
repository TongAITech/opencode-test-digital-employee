"""RC7.2 C09 bank-site BrowserSkill qualification; never marks BANK_FIELD PASS.

Operate ONLY on an existing B-authorized BrowserSkill Session+tab. This probe
executes no SUT mutation: verifies portable binary, live extension debug
capability, negotiated cooperative control, and real screenshot PNG Evidence.
Use its receipts alongside separate A/B/E mission and human approval proof.
Python 3.8 stdlib; Windows Git Bash supports package-local python.exe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from rc7_runtime.rc72_journey_playwright import _atomic_json
from rc7_runtime.rc72_journey_png import verify_png_file
from rc7_release.runtime_payload_materializer import BSK_LOCK_VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def qualify_bsk(
    *, package_root: Path, bsk_executable: Path,
    bsk_session_id: str, tab_id: int, output_root: Path,
    runner: Optional[Callable[[Sequence[str]], Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    root = Path(package_root).resolve()
    binary = Path(bsk_executable).resolve()
    output = Path(output_root).resolve()
    stamp = int(time.time())
    report: Dict[str, Any] = {
        "schema": "rc72-c09-bsk-bank-site-readonly-probe-v1",
        "started_at": stamp,
        "status": "BLOCKED",
        "field_verified": False,
        "official_journey_approved": False,
        "sut_mutation_count": 0,
        "checks": [],
    }
    output.mkdir(parents=True, exist_ok=True)

    def write_receipt() -> None:
        _atomic_json(output / "c09-bsk-probe.json", report)

    def check(name: str, value: bool, failure_code: str):
        report["checks"].append({"name": name, "passed": bool(value)})
        if not value:
            raise RuntimeError(failure_code)

    def call(argv: Sequence[str], *, expects_json: bool = True):
        command = [str(binary)] + list(argv)
        if runner is not None:
            data = runner(command)
            if not isinstance(data, Mapping):
                raise RuntimeError("BSK_PROBE_RUNNER_RESULT_INVALID")
            code, stdout = data.get("returncode"), data.get("stdout")
        else:
            env = dict(os.environ)
            env["BSK_AUTO_START"] = "0"
            try:
                result = subprocess.run(
                    command, shell=False, check=False, capture_output=True,
                    text=True, timeout=35, env=env)
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise RuntimeError("BSK_PROBE_CLI_COMMAND_UNAVAILABLE") from exc
            code, stdout = result.returncode, result.stdout
        if code != 0:
            raise RuntimeError("BSK_PROBE_CLI_RETURNED_FAILURE")
        if not expects_json:
            return str(stdout or "").strip()
        try:
            payload = json.loads(stdout)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("BSK_PROBE_CLI_JSON_INVALID") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError("BSK_PROBE_CLI_OBJECT_REQUIRED")
        return payload

    try:
        check("package_root", root.is_dir(), "BSK_PROBE_PACKAGE_ROOT_MISSING")
        source = root / "SOURCE_COMMIT"
        check("source_commit", source.is_file(), "BSK_PROBE_SOURCE_COMMIT_MISSING")
        sha = source.read_text(encoding="utf-8").strip()
        check("source_sha40", bool(re.fullmatch(r"[a-fA-F0-9]{40}", sha)),
              "BSK_PROBE_SOURCE_COMMIT_INVALID")
        report["source_commit"] = sha
        try:
            inside = os.path.commonpath([str(binary), str(root)]) == str(root)
        except ValueError:
            inside = False
        check("package_local_bsk", inside and binary.is_file(),
              "BSK_PROBE_PACKAGE_LOCAL_BINARY_MISSING")
        check("owned_session_identifier",
              isinstance(bsk_session_id, str)
              and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", bsk_session_id)),
              "BSK_PROBE_SESSION_ID_INVALID")
        check("owned_tab_identifier", type(tab_id) is int and tab_id > 0,
              "BSK_PROBE_TAB_ID_INVALID")
        report["bsk_sha256"] = _sha256(binary)
        report["session_fingerprint"] = hashlib.sha256(
            bsk_session_id.encode("utf-8")).hexdigest()[:16]
        report["tab_id"] = tab_id
        version = call(["--version"], expects_json=False)
        check("bsk_cli_version", BSK_LOCK_VERSION in version,
              "BSK_PROBE_CLI_VERSION_NOT_PINNED")
        report["bsk_cli_version"] = version[:120]
        # A previous bank daemon can keep running after CLI files are replaced.
        # Protocol 1.8 + exact daemon/extension 0.4.1 must be proven live;
        # installing a new CLI alone cannot establish the mobile capability.
        daemon = call(["status", "--json"])
        check("bsk_daemon_release",
              daemon.get("daemon_version") == BSK_LOCK_VERSION
              and daemon.get("protocol_version") == "1.8"
              and daemon.get("version_skew_browsers") == [],
              "BSK_PROBE_DAEMON_OR_PROTOCOL_VERSION_MISMATCH")
        scope = ["--session", bsk_session_id, "--tab-id", str(tab_id)]
        caps = call(["debug", "capabilities", *scope, "--json"])
        capability = caps.get("capabilities")
        check("live_extension_capabilities",
              isinstance(capability, Mapping)
              and isinstance(capability.get("extension"), Mapping)
              and isinstance(capability.get("cli"), Mapping),
              "BSK_PROBE_LIVE_EXTENSION_NOT_VERIFIED")
        component_cli = capability["cli"]
        component_ext = capability["extension"]
        check("bsk_live_protocol_and_extension_pin",
              component_cli.get("version") == BSK_LOCK_VERSION
              and str(component_cli.get("protocol_version")) == "1.8"
              and component_ext.get("version") == BSK_LOCK_VERSION,
              "BSK_PROBE_LIVE_EXTENSION_VERSION_MISMATCH")
        report["bsk_component_versions"] = {
            "required_version": BSK_LOCK_VERSION,
            "cli": component_cli.get("version"),
            "daemon": daemon.get("daemon_version"),
            "extension": component_ext.get("version"),
            "protocol_version": str(daemon.get("protocol_version")),
        }
        sync = call([
            "cooperate", "sync", *scope, "--policy", "strict", "--json"])
        check("cooperation_context",
              isinstance(sync.get("context_id"), str)
              and bool(sync["context_id"])
              and sync.get("tab_id") == tab_id,
              "BSK_PROBE_COOPERATIVE_CONTROL_NOT_GRANTED")
        screenshot = output / "live-browser.png"
        check("screenshot_not_preexisting", not screenshot.exists(),
              "BSK_PROBE_EVIDENCE_PATH_COLLISION")
        shot = call([
            "screenshot", *scope, "--out", str(screenshot), "--json"])
        png = verify_png_file(screenshot)
        check("real_bsk_png",
              shot.get("byte_size") == png["bytes"]
              and shot.get("tab_id") == tab_id
              and shot.get("format") == "png",
              "BSK_PROBE_SCREENSHOT_NOT_VERIFIED")
        report["screenshot"] = {
            "sha256": png["sha256"],
            "bytes": png["bytes"],
            "width": png["width"], "height": png["height"],
            "evidence_ref": screenshot.resolve().as_uri(),
        }
        report["status"] = "READ_ONLY_BSK_PROBE_PASS"
        return report
    except Exception as exc:
        report["failure_code"] = str(exc).split(":")[0][:100]
        return report
    finally:
        report["completed_at"] = int(time.time())
        write_receipt()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="C09 BSK bank-site read-only qualification")
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--bsk-bin", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--tab-id", type=int, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = qualify_bsk(
        package_root=args.package_root, bsk_executable=args.bsk_bin,
        bsk_session_id=args.session, tab_id=args.tab_id,
        output_root=args.output_root)
    print(json.dumps({
        "status": receipt["status"],
        "field_verified": receipt["field_verified"],
        "source_commit": receipt.get("source_commit"),
        "failure_code": receipt.get("failure_code"),
        "evidence": str(args.output_root / "c09-bsk-probe.json"),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["status"] == "READ_ONLY_BSK_PROBE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
