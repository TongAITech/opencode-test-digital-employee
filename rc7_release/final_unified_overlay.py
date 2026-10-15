from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


FINAL_PACKAGE_PREFIX = "PFC-AITest-RC7-FINAL-UNIFIED-BANK-WIN10"
POLICY_SCHEMA = "aitest.offline-runtime-policy.v3"
INVENTORY_SCHEMA = "pfc.aitest.rc7.full-capability-inventory.v1"

PAYLOAD_DIRS = (
    ("PFC_RC7_BUILD_NODE_DIR", "workspace-template/runtime/node"),
    ("PFC_RC7_BUILD_DSH_PLUGINS_DIR", "workspace-template/runtime/dsh-plugins"),
    ("PFC_RC7_BUILD_EXECUTION_NODE_DIR", "workspace-template/runtime/node-execution"),
    ("PFC_RC7_BUILD_BROWSER_SKILL_DIR", "workspace-template/runtime/browser/browserskill"),
    ("PFC_RC7_BUILD_BROWSER_SKILL_EXTENSION_DIR", "workspace-template/runtime/browser/browserskill-extension"),
    ("PFC_RC7_BUILD_JDK_DIR", "workspace-template/runtime/java"),
    ("PFC_RC7_BUILD_MAVEN_DIR", "workspace-template/runtime/maven"),
    ("PFC_RC7_BUILD_M2_DIR", "workspace-template/runtime/maven-repository"),
    ("PFC_RC7_BUILD_ALLURE_DIR", "workspace-template/runtime/allure"),
    ("PFC_RC7_BUILD_K6_DIR", "workspace-template/runtime/k6"),
    ("PFC_RC7_BUILD_ZAP_DIR", "workspace-template/runtime/zap"),
    ("PFC_RC7_BUILD_RIPGREP_DIR", "workspace-template/runtime/ripgrep"),
)

REQUIRED_DSH_PACKAGES = (
    "dsh-routing-suite",
    "@wxg-prc-cpg/browser-skill-dsh-plugin",
    "dsh-context",
    "dsh-plugin-bridge",
    "@nanmicoder/dsh-agent-teams",
    "@perrylink/dsh-plugin-doctor",
)
OPTIONAL_DSH_PACKAGES = (
    "dsh-vision-router",
    "dsh-plugin-anydoc",
    "dsh-memento",
    "dsh-error-handling",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(str(target))
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(item), str(dest))


def package_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "CHECKSUMS.sha256":
            continue
        if "__pycache__" in path.parts or path.suffix.lower() in (".pyc", ".pyo"):
            continue
        yield path


def npm_package_path(vendor_root: Path, package: str) -> Path:
    if package.startswith("@"):
        scope, name = package.split("/", 1)
        return vendor_root / "node_modules" / scope / name
    return vendor_root / "node_modules" / package


def present(path: Path) -> bool:
    return path.is_file() or path.is_dir()


def cap(cap_id: str, status: str, tier: str, path: Optional[str] = None, **extra: object) -> Dict[str, object]:
    out: Dict[str, object] = {"id": cap_id, "status": status, "tier": tier}
    if path:
        out["path"] = path
    out.update(extra)
    return out


def build_inventory(root: Path, source_commit: str) -> Dict[str, object]:
    runtime = root / "workspace-template" / "runtime"
    vendor = runtime / "dsh-plugins"
    exec_node = runtime / "node-execution"
    py = runtime / "python" / "python.exe"
    chrome = runtime / "browser" / "chrome-win64" / "chrome.exe"
    bsk_candidates = list((runtime / "browser" / "browserskill").rglob("bsk.exe")) if (runtime / "browser" / "browserskill").exists() else []
    maven = runtime / "maven" / "bin" / "mvn.cmd"
    java = runtime / "java" / "bin" / "java.exe"
    javac = runtime / "java" / "bin" / "javac.exe"
    k6 = runtime / "k6" / "k6.exe"
    allure = runtime / "allure" / "bin" / "allure.bat"
    zap = runtime / "zap" / "zap.bat"
    rg_candidates = list((runtime / "ripgrep").rglob("rg.exe")) if (runtime / "ripgrep").exists() else []
    gitnexus_candidates = list((exec_node / "node_modules" / ".bin").glob("gitnexus*.cmd")) if exec_node.exists() else []
    playwright_pkg = exec_node / "node_modules" / "playwright" / "package.json"
    codegraph = runtime / "code-intelligence" / "codegraph" / "codegraph-server-win32-x64.exe"

    capabilities: List[Dict[str, object]] = [
        cap("R1_EVENT_STREAM", "BUNDLED_ENABLED", "CORE", "state/rc7-r1.jsonl", truth=True),
        cap("RC7_CONTROL_PLANE", "BUNDLED_ENABLED", "CORE", "rc7_runtime"),
        cap("DSH_HOST", "BANK_HOST_CAPABILITY", "CORE", field_binding_required=True, exact_version_pin=False),
        cap("DSH_MCP_PATCH", "BUNDLED_ENABLED", "CORE", "rc7_release/dsh.py", launch_mode="--patch"),
        cap("PYTHON_RUNTIME", "BUNDLED_ENABLED" if py.is_file() else "MISSING", "CORE", str(py.relative_to(root)).replace("\\", "/")),
        cap("PYTEST", "BUNDLED_ENABLED" if py.is_file() else "MISSING", "L1_L5", "workspace-template/runtime/python"),
        cap("CODEGRAPH", "BUNDLED_ENABLED" if codegraph.is_file() else "MISSING", "CODE", "workspace-template/runtime/code-intelligence/codegraph"),
        cap("GITNEXUS", "BUNDLED_OPTIONAL" if gitnexus_candidates else "OPTIONAL_NOT_RESOLVED", "CODE", str(gitnexus_candidates[0].relative_to(root)).replace("\\", "/") if gitnexus_candidates else None, authority="SECONDARY_PROVIDER_NOT_TRUTH"),
        cap("CHROME_CONTROLLED", "BUNDLED_ENABLED" if chrome.is_file() else "MISSING", "L4_L5", str(chrome.relative_to(root)).replace("\\", "/")),
        cap("PLAYWRIGHT_NODE", "BUNDLED_ENABLED" if playwright_pkg.is_file() else "MISSING", "L4_L5", str(playwright_pkg.relative_to(root)).replace("\\", "/")),
        cap("BROWSERSKILL_CLI", "BUNDLED_ENABLED" if bsk_candidates else "MISSING", "L4_L5", str(bsk_candidates[0].relative_to(root)).replace("\\", "/") if bsk_candidates else None),
        cap("BROWSERSKILL_EXTENSION", "BUNDLED_ENABLED" if (runtime / "browser" / "browserskill-extension").exists() else "MISSING", "L4_L5", "workspace-template/runtime/browser/browserskill-extension"),
        cap("LOCAL_OCR", "BUNDLED_ENABLED" if (runtime / "python" / "Lib" / "site-packages").exists() else "MISSING", "VISION", "workspace-template/runtime/python", remote_image_upload=False),
        cap("LOCAL_CV", "BUNDLED_ENABLED" if (runtime / "python" / "Lib" / "site-packages").exists() else "MISSING", "VISION", "workspace-template/runtime/python", remote_image_upload=False),
        cap("BANK_VLM", "BANK_HOST_OPTIONAL", "VISION", enabled_by_default=False, remote_public_forbidden=True),
        cap("JDK", "BUNDLED_ENABLED" if java.is_file() and javac.is_file() else "MISSING", "L1_L2", "workspace-template/runtime/java"),
        cap("MAVEN", "BUNDLED_ENABLED" if maven.is_file() else "MISSING", "L1_L2", "workspace-template/runtime/maven"),
        cap("MAVEN_BOOTSTRAP_REPOSITORY", "BUNDLED_ENABLED" if (runtime / "maven-repository").exists() else "MISSING", "L1_L2", "workspace-template/runtime/maven-repository", project_dependencies="BANK_MIRROR_FIRST"),
        cap("ALLURE_CLI", "BUNDLED_ENABLED" if allure.is_file() else "MISSING", "REPORT", "workspace-template/runtime/allure"),
        cap("K6", "BUNDLED_ENABLED" if k6.is_file() else "MISSING", "L6", "workspace-template/runtime/k6"),
        cap("ZAP", "BUNDLED_ENABLED" if zap.is_file() else "MISSING", "L7", "workspace-template/runtime/zap"),
        cap("RIPGREP", "BUNDLED_ENABLED" if rg_candidates else "MISSING", "CODE_FALLBACK", str(rg_candidates[0].relative_to(root)).replace("\\", "/") if rg_candidates else None),
        cap("FOURA_ADAPTER", "BUNDLED_ADAPTER_BANK_BINDING_REQUIRED", "BANK", "rc7_release/bank_binding.py", dynamic_challenges="HUMAN_OR_BANK_APPROVED_PROVIDER"),
        cap("CAT_ADAPTER", "BUNDLED_ADAPTER_BANK_BINDING_REQUIRED", "BANK", "rc7_release/bank_binding.py"),
        cap("TDSQL_ADAPTER", "BUNDLED_ADAPTER_BANK_BINDING_REQUIRED", "BANK", "rc7_release/bank_binding.py", write_gate="HUMAN_CONFIRMATION"),
        cap("OCEANBASE_ADAPTER", "BUNDLED_ADAPTER_BANK_BINDING_REQUIRED", "BANK", "rc7_release/bank_binding.py", write_gate="HUMAN_CONFIRMATION"),
        cap("TIDB_ADAPTER", "BUNDLED_ADAPTER_BANK_BINDING_REQUIRED", "BANK", "rc7_release/bank_binding.py", write_gate="HUMAN_CONFIRMATION"),
        cap("BANK_MAVEN_MIRROR", "BANK_HOST_BINDING_REQUIRED", "L1_L2", "workspace-template/config/maven/settings-template.xml"),
        cap("BANK_PIP_MIRROR", "BANK_HOST_BINDING_REQUIRED", "EXTENSION", "workspace-template/config/pip/pip.ini.template"),
        cap("FAILURE_DIAGNOSIS", "BUNDLED_ENABLED", "CLOSED_LOOP", "rc7_runtime/diagnosis.py"),
        cap("MISSION_REPORT_BUILDER", "BUNDLED_ENABLED", "REPORT", "rc7_runtime/reporting.py"),
        cap("ADMIN_PLATFORM", "BUNDLED_ENABLED", "UI", "rc7_admin"),
        cap("SESSION_HANDOFF", "BUNDLED_ENABLED", "CONTROL", "rc7_runtime/bank_mission.py", truth="R1_EVENT_STREAM"),
    ]

    for package in REQUIRED_DSH_PACKAGES:
        p = npm_package_path(vendor, package)
        capabilities.append(cap("DSH_PLUGIN:%s" % package, "BUNDLED_CAPABILITY_GATED" if (p / "package.json").is_file() else "MISSING", "PLUGIN", str(p.relative_to(root)).replace("\\", "/") if p.exists() else None, bank_host_compatibility_probe_required=True))
    for package in OPTIONAL_DSH_PACKAGES:
        p = npm_package_path(vendor, package)
        status = "BUNDLED_DISABLED_BY_DEFAULT" if (p / "package.json").is_file() else "OPTIONAL_NOT_RESOLVED"
        extra = {"bank_host_compatibility_probe_required": True}
        if package == "dsh-vision-router":
            extra.update({"remote_provider_forbidden_by_default": True, "local_only_policy": True})
        capabilities.append(cap("DSH_PLUGIN:%s" % package, status, "PLUGIN_OPTIONAL", str(p.relative_to(root)).replace("\\", "/") if p.exists() else None, **extra))

    layers = {
        "L1": {"worker": "pfc-l1-test-execution", "tools": ["JDK", "MAVEN", "PYTEST"], "oracle": "JUnit/Pytest+coverage"},
        "L2": {"worker": "pfc-l2-test-execution", "tools": ["MAVEN", "PYTEST", "TDSQL_ADAPTER", "OCEANBASE_ADAPTER", "TIDB_ADAPTER"], "oracle": "component+DB"},
        "L3": {"worker": "pfc-l3-test-execution", "tools": ["PYTEST", "FOURA_ADAPTER", "CAT_ADAPTER"], "oracle": "API+business+DB/CAT"},
        "L4": {"worker": "pfc-l4-test-execution", "tools": ["PLAYWRIGHT_NODE", "CHROME_CONTROLLED", "BROWSERSKILL_CLI", "LOCAL_OCR", "LOCAL_CV"], "oracle": "DOM+a11y+network+visual"},
        "L5": {"worker": "pfc-l5-test-execution", "tools": ["PLAYWRIGHT_NODE", "FOURA_ADAPTER", "CAT_ADAPTER", "TDSQL_ADAPTER"], "oracle": "cross-channel E2E"},
        "L6": {"worker": "pfc-l6-test-execution", "tools": ["K6"], "oracle": "threshold+metrics"},
        "L7": {"worker": "pfc-l7-test-execution", "tools": ["ZAP", "PLAYWRIGHT_NODE"], "oracle": "security+authorization"},
    }
    return {
        "schema_version": INVENTORY_SCHEMA,
        "source_commit": source_commit,
        "durable_truth": "R1_EVENT_STREAM",
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "runtime_policy": POLICY_SCHEMA,
        "remote_public_image_upload": "FORBIDDEN",
        "mineru_server_required": False,
        "director_domain_execution": "FORBIDDEN",
        "independent_re_evaluation_required_for_pass": True,
        "real_bank_mission": "HOLD_FIELD_EVIDENCE_REQUIRED",
        "capabilities": capabilities,
        "execution_layers": layers,
        "mandatory_field_bindings": ["DSH_HOST", "4A", "CAT", "TDSQL/OCEANBASE/TIDB", "BANK_MAVEN_MIRROR", "BANK_PIP_MIRROR"],
    }


def write_config_templates(root: Path) -> None:
    maven = root / "workspace-template" / "config" / "maven" / "settings-template.xml"
    maven.parent.mkdir(parents=True, exist_ok=True)
    maven.write_text("""<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<settings xmlns=\"http://maven.apache.org/SETTINGS/1.2.0\">\n  <mirrors>\n    <mirror><id>bank-mirror</id><mirrorOf>*</mirrorOf><url>${env.PFC_MAVEN_MIRROR_URL}</url></mirror>\n  </mirrors>\n</settings>\n""", encoding="utf-8")
    pip = root / "workspace-template" / "config" / "pip" / "pip.ini.template"
    pip.parent.mkdir(parents=True, exist_ok=True)
    pip.write_text("[global]\nindex-url = ${PFC_PIP_INDEX_URL}\ndisable-pip-version-check = true\n", encoding="utf-8")
    bank = root / "workspace-template" / "config" / "bank" / "bindings.example.json"
    bank.parent.mkdir(parents=True, exist_ok=True)
    bank.write_text(json.dumps({
        "foura_script": "${PFC_4A_SCRIPT}",
        "cat_config": "${PFC_CAT_CONFIG}",
        "tdsql_dsn": "${PFC_TDSQL_DSN}",
        "oceanbase_dsn": "${PFC_OCEANBASE_DSN}",
        "tidb_dsn": "${PFC_TIDB_DSN}",
        "maven_mirror_url": "${PFC_MAVEN_MIRROR_URL}",
        "pip_index_url": "${PFC_PIP_INDEX_URL}",
        "secrets": "DO_NOT_BUNDLE_REAL_SECRETS"
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_manifest_and_checksums(root: Path, inventory: Dict[str, object]) -> None:
    manifest_path = root / "PACKAGE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "runtime_policy_schema": POLICY_SCHEMA,
        "final_unified_turnkey": True,
        "full_capability_inventory": "FULL-CAPABILITY-INVENTORY.json",
        "field_bindings_required": True,
        "real_mission_pass": False,
        "bank_field_pass": False,
    })
    manifest["unified_capability_summary"] = {
        "count": len(inventory["capabilities"]),
        "execution_layers": sorted(inventory["execution_layers"].keys()),
        "real_bank_mission": inventory["real_bank_mission"],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    lines: List[str] = []
    for path in package_files(root):
        rel = path.relative_to(root).as_posix()
        lines.append("%s  %s" % (sha256_file(path), rel))
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def overlay(package_root: Path, source_commit: str) -> Dict[str, object]:
    copied: Dict[str, str] = {}
    for env_name, target_rel in PAYLOAD_DIRS:
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        source = Path(value).resolve()
        if not source.is_dir():
            raise RuntimeError("PAYLOAD_DIR_MISSING:%s:%s" % (env_name, source))
        target = package_root / target_rel
        copy_tree(source, target)
        copied[env_name] = target_rel

    write_config_templates(package_root)
    inventory = build_inventory(package_root, source_commit)
    inventory_path = package_root / "FULL-CAPABILITY-INVENTORY.json"
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    update_manifest_and_checksums(package_root, inventory)
    return {"status": "PASS", "copied": copied, "inventory": inventory}


def archive(package_root: Path, output_dir: Path, source_commit: str) -> Tuple[Path, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / ("%s-%s.zip" % (FINAL_PACKAGE_PREFIX, source_commit[:12]))
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(str(target), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                zf.write(str(path), (Path(package_root.name) / path.relative_to(package_root)).as_posix())
    digest = sha256_file(target)
    Path(str(target) + ".sha256").write_text("%s  %s\n" % (digest, target.name), encoding="utf-8")
    return target, digest


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--package-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--source-commit", required=True)
    args = p.parse_args(argv)
    root = Path(args.package_root).resolve()
    result = overlay(root, args.source_commit)
    zip_path, digest = archive(root, Path(args.output).resolve(), args.source_commit)
    print(json.dumps({"status": "PASS", "package_root": str(root), "zip": str(zip_path), "sha256": digest, "copied": result["copied"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
