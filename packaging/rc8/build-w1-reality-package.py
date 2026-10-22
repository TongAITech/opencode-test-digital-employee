"""Build a complete standalone RC8 bank Reality validation package.

Always emits a full replacement package, never a patch. Public internet is not
used by the package at runtime; bank-local Python/Git/Java/Maven/CodeGraph/DSH
are capability-discovered external prerequisites for this Reality stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple


RUNTIME_FILES = (
    "rc8_runtime/__init__.py",
    "rc8_runtime/contracts.py",
    "rc8_runtime/artifacts.py",
    "rc8_runtime/r1_runtime.py",
    "rc8_runtime/governance.py",
    "rc8_runtime/coverage.py",
    "rc8_runtime/mission_graph.py",
    "rc8_center/__init__.py",
    "rc8_center/__main__.py",
    "rc8_center/control_plane.py",
    "rc8_center/http_server.py",
    "rc8_center/artifacts.py",
    "rc8_center/json_repository.py",
    "rc8_center/governance_repository.py",
    "rc8_center/coverage_repository.py",
    "rc8_center/governance_projection.py",
    "rc8_center/governance_event_projector.py",
    "rc8_center/mission_service.py",
    "rc8_center/product_api.py",
    "rc8_node/__init__.py",
    "rc8_node/__main__.py",
    "rc8_node/agent.py",
    "rc8_node/formal_agent.py",
    "rc8_node/capabilities.py",
    "rc8_node/execution.py",
    "rc8_node/jacoco.py",
    "rc8_node/execution_publish.py",
    "rc8_node/work_item_execution.py",
    "rc8_node/reality_maven.py",
    "rc8_node/codegraph.py",
    "rc8_node/reality_codegraph.py",
    "rc8_node/code_analysis.py",
    "rc8_node/code_analysis_semantic.py",
    "rc8_node/dsh_semantic_worker.py",
    "rc8_node/reality_code_analysis.py",
    "rc8_node/reality_code_analysis_auto.py",
    "governance/rc8-capability-contracts.json",
    "scripts/rc8_validate_governance.py",
    "packaging/rc8/rc8-center.sh",
    "packaging/rc8/rc8-node.sh",
    "packaging/rc8/rc8-maven-reality.sh",
    "packaging/rc8/rc8-codegraph-reality.sh",
    "packaging/rc8/rc8-code-analysis-reality.sh",
    "packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json",
    "docs/rc8/RC8-MASTER-CONTRACT.md",
    "docs/rc8/RC8-ARCHITECTURE-BASELINE.md",
    "docs/rc8/RC8-PRODUCT-BASELINE.md",
    "docs/rc8/RC8-CENTER-TECHNOLOGY-STACK-CONTRACT.md",
    "docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md",
    "docs/rc8/RC8-CODEGRAPH-REALITY-RUNBOOK.md",
    "docs/rc8/RC8-CODE-ANALYSIS-REALITY-RUNBOOK.md",
    "docs/rc8/RC8-NO-DISCOUNT-DELIVERY-CONTRACT.md",
    "docs/rc8/RC8-CAPABILITY-CLOSURE-MATRIX.md",
    "docs/rc8/RC8-L1-L7-ACCEPTANCE-CONTRACT.md",
    "docs/rc8/RC8-MISSION-GRAPH-CONTRACT.md",
    "docs/rc8/RC8-PRODUCT-PROJECTION-MAP.md",
    "docs/rc8/RC8-RC7-REGRESSION-CATALOG.md",
    "docs/rc8/RC8-WAVE-DELIVERY-GATES.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, args: List[str]) -> str:
    try:
        proc = subprocess.run(["git"] + args, cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except OSError:
        return ""
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip() if proc.returncode == 0 else ""


def _resolve_head(repo: Path) -> str:
    explicit = os.environ.get("RC8_BUILD_HEAD", "").strip()
    return explicit or _git(repo, ["rev-parse", "HEAD"]) or "UNKNOWN_HEAD"


def _copy_required(repo: Path, root: Path) -> List[str]:
    files: List[str] = []
    for relative in RUNTIME_FILES:
        source = repo / relative
        if not source.is_file():
            raise RuntimeError("PACKAGE_REQUIRED_FILE_MISSING:%s" % relative)
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
        files.append(relative)
    return files


def _write_config(root: Path) -> str:
    relative = "config/reality.env.example"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Stable across full replacement packages.\n"
        "export RC8_CENTER_URL=http://127.0.0.1:4098\n"
        "export RC8_NODE_ID=office-pc-01\n"
        "export RC8_NODE_OPERATOR=test-user\n"
        "export RC8_NODE_STATE_DIR=\"$HOME/.rc8/node-state/office-pc-01\"\n"
        "export RC8_NODE_STATE=\"$RC8_NODE_STATE_DIR\"\n"
        "# Bank-local capabilities:\n"
        "# export RC8_MVN=/path/to/mvn\n"
        "# export RC8_MAVEN_REPO=/path/to/maven/repository\n"
        "# export RC8_CODEGRAPH_BIN=/path/to/codegraph.exe\n"
        "# export RC8_DSH_BIN=/path/to/dsh\n"
        "# export RC8_DSH_PATCH=/path/to/bank/headless/patch\n",
        encoding="utf-8",
    )
    return relative


def _write_readme(root: Path, head: str) -> str:
    relative = "README-行内验证.md"
    path = root / relative
    path.write_text(
        "# RC8 行内 Reality 验证完整包\n\n"
        "构建 HEAD: `%s`\n\n" % head
        + "这是完整替换包，不是补丁包。解压到新目录运行；Node identity/state 必须放在版本包之外。\n\n"
        "## 当前能力边界\n"
        "- Center / Node / WorkItem / R1 / Artifact Sync\n"
        "- Center Mission Graph / scope-aware Stage control\n"
        "- Maven/JUnit Tool Reality\n"
        "- JaCoCo 变更方法/行/分支覆盖 Actual（仅接受同一执行新鲜报告）\n"
        "- CodeGraph Tool Reality\n"
        "- Code Analysis 构建中的结构/语义链\n"
        "- No-Discount Governance + Mission Graph Runtime + durable governance projection\n"
        "- R1-first Governance Projector：运行事实必须先持久化 R1，Center Projection 可重放恢复\n"
        "- Product API: `/api/v1/test-runs/{id}/governance`（记录事实，不自行推导PASS）\n"
        "- FormalNodeAgent 已包含显式 WorkItem lease token 协议；DSH Session 不持有任务真相。\n"
        "- 正式 Center 技术栈为 FastAPI + PostgreSQL + Redis + Vue3/TypeScript/Vite + Nginx + Docker Compose；本包内 stdlib HTTP 仅是 W1 行内 Reality 最小协议适配器。\n\n"
        "重要：Tool Reality 不能提升为 L1/L1-L7/TestRun 充分度。先运行 `python scripts/rc8_validate_governance.py` 可核对当前机器声明。\n\n"
        "## 1. 校验与永久 Node state\n"
        "```bash\n"
        "sha256sum -c SHA256SUMS.txt\n"
        "python scripts/rc8_validate_governance.py\n"
        "export RC8_NODE_ID=office-pc-01\n"
        "export RC8_NODE_STATE_DIR=\"$HOME/.rc8/node-state/$RC8_NODE_ID\"\n"
        "export RC8_NODE_STATE=\"$RC8_NODE_STATE_DIR\"\n"
        "mkdir -p \"$RC8_NODE_STATE\"\n"
        "```\n\n"
        "如果旧包已注册该 Node，必须把已被 Center 接受的 `node-identity.json` 原样迁入永久目录，禁止重新生成。\n\n"
        "## 2. Center / Node\n"
        "```bash\n"
        "bash packaging/rc8/rc8-center.sh --check --state-dir ./runtime/rc8-center\n"
        "bash packaging/rc8/rc8-center.sh --host 127.0.0.1 --port 4098 --state-dir ./runtime/rc8-center\n"
        "bash packaging/rc8/rc8-node.sh --once --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\"\n"
        "```\n\n"
        "## 3. Maven/JUnit Reality\n"
        "```bash\n"
        "bash packaging/rc8/rc8-maven-reality.sh --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\" \\\n"
        "  --project-dir /d/PFC/bloan-prod-factory-cfg-center --maven mvn \\\n"
        "  --maven-repo /c/Users/<user>/.m2/repository --allow-online --require-pass\n"
        "```\n\n"
        "## 4. CodeGraph Reality\n"
        "```bash\n"
        "bash packaging/rc8/rc8-codegraph-reality.sh --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\" \\\n"
        "  --project-dir /d/PFC/bloan-prod-factory-cfg-center \\\n"
        "  --codegraph /path/to/codegraph-server-win32-x64.exe --base-ref HEAD~1 --head-ref HEAD --max-points 2\n"
        "```\n\n"
        "## 5. 自动 Code Analysis Reality\n"
        "```bash\n"
        "bash packaging/rc8/rc8-code-analysis-reality.sh --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\" \\\n"
        "  --project-dir /d/PFC/bloan-prod-factory-cfg-center \\\n"
        "  --codegraph /path/to/codegraph-server-win32-x64.exe \\\n"
        "  --dsh dsh --base-ref HEAD~1 --head-ref HEAD\n"
        "```\n\n"
        "完整 L1 闭环还必须继续完成覆盖缺口、delta test、targeted rerun、收敛和产品投影；不能以 JaCoCo 或 CodeGraph 单项成功替代。\n",
        encoding="utf-8",
    )
    return relative


def _write_manifest(root: Path, head: str, files: List[str]) -> str:
    relative = "PACKAGE-MANIFEST.json"
    payload: Dict[str, object] = {
        "schema_version": "rc8.bank-reality-package.v9",
        "package_type": "FULL_STANDALONE_REALITY_VALIDATION_PACKAGE",
        "patch_package": False,
        "git_head": head,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "public_internet_install_required": False,
        "formal_center_stack": {
            "backend": "FastAPI",
            "persistence": "PostgreSQL",
            "coordination": "Redis",
            "frontend": "Vue 3 + TypeScript + Vite",
            "web_edge": "Nginx",
            "deployment": "Docker Compose",
            "current_package_server_role": "W1_MINIMAL_PROTOCOL_ADAPTER_ONLY"
        },
        "included_runtime_capabilities": [
            "CENTER_NODE_CONTROL",
            "CENTER_MISSION_SERVICE",
            "R1_RUNTIME_TRUTH",
            "ARTIFACT_SYNC",
            "FORMAL_NODE_EXPLICIT_LEASE_PROTOCOL",
            "NO_DISCOUNT_GOVERNANCE",
            "MISSION_GRAPH_RUNTIME",
            "GOVERNANCE_DURABLE_PROJECTION",
            "COVERAGE_PROVENANCE",
            "R1_GOVERNANCE_REPLAY",
            "GOVERNANCE_PRODUCT_API",
            "MAVEN_JUNIT_REALITY",
            "JACOCO_CHANGED_SCOPE_REALITY",
            "CODEGRAPH_REALITY",
            "CODE_ANALYSIS_STRUCTURAL_LOOP",
            "DSH_SEMANTIC_WORKER",
            "CODE_ANALYSIS_AUTONOMOUS_REALITY",
        ],
        "external_bank_capabilities_expected": ["PYTHON_3_8_PLUS", "GIT", "JAVA_MAVEN", "CODEGRAPH", "DSH_HEADLESS"],
        "files": sorted(files),
        "truth_note": "Package completeness is not stage/layer/mission sufficiency. Formal Center W-A is CI-verified separately; Bank Reality and W-B L1 sufficiency remain unverified until their own evidence closes the gates.",
    }
    path = root / relative
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return relative


def _write_hashes(root: Path) -> Tuple[str, int]:
    relative = "SHA256SUMS.txt"
    rows: List[str] = []
    count = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel == relative:
            continue
        rows.append("%s  %s" % (_sha256(path), rel))
        count += 1
    (root / relative).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return relative, count


def _verify_python(root: Path) -> None:
    files = [str(path) for path in root.rglob("*.py")]
    proc = subprocess.run([sys.executable, "-m", "py_compile"] + files, cwd=str(root), check=False)
    if proc.returncode != 0:
        raise RuntimeError("PACKAGE_PYTHON_COMPILE_FAILED")
    for pycache in root.rglob("__pycache__"):
        shutil.rmtree(str(pycache), ignore_errors=True)


def _verify_runtime_imports(root: Path) -> None:
    code = (
        "from rc8_runtime import CoverageObservation, MissionGraphRuntime, MissionRuntimeState, ScopedStatusClaim; "
        "from rc8_center import CenterMissionService, CenterProductApplication, GovernanceEventProjector, GovernanceProjectionService, JsonFileCoverageRepository, JsonFileGovernanceRepository; "
        "from rc8_node import FormalNodeAgent; "
        "from rc8_node.jacoco import JaCoCoChangedScopeCollector; "
        "assert CoverageObservation and MissionGraphRuntime and MissionRuntimeState and ScopedStatusClaim; "
        "assert CenterMissionService and CenterProductApplication and GovernanceEventProjector and GovernanceProjectionService; "
        "assert JsonFileCoverageRepository and JsonFileGovernanceRepository and FormalNodeAgent and JaCoCoChangedScopeCollector; "
        "print('RC8_PACKAGE_RUNTIME_IMPORT_PASS')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError("PACKAGE_RUNTIME_IMPORT_FAILED:%s" % detail)

    governance = subprocess.run(
        [sys.executable, "scripts/rc8_validate_governance.py"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if governance.returncode != 0:
        detail = ((governance.stdout or b"") + (governance.stderr or b"")).decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError("PACKAGE_GOVERNANCE_VALIDATION_FAILED:%s" % detail)

    center_check = subprocess.run(
        [sys.executable, "-m", "rc8_center", "--check", "--state-dir", str(root / ".package-smoke-center")],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if center_check.returncode != 0:
        detail = ((center_check.stdout or b"") + (center_check.stderr or b"")).decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError("PACKAGE_CENTER_CHECK_FAILED:%s" % detail)
    shutil.rmtree(str(root / ".package-smoke-center"), ignore_errors=True)


def _zip_tree(root: Path, output_zip: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(output_zip), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(str(path), (Path(root.name) / path.relative_to(root)).as_posix())
    with zipfile.ZipFile(str(output_zip), "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("PACKAGE_ZIP_INTEGRITY_FAILED:%s" % bad)


def build(repo: Path, output_dir: Path) -> Dict[str, object]:
    head = _resolve_head(repo)
    short = head[:8] if head != "UNKNOWN_HEAD" else "unknown"
    package_name = "RC8-W1-REALITY-BANK-%s" % short
    output_zip = output_dir / (package_name + ".zip")
    with tempfile.TemporaryDirectory(prefix="rc8-reality-package-") as temp_dir:
        root = Path(temp_dir) / package_name
        root.mkdir(parents=True)
        files = _copy_required(repo, root)
        files.append(_write_config(root))
        files.append(_write_readme(root, head))
        files.append(_write_manifest(root, head, files))
        hashes_name, hashed_count = _write_hashes(root)
        files.append(hashes_name)
        _verify_python(root)
        _verify_runtime_imports(root)
        _zip_tree(root, output_zip)
    return {
        "status": "PACKAGE_BUILT",
        "package": str(output_zip),
        "package_name": package_name,
        "git_head": head,
        "zip_sha256": _sha256(output_zip),
        "zip_bytes": output_zip.stat().st_size,
        "hashed_files": hashed_count,
        "patch_package": False,
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Build complete RC8 bank Reality package")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(Path(args.repo).resolve(), Path(args.output_dir).resolve()), ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "PACKAGE_BUILD_FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())