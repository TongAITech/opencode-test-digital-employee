#!/usr/bin/env python3
"""Verify/install/uninstall the RC7.2 offline DSH ecosystem bundle.

Python 3.8+; bank-side code never contacts npm, pip, GitHub or a public registry.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = "pfc.rc72.dsh-ecosystem-offline.v1"
PROFILE_DEFAULT = "rc7.2-bank"
PACKAGE_IDS = ("dsh-skills-manager", "dsh-mnemon", "dsh-archify", "modlens")
PACKAGE_NAMES = {
    "dsh-skills-manager": "@michengai/dsh-skills-manager",
    "dsh-mnemon": "dsh-mnemon",
    "dsh-archify": "dsh-archify",
    "modlens": "@liustack/modlens",
}
EXCLUDED = ["dsh-qa", "dsh-routing-suite", "WeKnora", "dsh-weknora"]


class InstallError(RuntimeError):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _tree_sha256(root):
    root = Path(root)
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        h.update(relative + b"\0")
        h.update(bytes.fromhex(_sha256(path)))
    return h.hexdigest()


def _platform_id():
    machine = platform.machine().lower()
    if machine not in ("amd64", "x86_64"):
        raise InstallError("UNSUPPORTED_CPU_ARCHITECTURE")
    if os.name == "nt":
        return "win32-x64"
    if platform.system().lower() == "linux":
        return "linux-x64"
    raise InstallError("UNSUPPORTED_OPERATING_SYSTEM")


def _is_bundle_root(path):
    return (
        path.is_dir()
        and (path / "manifest.json").is_file()
        and (path / "install.py").is_file()
        and (path / "packages").is_dir()
        and (path / "runtime/mnemon").is_dir()
    )


def resolve_bundle_root(value=None):
    start = Path(value or __file__).expanduser()
    if start.is_file():
        start = start.parent
    start = start.resolve()
    if _is_bundle_root(start):
        return start
    for parent in list(start.parents)[:8]:
        if _is_bundle_root(parent):
            return parent
    found = []
    frontier = [start]
    for _ in range(4):
        next_frontier = []
        for parent in frontier:
            try:
                children = [p for p in parent.iterdir() if p.is_dir() and not p.is_symlink()]
            except OSError:
                continue
            for child in children:
                if _is_bundle_root(child):
                    found.append(child.resolve())
                else:
                    next_frontier.append(child)
        frontier = next_frontier
    found = sorted(set(found))
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise InstallError("BUNDLE_ROOT_AMBIGUOUS")
    raise InstallError("BUNDLE_ROOT_NOT_FOUND")


def verify_bundle(root=None):
    root = resolve_bundle_root(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA:
        raise InstallError("BUNDLE_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("platform") != _platform_id():
        raise InstallError("BUNDLE_PLATFORM_MISMATCH")
    if manifest.get("explicit_exclusions") != EXCLUDED:
        raise InstallError("BUNDLE_EXCLUSION_POLICY_MISMATCH")
    extensions = manifest.get("extensions")
    if not isinstance(extensions, list) or len(extensions) != 4:
        raise InstallError("BUNDLE_EXTENSION_COUNT_MISMATCH")
    ids = [row.get("id") for row in extensions]
    if set(ids) != set(PACKAGE_IDS):
        raise InstallError("BUNDLE_EXTENSION_SET_MISMATCH")
    for row in extensions:
        package_id = row["id"]
        package_root = root / "packages" / package_id
        if not package_root.is_dir():
            raise InstallError("BUNDLE_PACKAGE_MISSING:%s" % package_id)
        package = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
        if package.get("name") != PACKAGE_NAMES[package_id] or package.get("version") != row.get("version"):
            raise InstallError("BUNDLE_PACKAGE_IDENTITY_MISMATCH:%s" % package_id)
        if package.get("license") != row.get("license"):
            raise InstallError("BUNDLE_PACKAGE_LICENSE_MISMATCH:%s" % package_id)
        if row.get("bundle_tree_sha256") and _tree_sha256(package_root) != row["bundle_tree_sha256"]:
            raise InstallError("BUNDLE_PACKAGE_TREE_SHA256_MISMATCH:%s" % package_id)
        if not (package_root / "node_modules").is_dir() and (package.get("dependencies") or {}):
            raise InstallError("BUNDLE_DEPENDENCIES_MISSING:%s" % package_id)
    native = manifest.get("mnemon_native_cli") or {}
    native_path = root / native.get("path", "")
    if not native_path.is_file() or _sha256(native_path) != native.get("sha256"):
        raise InstallError("MNEMON_NATIVE_CLI_SHA256_MISMATCH")
    return {"status": "PASS", "root": str(root), "platform": manifest["platform"],
            "extensions": len(extensions), "manifest": manifest}


def _run(command, env=None):
    command = [str(x) for x in command]
    try:
        if os.name == "nt" and Path(command[0]).suffix.lower() in (".cmd", ".bat"):
            line = subprocess.list2cmdline(command)
            result = subprocess.run(line, shell=True, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=240, check=False)
        else:
            result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=240, check=False)
    except Exception as exc:
        raise InstallError("DSH_COMMAND_COULD_NOT_START:%s" % command[0]) from exc
    output = (result.stdout or b"").decode("utf-8", errors="replace")
    if result.returncode:
        raise InstallError("DSH_COMMAND_FAILED:%s:%s" % (command[1] if len(command) > 1 else command[0], output[-1200:]))
    return output


def _dsh_version(output):
    matches = re.findall(r"(?<!\d)(\d+\.\d+\.\d+(?:-rc\.\d+)?)(?!\d)", output)
    if not matches:
        raise InstallError("DSH_VERSION_UNREADABLE")
    return matches[0]


def _version_tuple(value):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?", value)
    if not match:
        raise InstallError("DSH_VERSION_FORMAT_UNSUPPORTED")
    major, minor, patch, rc = match.groups()
    return (int(major), int(minor), int(patch), 0 if rc is not None else 1, int(rc or 0))


def _check_dsh_compatibility(version):
    v = _version_tuple(version)
    skills_min = _version_tuple("0.2.0-rc.1")
    upper = _version_tuple("0.3.0-rc.0")
    mnemon_min = _version_tuple("0.2.1-rc.1")
    mnemon_legacy_min = _version_tuple("0.2.0-rc.2")
    if not (skills_min <= v < upper):
        raise InstallError("DSH_VERSION_OUTSIDE_SKILLS_MANAGER_RANGE:%s" % version)
    if not ((mnemon_legacy_min <= v < mnemon_min) or (mnemon_min <= v < upper)):
        raise InstallError("DSH_VERSION_OUTSIDE_MNEMON_RANGE:%s" % version)


def _resolve_dsh(value):
    candidate = value or shutil.which("dsh") or shutil.which("dsh.cmd") or shutil.which("dsh.exe")
    if not candidate:
        raise InstallError("DSH_HOST_NOT_FOUND_USE_--dsh-bin")
    path = Path(candidate)
    if path.is_file():
        return str(path.resolve())
    found = shutil.which(str(candidate))
    if found:
        return found
    raise InstallError("DSH_HOST_NOT_FOUND")


def _safe_copytree(source, target):
    source, target = Path(source), Path(target)
    if target.exists():
        raise InstallError("REFUSE_OVERWRITE_EXISTING_ECOSYSTEM_PAYLOAD:%s" % target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(source), str(target), symlinks=False)


def _receipt_path(rc72_home):
    return Path(rc72_home) / "runtime-state" / "ecosystem-extensions" / "install-receipt.json"


def _resolve_node(rc72_home):
    runtime = Path(rc72_home) / "workspace-template" / "runtime" / "node"
    candidates = (
        runtime / ("node.exe" if os.name == "nt" else "node"),
        runtime / "node.exe",
        runtime / "node",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    found = shutil.which("node") or shutil.which("node.exe")
    if not found:
        raise InstallError("NODE_RUNTIME_NOT_FOUND")
    return found


def _node_version(node_bin):
    output = _run([node_bin, "--version"])
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", output)
    if not match:
        raise InstallError("NODE_VERSION_UNREADABLE")
    return tuple(int(value) for value in match.groups()), output.strip()


def _require_node(node_bin, minimum, purpose):
    observed, output = _node_version(node_bin)
    if observed < minimum:
        raise InstallError("%s_NODE_VERSION_TOO_OLD:%s" % (purpose, output))
    return output


def install(root=None, *, rc72_home, dsh_bin=None, profile=PROFILE_DEFAULT):
    checked = verify_bundle(root)
    root = Path(checked["root"])
    if not re.fullmatch(r"rc7\.2-[a-z0-9][a-z0-9._-]{0,40}", profile):
        raise InstallError("PROTECTED_OR_NON_RC72_PROFILE_FORBIDDEN")
    rc72_home = Path(rc72_home).expanduser().resolve()
    if not ((rc72_home / "SOURCE_COMMIT").is_file()
            and (rc72_home / "packaging/rc7.2/AITEST.sh").is_file()):
        raise InstallError("RC72_PACKAGE_ROOT_REQUIRED")
    dsh = _resolve_dsh(dsh_bin)
    dsh_version = _dsh_version(_run([dsh, "--version"]))
    _check_dsh_compatibility(dsh_version)
    node_bin = _resolve_node(rc72_home)
    node_version = _require_node(node_bin, (20, 0, 0), "ECOSYSTEM")

    runtime_root = rc72_home / "workspace-template" / "runtime"
    extension_root = runtime_root / "dsh-ecosystem-extensions"
    package_target = extension_root / "packages"
    mnemon_root = runtime_root / "mnemon"
    native = checked["manifest"]["mnemon_native_cli"]
    native_source = root / native["path"]
    native_target = mnemon_root / native_source.name
    policy_dir = rc72_home / "runtime-state" / "ecosystem-extensions"
    template_source = root / "modlens-config.bank-template.json"
    template_target = policy_dir / "modlens-config.bank-template.json"
    receipt_path = _receipt_path(rc72_home)
    if extension_root.exists() or native_target.exists():
        raise InstallError("ECOSYSTEM_INSTALL_TARGET_ALREADY_EXISTS_RUN_HEALTH_OR_UNINSTALL")
    if template_target.exists() or receipt_path.exists():
        raise InstallError("ECOSYSTEM_INSTALL_RECEIPT_OR_POLICY_TEMPLATE_ALREADY_EXISTS")

    installed = []
    native_created = False
    extension_created = False
    template_created = False
    receipt_created = False
    receipt_temp = receipt_path.with_name(receipt_path.name + ".tmp")
    env = os.environ.copy()
    try:
        extension_root.mkdir(parents=True)
        extension_created = True
        for row in checked["manifest"]["extensions"]:
            target = package_target / row["id"]
            _safe_copytree(root / "packages" / row["id"], target)
            if row.get("bundle_tree_sha256") and _tree_sha256(target) != row["bundle_tree_sha256"]:
                raise InstallError("COPIED_PACKAGE_TREE_SHA256_MISMATCH:%s" % row["id"])

        mnemon_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(native_source), str(native_target))
        native_created = True
        if os.name != "nt":
            native_target.chmod(native_target.stat().st_mode | 0o111)
        if _sha256(native_target) != native["sha256"]:
            raise InstallError("MNEMON_CLI_COPY_SHA256_MISMATCH")
        mnemon_version_output = _run([str(native_target), "--version"])
        if native["version"] not in mnemon_version_output:
            raise InstallError("MNEMON_CLI_VERSION_MISMATCH")

        env.update({
            "npm_config_offline": "true",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "PNPM_CONFIG_OFFLINE": "true",
            "COREPACK_ENABLE_NETWORK": "0",
            "MNEMON_CLI_PATH": str(native_target),
            "PATH": os.pathsep.join([str(mnemon_root), str(Path(node_bin).parent), env.get("PATH", "")]),
            "PFC_RC72_ECOSYSTEM_OFFLINE": "1",
        })
        for row in checked["manifest"]["extensions"]:
            package_path = package_target / row["id"]
            if row["id"] == "modlens":
                # ModLens is staged, not registered, until internal-only
                # provider configuration has been explicitly supplied.
                continue
            installed.append(row["package"])
            _run([dsh, "plugin", "--profile", profile, "add", "file:" + str(package_path)], env=env)
        listing = _run([dsh, "plugin", "--profile", profile, "list"], env=env)
        expected = [row["package"] for row in checked["manifest"]["extensions"] if row["id"] != "modlens"]
        missing = [name for name in expected if name not in listing]
        if missing:
            raise InstallError("DSH_PLUGIN_LIST_MISSING:" + ",".join(missing))

        policy_dir.mkdir(parents=True, exist_ok=True)
        if template_target.exists():
            raise InstallError("MODLENS_POLICY_TEMPLATE_ALREADY_EXISTS")
        shutil.copy2(str(template_source), str(template_target))
        template_created = True
        receipt = {
            "schema_version": "pfc.rc72.ecosystem-install-receipt.v1",
            "status": "INSTALLED_HOST_ACTIVATION_NOT_BANK_ACCEPTANCE",
            "platform": checked["platform"],
            "dsh_version": dsh_version,
            "node_version": node_version,
            "profile": profile,
            "rc72_source_commit": (rc72_home / "SOURCE_COMMIT").read_text(encoding="utf-8").strip(),
            "extensions": [
                {"id": row["id"], "package": row["package"], "version": row["version"],
                 "bundle_tree_sha256": row.get("bundle_tree_sha256"),
                 "installed": row["id"] != "modlens",
                 "activation_state": "staged_until_internal_endpoint_configured" if row["id"] == "modlens" else "installed"}
                for row in checked["manifest"]["extensions"]
            ],
            "mnemon_cli": {"path": str(native_target), "version": native["version"], "sha256": native["sha256"],
                           "version_output": mnemon_version_output.strip()},
            "modlens_policy_template_sha256": _sha256(template_target),
            "modlens_enabled": False,
            "bank_final": False,
        }
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_temp.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
        os.replace(str(receipt_temp), str(receipt_path))
        receipt_created = True
        return receipt
    except Exception:
        for package in reversed(installed):
            try:
                _run([dsh, "plugin", "--profile", profile, "remove", package], env=env)
            except Exception:
                pass
        if receipt_temp.exists():
            receipt_temp.unlink()
        if receipt_created and receipt_path.exists():
            receipt_path.unlink()
        if template_created and template_target.exists():
            template_target.unlink()
        if extension_created and extension_root.exists():
            shutil.rmtree(str(extension_root), ignore_errors=True)
        if native_created and native_target.exists() and _sha256(native_target) == native["sha256"]:
            native_target.unlink()
        try:
            mnemon_root.rmdir()
        except OSError:
            pass
        raise


def health(rc72_home, *, dsh_bin=None, profile=PROFILE_DEFAULT):
    rc72_home = Path(rc72_home).expanduser().resolve()
    receipt_path = _receipt_path(rc72_home)
    if not receipt_path.is_file():
        raise InstallError("ECOSYSTEM_INSTALL_RECEIPT_MISSING")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("profile") != profile or not re.fullmatch(r"rc7\.2-[a-z0-9][a-z0-9._-]{0,40}", profile):
        raise InstallError("ECOSYSTEM_PROFILE_RECEIPT_MISMATCH")
    dsh = _resolve_dsh(dsh_bin)
    native_path = Path(receipt["mnemon_cli"]["path"])
    env = os.environ.copy()
    env["MNEMON_CLI_PATH"] = str(native_path)
    env["PATH"] = str(native_path.parent) + os.pathsep + env.get("PATH", "")
    listing = _run([dsh, "plugin", "--profile", profile, "list"], env=env)
    active = [row for row in receipt["extensions"] if row.get("installed")]
    staged = [row for row in receipt["extensions"] if not row.get("installed")]
    missing = [row["package"] for row in active if row["package"] not in listing]
    if missing:
        raise InstallError("ECOSYSTEM_HEALTH_PLUGIN_MISSING:" + ",".join(missing))
    package_root = rc72_home / "workspace-template/runtime/dsh-ecosystem-extensions/packages"
    for row in receipt["extensions"]:
        staged_path = package_root / row["id"]
        if not staged_path.is_dir() or (row.get("bundle_tree_sha256") and _tree_sha256(staged_path) != row["bundle_tree_sha256"]):
            raise InstallError("ECOSYSTEM_HEALTH_STAGED_PACKAGE_MISMATCH:" + row["id"])
    if not native_path.is_file() or _sha256(native_path) != receipt["mnemon_cli"]["sha256"]:
        raise InstallError("MNEMON_CLI_HEALTH_SHA256_MISMATCH")
    native_version = _run([str(native_path), "--version"])
    if receipt["mnemon_cli"]["version"] not in native_version:
        raise InstallError("MNEMON_CLI_HEALTH_VERSION_MISMATCH")
    if receipt.get("modlens_enabled"):
        node_bin = _resolve_node(rc72_home)
        node_version = _require_node(node_bin, (22, 19, 0), "MODLENS")
        config_path = Path.home() / ".modlens" / "config.json"
        if not config_path.is_file():
            raise InstallError("MODLENS_INTERNAL_CONFIG_MISSING")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        openai = (config.get("providers") or {}).get("openai") or {}
        parsed = urlparse(openai.get("baseUrl") or "")
        host = (parsed.hostname or "").lower()
        if (config.get("provider") != "openai" or parsed.scheme != "https"
                or openai.get("proxy") != ""
                or host != receipt.get("modlens_internal_endpoint_host")):
            raise InstallError("MODLENS_INTERNAL_ENDPOINT_HEALTH_MISMATCH")
        reuse = config.get("reuse") or {}
        if any(reuse.get(key) is not False for key in ("claude", "codex", "opencode", "pi", "grok")):
            raise InstallError("MODLENS_EXTERNAL_CREDENTIAL_REUSE_MUST_BE_DISABLED")
    else:
        node_version = receipt.get("node_version")
    return {
        "status": "PASS",
        "profile": profile,
        "installed_plugins": len(active),
        "staged_plugins": [row["package"] for row in staged],
        "node_version": node_version,
        "mnemon_cli": str(native_path),
        "modlens_enabled": receipt.get("modlens_enabled", False),
    }


def uninstall(rc72_home, *, dsh_bin=None, profile=PROFILE_DEFAULT):
    rc72_home = Path(rc72_home).expanduser().resolve()
    receipt_path = _receipt_path(rc72_home)
    if not receipt_path.is_file():
        raise InstallError("ECOSYSTEM_INSTALL_RECEIPT_MISSING")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("profile") != profile or not re.fullmatch(r"rc7\.2-[a-z0-9][a-z0-9._-]{0,40}", profile):
        raise InstallError("PROTECTED_OR_NON_RC72_PROFILE_FORBIDDEN")
    package_root = rc72_home / "workspace-template/runtime/dsh-ecosystem-extensions/packages"
    for row in receipt["extensions"]:
        staged = package_root / row["id"]
        if not staged.is_dir() or (row.get("bundle_tree_sha256") and _tree_sha256(staged) != row["bundle_tree_sha256"]):
            raise InstallError("REFUSE_UNINSTALL_TAMPERED_PACKAGE:" + row["id"])
    native_path = Path(receipt["mnemon_cli"]["path"])
    if not native_path.is_file() or _sha256(native_path) != receipt["mnemon_cli"]["sha256"]:
        raise InstallError("REFUSE_UNINSTALL_TAMPERED_OR_MISSING_MNEMON_CLI")
    dsh = _resolve_dsh(dsh_bin)
    env = os.environ.copy()
    env["MNEMON_CLI_PATH"] = str(native_path)
    env["PATH"] = str(native_path.parent) + os.pathsep + env.get("PATH", "")
    for row in reversed(receipt["extensions"]):
        if row.get("installed"):
            _run([dsh, "plugin", "--profile", profile, "remove", row["package"]], env=env)
    native_path.unlink()
    try:
        native_path.parent.rmdir()
    except OSError:
        pass
    extension_root = rc72_home / "workspace-template" / "runtime" / "dsh-ecosystem-extensions"
    shutil.rmtree(str(extension_root))
    template_path = rc72_home / "runtime-state/ecosystem-extensions/modlens-config.bank-template.json"
    if template_path.is_file() and _sha256(template_path) == receipt.get("modlens_policy_template_sha256"):
        template_path.unlink()
    receipt_path.unlink()
    return {"status": "UNINSTALLED", "profile": profile, "memory_data_preserved": True}


def configure_modlens(*, internal_host_suffix, replace_existing=False):
    suffix = (internal_host_suffix or "").strip().lower().lstrip(".")
    if not suffix:
        raise InstallError("INTERNAL_HOST_SUFFIX_REQUIRED")
    base_url = input("Bank internal OpenAI-compatible multimodal endpoint URL: ").strip()
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or not (host == suffix or host.endswith("." + suffix)):
        raise InstallError("MODLENS_ENDPOINT_NOT_IN_APPROVED_INTERNAL_SUFFIX")
    model = input("Internal multimodal model name: ").strip()
    if not model:
        raise InstallError("MODLENS_MODEL_REQUIRED")
    api_key = getpass.getpass("Internal endpoint API key (hidden input): ").strip()
    if not api_key:
        raise InstallError("MODLENS_API_KEY_REQUIRED")
    target = Path.home() / ".modlens" / "config.json"
    if target.exists() and not replace_existing:
        raise InstallError("MODLENS_CONFIG_EXISTS_USE_BACKUP_AND_EXPLICIT_REPLACE")
    if target.exists():
        backup = target.with_name("config.json.backup-" + datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"))
        shutil.copy2(str(target), str(backup))
    target.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "provider": "openai",
        "providers": {"openai": {"baseUrl": base_url, "apiKey": api_key, "model": model, "proxy": ""}},
        "reuse": {"claude": False, "codex": False, "opencode": False, "pi": False, "grok": False},
        "guards": {"denyWhenUnknown": True},
    }
    target.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return {"status": "CONFIGURED_INTERNAL_ENDPOINT_ONLY", "config_path": str(target), "host": host, "api_key_written": True}


def enable_modlens(rc72_home, *, internal_host_suffix, dsh_bin=None, profile=PROFILE_DEFAULT):
    suffix = (internal_host_suffix or "").strip().lower().lstrip(".")
    config_path = Path.home() / ".modlens" / "config.json"
    if not config_path.is_file():
        raise InstallError("MODLENS_INTERNAL_CONFIG_MISSING")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    openai = (config.get("providers") or {}).get("openai") or {}
    parsed = urlparse(openai.get("baseUrl") or "")
    host = (parsed.hostname or "").lower()
    if config.get("provider") != "openai" or not openai.get("apiKey") or not openai.get("model"):
        raise InstallError("MODLENS_INTERNAL_PROVIDER_NOT_CONFIGURED")
    if parsed.scheme != "https" or openai.get("proxy") != "":
        raise InstallError("MODLENS_ENDPOINT_MUST_USE_DIRECT_HTTPS")
    if not suffix or not (host == suffix or host.endswith("." + suffix)):
        raise InstallError("MODLENS_ENDPOINT_NOT_IN_APPROVED_INTERNAL_SUFFIX")
    reuse = config.get("reuse") or {}
    required_reuse_grants = ("claude", "codex", "opencode", "pi", "grok")
    if any(reuse.get(key) is not False for key in required_reuse_grants):
        raise InstallError("MODLENS_EXTERNAL_CREDENTIAL_REUSE_MUST_BE_DISABLED")
    if not (config.get("guards") or {}).get("denyWhenUnknown"):
        raise InstallError("MODLENS_DENY_UNKNOWN_GUARD_REQUIRED")
    if not re.fullmatch(r"rc7\.2-[a-z0-9][a-z0-9._-]{0,40}", profile):
        raise InstallError("PROTECTED_OR_NON_RC72_PROFILE_FORBIDDEN")

    rc72_home = Path(rc72_home).expanduser().resolve()
    receipt_path = _receipt_path(rc72_home)
    if not receipt_path.is_file():
        raise InstallError("ECOSYSTEM_INSTALL_RECEIPT_MISSING")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    row = next((item for item in receipt["extensions"] if item["id"] == "modlens"), None)
    if row is None:
        raise InstallError("MODLENS_PACKAGE_NOT_STAGED")
    if row.get("installed"):
        return {"status": "ALREADY_ENABLED", "host": host}
    package_path = rc72_home / "workspace-template/runtime/dsh-ecosystem-extensions/packages/modlens"
    if not package_path.is_dir() or _tree_sha256(package_path) != row["bundle_tree_sha256"]:
        raise InstallError("MODLENS_STAGED_PACKAGE_SHA256_MISMATCH")
    node_bin = _resolve_node(rc72_home)
    node_version = _require_node(node_bin, (22, 19, 0), "MODLENS")
    dsh = _resolve_dsh(dsh_bin)
    version = _dsh_version(_run([dsh, "--version"]))
    _check_dsh_compatibility(version)
    native_path = Path(receipt["mnemon_cli"]["path"])
    env = os.environ.copy()
    env.update({
        "npm_config_offline": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "PNPM_CONFIG_OFFLINE": "true",
        "COREPACK_ENABLE_NETWORK": "0",
        "MNEMON_CLI_PATH": str(native_path),
        "PATH": os.pathsep.join([str(native_path.parent), str(Path(node_bin).parent), env.get("PATH", "")]),
        "PFC_RC72_ECOSYSTEM_OFFLINE": "1",
    })
    registered = False
    try:
        _run([dsh, "plugin", "--profile", profile, "add", "file:" + str(package_path)], env=env)
        registered = True
        listing = _run([dsh, "plugin", "--profile", profile, "list"], env=env)
        if row["package"] not in listing:
            raise InstallError("MODLENS_PLUGIN_NOT_VISIBLE_AFTER_ENABLE")
        row["installed"] = True
        row["activation_state"] = "enabled_internal_endpoint_only"
        receipt["modlens_enabled"] = True
        receipt["modlens_internal_endpoint_host"] = host
        receipt["dsh_version"] = version
        receipt["node_version"] = node_version
        temp = receipt_path.with_name(receipt_path.name + ".tmp")
        temp.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(str(temp), str(receipt_path))
        return {"status": "MODLENS_ENABLED_INTERNAL_ENDPOINT_ONLY", "host": host, "restart_dsh_required": True}
    except Exception:
        if registered:
            try:
                _run([dsh, "plugin", "--profile", profile, "remove", row["package"]], env=env)
            except Exception:
                pass
        raise



def main(argv=None):
    parser = argparse.ArgumentParser(description="RC7.2 offline DSH ecosystem installer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    ins = sub.add_parser("install")
    ins.add_argument("--rc72-home", required=True)
    ins.add_argument("--dsh-bin")
    ins.add_argument("--profile", default=PROFILE_DEFAULT)
    ins.add_argument("--bundle-root")
    un = sub.add_parser("uninstall")
    un.add_argument("--rc72-home", required=True)
    un.add_argument("--dsh-bin")
    un.add_argument("--profile", default=PROFILE_DEFAULT)
    he = sub.add_parser("health")
    he.add_argument("--rc72-home", required=True)
    he.add_argument("--dsh-bin")
    he.add_argument("--profile", default=PROFILE_DEFAULT)
    cfg = sub.add_parser("configure-modlens")
    cfg.add_argument("--internal-host-suffix", required=True)
    cfg.add_argument("--replace-existing", action="store_true")
    en = sub.add_parser("enable-modlens")
    en.add_argument("--rc72-home", required=True)
    en.add_argument("--internal-host-suffix", required=True)
    en.add_argument("--dsh-bin")
    en.add_argument("--profile", default=PROFILE_DEFAULT)
    args = parser.parse_args(argv)
    if args.command == "verify":
        result = verify_bundle()
    elif args.command == "install":
        result = install(args.bundle_root, rc72_home=args.rc72_home, dsh_bin=args.dsh_bin, profile=args.profile)
    elif args.command == "uninstall":
        result = uninstall(args.rc72_home, dsh_bin=args.dsh_bin, profile=args.profile)
    elif args.command == "health":
        result = health(args.rc72_home, dsh_bin=args.dsh_bin, profile=args.profile)
    elif args.command == "configure-modlens":
        result = configure_modlens(internal_host_suffix=args.internal_host_suffix, replace_existing=args.replace_existing)
    else:
        result = enable_modlens(args.rc72_home, internal_host_suffix=args.internal_host_suffix,
                                dsh_bin=args.dsh_bin, profile=args.profile)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as exc:
        print("[RC7.2-ECOSYSTEM] " + str(exc), file=sys.stderr)
        raise SystemExit(2)
