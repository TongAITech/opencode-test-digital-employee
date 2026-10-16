from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import dsh_plugins


class PluginQualificationError(RuntimeError):
    pass


def _dsh_home() -> Path:
    configured = os.environ.get("DSH_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".dsh").resolve()


def _package_manifests(profile: Path) -> Iterable[Path]:
    node_modules = profile / "node_modules"
    if not node_modules.is_dir():
        return ()
    rows: List[Path] = []
    for child in sorted(node_modules.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("@"):
            for package in sorted(child.iterdir()):
                manifest = package / "package.json"
                if manifest.is_file():
                    rows.append(manifest)
        else:
            manifest = child / "package.json"
            if manifest.is_file():
                rows.append(manifest)
    return tuple(rows)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def profile_contract_snapshot(profile_name: str) -> Dict[str, object]:
    profile = _dsh_home() / "profiles" / profile_name
    if not profile.is_dir():
        return {"profile": profile_name, "exists": False, "digest": None, "files": {}}
    important: List[Path] = []
    for name in ("package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock"):
        target = profile / name
        if target.is_file():
            important.append(target)
    important.extend(_package_manifests(profile))
    rows = {}
    for path in important:
        rel = path.relative_to(profile).as_posix()
        rows[rel] = {"sha256": _hash_file(path), "size": path.stat().st_size}
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "profile": profile_name,
        "exists": True,
        "digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "files": rows,
    }


def _run(command: List[str], env: Dict[str, str], timeout: int = 90) -> Dict[str, object]:
    proc = subprocess.run(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    output = dsh_plugins._decode(proc.stdout or b"")
    return {"exit_code": proc.returncode, "output_tail": output[-4000:]}


def _profile_boot(dsh: str, profile: str, env: Dict[str, str], port: int, seconds: int) -> Dict[str, object]:
    command = [dsh, "--profile", profile, "--no-open", "--port", str(port)]
    proc = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    started = time.monotonic()
    try:
        while time.monotonic() - started < seconds:
            code = proc.poll()
            if code is not None:
                output = b""
                if proc.stdout is not None:
                    output = proc.stdout.read() or b""
                return {
                    "status": "FAIL",
                    "reason": "PROFILE_EXITED_BEFORE_BOOT_WINDOW",
                    "exit_code": code,
                    "output_tail": dsh_plugins._decode(output)[-4000:],
                }
            time.sleep(0.25)
        return {"status": "PASS", "boot_window_seconds": seconds, "pid": proc.pid}
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)


def qualify(
    home: Path,
    *,
    protected_profile: str = "web",
    isolated_profile: str = "rc7-qualification",
    boot_port: int = 4099,
    boot_seconds: int = 5,
) -> Dict[str, object]:
    if isolated_profile == protected_profile or isolated_profile in dsh_plugins.protected_profiles():
        raise PluginQualificationError("ISOLATED_PROFILE_MUST_NOT_BE_PROTECTED")
    if boot_seconds < 2 or boot_seconds > 30:
        raise PluginQualificationError("BOOT_SECONDS_OUT_OF_RANGE")
    if boot_port < 1024 or boot_port > 65535:
        raise PluginQualificationError("BOOT_PORT_OUT_OF_RANGE")

    env = dsh_plugins.prepare_env(home)
    dsh = shutil.which("dsh", path=env.get("PATH"))
    pre = profile_contract_snapshot(protected_profile)
    if not dsh:
        return {
            "status": "HOLD",
            "reason": "BANK_DSH_HOST_NOT_FOUND",
            "protected_profile_before": pre,
        }

    initialize = _run(
        [dsh, "--profile", isolated_profile, "--from-default-profile", "web", "--dump-config"],
        env,
    )
    if initialize["exit_code"] != 0:
        return {
            "status": "FAIL",
            "reason": "ISOLATED_PROFILE_INITIALIZATION_FAILED",
            "initialize": initialize,
            "protected_profile_before": pre,
        }

    install = dsh_plugins.install(
        home,
        isolated_profile,
        allow_profile_mutation=True,
        include_diagnostic=False,
    )
    if install.get("status") != "PASS":
        return {
            "status": "FAIL",
            "reason": "P0_PLUGIN_INSTALL_FAILED",
            "install": install,
            "protected_profile_before": pre,
            "protected_profile_after": profile_contract_snapshot(protected_profile),
        }

    config = _run([dsh, "--profile", isolated_profile, "--dump-config"], env)
    boot = _profile_boot(dsh, isolated_profile, env, boot_port, boot_seconds)
    post = profile_contract_snapshot(protected_profile)
    integrity = pre.get("digest") == post.get("digest") and pre.get("exists") == post.get("exists")

    gates = {
        "PAYLOAD": "PASS",
        "DEPENDENCY_RESOLVE_INSTALL": "PASS",
        "PROFILE_CONFIG": "PASS" if config["exit_code"] == 0 else "FAIL",
        "PROFILE_BOOT": boot.get("status", "FAIL"),
        "PROTECTED_BANK_PROFILE_INTEGRITY": "PASS" if integrity else "FAIL",
        "REAL_PLUGIN_TOOL_CALL": "HOLD_FIELD_PLUGIN_SPECIFIC_CALL_REQUIRED",
    }
    hard_pass = all(
        value == "PASS"
        for key, value in gates.items()
        if key != "REAL_PLUGIN_TOOL_CALL"
    )
    return {
        "status": "HOLD" if hard_pass else "FAIL",
        "reason": "REAL_PLUGIN_TOOL_CALL_REQUIRED" if hard_pass else "PLUGIN_RUNTIME_QUALIFICATION_FAILED",
        "profile": isolated_profile,
        "protected_profile": protected_profile,
        "initialize": initialize,
        "install": install,
        "config": config,
        "boot": boot,
        "protected_profile_before": pre,
        "protected_profile_after": post,
        "gates": gates,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True)
    parser.add_argument("--protected-profile", default="web")
    parser.add_argument("--isolated-profile", default="rc7-qualification")
    parser.add_argument("--boot-port", type=int, default=4099)
    parser.add_argument("--boot-seconds", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = qualify(
        Path(args.home).resolve(),
        protected_profile=args.protected_profile,
        isolated_profile=args.isolated_profile,
        boot_port=args.boot_port,
        boot_seconds=args.boot_seconds,
    )
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("status") in ("PASS", "HOLD") else 2


if __name__ == "__main__":
    raise SystemExit(main())
