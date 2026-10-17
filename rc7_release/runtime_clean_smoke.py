"""Clean-extract smoke qualification for every RC7 turnkey runtime payload.

This gate runs after the transport ZIP has been deleted/re-extracted.  It must
never discover developer/runner tools for product capabilities: every runtime
command is rooted under the extracted package.  Windows' own cmd.exe is only
used as the script host for .cmd/.bat launchers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .runtime_delivery_contract import verify_runtime_delivery


SCHEMA_VERSION = "pfc.aitest.rc7.runtime-clean-smoke.v1"
_BROWSER_MARKER = "RC7_RUNTIME_CLEAN_BROWSER_SMOKE_OK"
Runner = Callable[..., str]


class RuntimeCleanSmokeError(RuntimeError):
    pass


def _command_text(command: Sequence[str]) -> str:
    return " ".join('"%s"' % item if " " in item else item for item in command)


def _default_runner(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    label: str,
    timeout: int = 60,
) -> str:
    try:
        result = subprocess.run(
            list(command),
            cwd=str(cwd),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeCleanSmokeError("%s_TIMEOUT:%s" % (label, _command_text(command))) from exc
    if result.returncode != 0:
        raise RuntimeCleanSmokeError(
            "%s_FAILED:rc=%s:command=%s:output=%s"
            % (label, result.returncode, _command_text(command), result.stdout[-2000:])
        )
    return result.stdout


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeCleanSmokeError("%s_MISSING:%s" % (label, path))
    return path.resolve()


def _require_dir(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise RuntimeCleanSmokeError("%s_MISSING:%s" % (label, path))
    return path.resolve()


def _unique_file(root: Path, name: str, label: str) -> Path:
    matches = [path.resolve() for path in root.rglob(name) if path.is_file() and path.stat().st_size > 0]
    if len(matches) != 1:
        raise RuntimeCleanSmokeError("%s_EXPECTED_ONE:%s:found=%s" % (label, name, len(matches)))
    return matches[0]


def _system_cmd() -> str:
    comspec = str(os.environ.get("COMSPEC") or "").strip()
    if comspec:
        return str(Path(comspec).resolve())
    system_root = str(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows")
    return str((Path(system_root) / "System32" / "cmd.exe").resolve())


def _minimal_env(root: Path, *, java: bool = False, maven: bool = False) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    path_entries: List[str] = []
    if java:
        java_home = root / "workspace-template/runtime/java"
        env["JAVA_HOME"] = str(java_home.resolve())
        path_entries.append(str((java_home / "bin").resolve()))
    if maven:
        maven_home = root / "workspace-template/runtime/maven"
        env["MAVEN_HOME"] = str(maven_home.resolve())
        path_entries.append(str((maven_home / "bin").resolve()))
    system_root = str(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows")
    path_entries.append(str((Path(system_root) / "System32").resolve()))
    env["PATH"] = os.pathsep.join(path_entries)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _cmd_script(script: Path, *args: str) -> List[str]:
    command = '"%s"' % script.resolve()
    if args:
        command += " " + " ".join(args)
    return [_system_cmd(), "/d", "/s", "/c", command]


def _row(label: str, command: Optional[Sequence[str]] = None, output: str = "") -> Dict[str, Any]:
    row: Dict[str, Any] = {"capability": label, "status": "PASS"}
    if command is not None:
        row["command"] = list(command)
    if output:
        row["output"] = output.strip()[-500:]
    return row


def _assert_under_root(root: Path, path: Path, label: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeCleanSmokeError("%s_ESCAPES_PACKAGE:%s" % (label, path)) from exc


def qualify_runtime_clean_smoke(
    package_root: Path | str,
    *,
    runner: Optional[Runner] = None,
    require_windows: bool = True,
) -> Dict[str, Any]:
    root = Path(package_root).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeCleanSmokeError("PACKAGE_ROOT_NOT_FOUND:%s" % root)
    if require_windows and os.name != "nt":
        raise RuntimeCleanSmokeError("WINDOWS_RUNTIME_REQUIRED")

    # Presence/manifest authority runs first.  Smoke never weakens this gate.
    delivery = verify_runtime_delivery(root)
    run = runner or _default_runner
    rows: List[Dict[str, Any]] = []

    def execute(label: str, command: Sequence[str], *, cwd: Optional[Path] = None, env: Optional[Mapping[str, str]] = None, timeout: int = 60) -> str:
        if not command:
            raise RuntimeCleanSmokeError("%s_EMPTY_COMMAND" % label)
        first = Path(command[0])
        # cmd.exe is the only permitted host executable outside the package.
        if first.name.lower() != "cmd.exe":
            _assert_under_root(root, first, label)
        output = run(
            [str(item) for item in command],
            cwd=(cwd or root).resolve(),
            env=dict(env or _minimal_env(root)),
            label=label,
            timeout=timeout,
        )
        rows.append(_row(label, command, output))
        return output

    runtime = root / "workspace-template/runtime"
    python = _require_file(runtime / "python/python.exe", "PYTHON")
    node = _require_file(runtime / "node/node.exe", "NODE")
    chrome = _require_file(runtime / "browser/chrome-win64/chrome.exe", "CONTROLLED_BROWSER")
    codegraph = _require_file(runtime / "code-intelligence/codegraph/codegraph-server-win32-x64.exe", "CODEGRAPH")
    _require_file(codegraph.parent / "onnxruntime.dll", "CODEGRAPH_ONNXRUNTIME")
    java = _require_file(runtime / "java/bin/java.exe", "JDK")
    maven = _require_file(runtime / "maven/bin/mvn.cmd", "MAVEN")

    execute("python", [str(python), "-c", "import sys; print(sys.executable)"])
    execute("node", [str(node), "--version"])

    with tempfile.TemporaryDirectory(prefix="rc7-runtime-clean-browser-") as profile:
        browser_command = [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--user-data-dir=%s" % profile,
            "--dump-dom",
            "data:text/html,<html><body>%s</body></html>" % _BROWSER_MARKER,
        ]
        browser_output = execute("controlled_browser", browser_command, timeout=60)
        if _BROWSER_MARKER not in browser_output:
            raise RuntimeCleanSmokeError("CONTROLLED_BROWSER_MARKER_MISSING")

    browserskill_root = _require_dir(runtime / "browser/browserskill", "BROWSERSKILL")
    bsk = _unique_file(browserskill_root, "bsk.exe", "BROWSERSKILL")
    execute("browserskill", [str(bsk), "--version"])

    extension_root = _require_dir(runtime / "browser/browserskill-extension", "BROWSERSKILL_EXTENSION")
    extension_manifest = _unique_file(extension_root, "manifest.json", "BROWSERSKILL_EXTENSION_MANIFEST")
    try:
        extension = json.loads(extension_manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeCleanSmokeError("BROWSERSKILL_EXTENSION_MANIFEST_INVALID:%s" % exc) from exc
    if not str(extension.get("name") or "").strip() or not str(extension.get("version") or "").strip():
        raise RuntimeCleanSmokeError("BROWSERSKILL_EXTENSION_IDENTITY_MISSING")
    rows.append({"capability": "browserskill_extension", "status": "PASS", "manifest": str(extension_manifest), "version": str(extension["version"])})

    execute("codegraph", [str(codegraph), "--help"], timeout=60)

    rg = _unique_file(_require_dir(runtime / "ripgrep", "RIPGREP"), "rg.exe", "RIPGREP")
    execute("ripgrep", [str(rg), "--version"])
    execute("jdk", [str(java), "-version"], env=_minimal_env(root, java=True))
    execute("maven", _cmd_script(maven, "-version"), env=_minimal_env(root, java=True, maven=True))

    node_exec = _require_dir(runtime / "node-execution", "NODE_EXECUTION")
    _require_dir(node_exec / "node_modules/playwright", "PLAYWRIGHT")
    execute(
        "playwright",
        [str(node), "-e", "const p=require('playwright'); if(!p.chromium||typeof p.chromium.launch!=='function') process.exit(7); console.log('playwright-ok')"],
        cwd=node_exec,
    )

    execute(
        "local_ocr_cv",
        [str(python), "-c", "import cv2,PIL; print(cv2.__version__, PIL.__version__)"],
    )

    maven_repo = _require_dir(runtime / "maven-repository", "MAVEN_BOOTSTRAP_REPOSITORY")
    coordinate_dirs = (
        maven_repo / "org/junit/jupiter/junit-jupiter",
        maven_repo / "org/apache/maven/plugins/maven-surefire-plugin",
        maven_repo / "org/apache/maven/plugins/maven-failsafe-plugin",
        maven_repo / "org/jacoco/jacoco-maven-plugin",
    )
    for coordinate in coordinate_dirs:
        if not coordinate.is_dir() or not any(coordinate.rglob("*.pom")):
            raise RuntimeCleanSmokeError("MAVEN_BOOTSTRAP_COORDINATE_MISSING:%s" % coordinate.relative_to(maven_repo).as_posix())
    rows.append({"capability": "maven_bootstrap_repository", "status": "PASS", "coordinates": [str(path.relative_to(maven_repo).as_posix()) for path in coordinate_dirs]})

    allure = _unique_file(_require_dir(runtime / "allure", "ALLURE"), "allure.bat", "ALLURE")
    execute("allure", _cmd_script(allure, "--version"), env=_minimal_env(root, java=True))

    k6 = _unique_file(_require_dir(runtime / "k6", "K6"), "k6.exe", "K6")
    execute("k6", [str(k6), "version"])

    zap_root = _require_dir(runtime / "zap", "ZAP")
    zap_jars = [path.resolve() for path in zap_root.rglob("zap-*.jar") if path.is_file() and path.stat().st_size > 0]
    if len(zap_jars) != 1:
        raise RuntimeCleanSmokeError("ZAP_EXPECTED_ONE_MAIN_JAR:found=%s" % len(zap_jars))
    execute("zap", [str(java), "-jar", str(zap_jars[0]), "-version"], env=_minimal_env(root, java=True), timeout=120)

    dsh_plugins = _require_dir(runtime / "dsh-plugins", "DSH_PLUGINS")
    if not any(dsh_plugins.rglob("package.json")):
        raise RuntimeCleanSmokeError("DSH_PLUGIN_PACKAGE_MANIFESTS_MISSING")
    plugin_output = execute(
        "dsh_plugins",
        [str(python), "-m", "rc7_release.plugin_payload", "inspect", "--home", str(root)],
        cwd=root,
    )
    try:
        plugin_payload = json.loads(plugin_output.strip().splitlines()[-1])
    except Exception as exc:
        raise RuntimeCleanSmokeError("DSH_PLUGIN_INSPECT_OUTPUT_INVALID:%s" % exc) from exc
    if plugin_payload.get("status") != "PASS":
        raise RuntimeCleanSmokeError("DSH_PLUGIN_INSPECT_NOT_PASS")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "package_root": str(root),
        "delivery_runtime_complete": bool(delivery.get("delivery_runtime_complete")),
        "required_payload_count": int(delivery.get("required_payload_count") or 0),
        "smoke_count": len(rows),
        "smokes": rows,
        "blocking_reasons": [],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.runtime_clean_smoke")
    parser.add_argument("--package-root", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = qualify_runtime_clean_smoke(args.package_root)
    except Exception as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "FAIL", "blocking_reasons": [str(exc)]}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
