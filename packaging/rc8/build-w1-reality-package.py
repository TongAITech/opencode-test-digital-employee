"""Build a complete standalone RC8 W1/W2 bank reality validation package.

This is deliberately a full replacement package, never a patch/hotfix. The
package contains the current Center/Node runtime needed to validate Maven/JUnit,
CodeGraph and evidence-backed Code Analysis against capabilities present in the
bank environment. No public-internet installation step is introduced.
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
    "rc8_center/__init__.py",
    "rc8_center/__main__.py",
    "rc8_center/control_plane.py",
    "rc8_center/http_server.py",
    "rc8_center/artifacts.py",
    "rc8_center/json_repository.py",
    "rc8_node/__init__.py",
    "rc8_node/__main__.py",
    "rc8_node/agent.py",
    "rc8_node/capabilities.py",
    "rc8_node/execution.py",
    "rc8_node/execution_publish.py",
    "rc8_node/work_item_execution.py",
    "rc8_node/reality_maven.py",
    "rc8_node/codegraph.py",
    "rc8_node/reality_codegraph.py",
    "rc8_node/code_analysis.py",
    "rc8_node/reality_code_analysis.py",
    "packaging/rc8/rc8-center.sh",
    "packaging/rc8/rc8-node.sh",
    "packaging/rc8/rc8-maven-reality.sh",
    "packaging/rc8/rc8-codegraph-reality.sh",
    "packaging/rc8/rc8-code-analysis-reality.sh",
    "packaging/rc8/RC7_OFFLINE_TOOLSET_MANIFEST.json",
    "docs/rc8/RC8-W1-SINGLE-NODE-VERTICAL-SLICE.md",
    "docs/rc8/RC8-CODEGRAPH-REALITY-RUNBOOK.md",
    "docs/rc8/RC8-CODE-ANALYSIS-REALITY-RUNBOOK.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, args: List[str]) -> str:
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip()


def _resolve_head(repo: Path) -> str:
    explicit = os.environ.get("RC8_BUILD_HEAD", "").strip()
    if explicit:
        return explicit
    head = _git(repo, ["rev-parse", "HEAD"])
    return head or "UNKNOWN_HEAD"


def _copy_required(repo: Path, package_root: Path) -> List[str]:
    copied: List[str] = []
    for relative in RUNTIME_FILES:
        source = repo / relative
        if not source.is_file():
            raise RuntimeError("PACKAGE_REQUIRED_FILE_MISSING:%s" % relative)
        target = package_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source), str(target))
        copied.append(relative)
    return copied


def _write_config(package_root: Path) -> str:
    relative = "config/reality.env.example"
    path = package_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Stable values shared by all replacement package versions.\n"
        "export RC8_CENTER_URL=http://127.0.0.1:4098\n"
        "export RC8_NODE_ID=office-pc-01\n"
        "export RC8_NODE_OPERATOR=test-user\n"
        "# IMPORTANT: node identity/state must live OUTSIDE the version package.\n"
        "export RC8_NODE_STATE_DIR=\"$HOME/.rc8/node-state/office-pc-01\"\n"
        "export RC8_NODE_STATE=\"$RC8_NODE_STATE_DIR\"\n"
        "# Optional bank-local tools:\n"
        "# export RC8_MVN=/path/to/mvn\n"
        "# export RC8_MAVEN_REPO=/path/to/maven/repository\n"
        "# export RC8_CODEGRAPH_BIN=/path/to/codegraph\n",
        encoding="utf-8",
    )
    return relative


def _write_readme(package_root: Path, head: str) -> str:
    relative = "README-行内验证.md"
    path = package_root / relative
    path.write_text(
        "# RC8 行内 Reality 验证完整包\n\n"
        "构建 HEAD: `%s`\n\n" % head
        + "这是完整替换包，不是补丁包。解压到新目录运行，不要覆盖旧包。\n\n"
        "## 包内能力\n"
        "- RC8 Center / Node Agent / WorkItem Lease / R1 Runtime Truth\n"
        "- Artifact Sync + SHA-256 + AVAILABLE gate\n"
        "- Maven/JUnit Reality Runner\n"
        "- CodeGraph Reality Runner（Git snapshot 绑定）\n"
        "- Code Analysis Reality Runner（多轮结构充分度 + DSH 语义证据契约）\n\n"
        "## 外部前置\n"
        "本 Reality 包复用银行环境已存在的 Python/Git/Java/Maven/CodeGraph。"
        "完整代码分析最终 PASS 还需要行内 DSH 语义 Worker。"
        "本包不是最终 RC8-NODE 全工具离线交付包，不会临时访问公网下载安装工具。\n\n"
        "## 1. 校验\n"
        "```bash\nsha256sum -c SHA256SUMS.txt\n```\n\n"
        "## 2. 固定 Node state（跨版本包复用）\n"
        "```bash\n"
        "export RC8_NODE_ID=office-pc-01\n"
        "export RC8_NODE_STATE_DIR=\"$HOME/.rc8/node-state/$RC8_NODE_ID\"\n"
        "export RC8_NODE_STATE=\"$RC8_NODE_STATE_DIR\"\n"
        "mkdir -p \"$RC8_NODE_STATE\"\n"
        "```\n\n"
        "如果旧包已经注册过同名 Node，先把旧包的 node-identity.json 原样迁入这个永久目录，禁止重新生成身份。\n\n"
        "## 3. Center\n"
        "```bash\n"
        "bash packaging/rc8/rc8-center.sh --check --state-dir ./runtime/rc8-center\n"
        "bash packaging/rc8/rc8-center.sh --host 127.0.0.1 --port 4098 --state-dir ./runtime/rc8-center\n"
        "```\n\n"
        "## 4. Node\n"
        "```bash\n"
        "bash packaging/rc8/rc8-node.sh --once --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\"\n"
        "```\n\n"
        "## 5. Maven/JUnit Reality\n"
        "```bash\n"
        "bash packaging/rc8/rc8-maven-reality.sh --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\" \\\n"
        "  --project-dir /d/PFC/bloan-prod-factory-cfg-center --maven mvn \\\n"
        "  --maven-repo /c/Users/<user>/.m2/repository --allow-online --require-pass\n"
        "```\n\n"
        "## 6. CodeGraph Reality\n"
        "```bash\n"
        "bash packaging/rc8/rc8-codegraph-reality.sh --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\" \\\n"
        "  --project-dir /d/PFC/bloan-prod-factory-cfg-center \\\n"
        "  --codegraph /path/to/real/codegraph.exe --base-ref HEAD~1 --head-ref HEAD --max-points 2\n"
        "```\n\n"
        "## 7. Code Analysis Reality\n"
        "第一阶段先验证多轮结构分析。结构证据充分但无 DSH 语义结果时，预期 exit code=30、SEMANTIC_PENDING，这是正确状态。\n\n"
        "```bash\n"
        "bash packaging/rc8/rc8-code-analysis-reality.sh --center http://127.0.0.1:4098 \\\n"
        "  --node-id office-pc-01 --operator test-user --state-dir \"$RC8_NODE_STATE\" \\\n"
        "  --project-dir /d/PFC/bloan-prod-factory-cfg-center \\\n"
        "  --codegraph /path/to/real/codegraph.exe --base-ref HEAD~1 --head-ref HEAD\n"
        "```\n\n"
        "DSH 按 `docs/rc8/RC8-CODE-ANALYSIS-REALITY-RUNBOOK.md` 生成 evidence-bound `semantic-analysis.json` 后，"
        "增加 `--semantic-json /path/to/semantic-analysis.json` 重跑同一 snapshot。\n\n"
        "完整 Code Analysis PASS 必须看到 `CODE_ANALYSIS_SUFFICIENT + capability_state=VERIFIED + R1 PERSISTENCE_VERIFIED`。\n",
        encoding="utf-8",
    )
    return relative


def _write_manifest(package_root: Path, head: str, files: List[str]) -> str:
    relative = "PACKAGE-MANIFEST.json"
    manifest: Dict[str, object] = {
        "schema_version": "rc8.bank-reality-package.v3",
        "package_type": "FULL_STANDALONE_REALITY_VALIDATION_PACKAGE",
        "patch_package": False,
        "git_head": head,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "public_internet_install_required": False,
        "included_runtime_capabilities": [
            "CENTER_NODE_CONTROL",
            "R1_RUNTIME_TRUTH",
            "ARTIFACT_SYNC",
            "MAVEN_JUNIT_REALITY",
            "CODEGRAPH_REALITY",
            "CODE_ANALYSIS_REALITY",
        ],
        "external_bank_capabilities_expected": [
            "PYTHON_3_8_PLUS",
            "GIT",
            "JAVA_MAVEN",
            "CODEGRAPH",
            "DSH_SEMANTIC_WORKER_FOR_FULL_CODE_ANALYSIS",
        ],
        "files": sorted(files),
        "truth_note": "Package completeness does not imply bank capability VERIFIED; each tool/stage requires its Reality Gate.",
    }
    path = package_root / relative
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return relative


def _write_hashes(package_root: Path) -> Tuple[str, int]:
    relative = "SHA256SUMS.txt"
    path = package_root / relative
    rows: List[str] = []
    count = 0
    for file_path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        rel = file_path.relative_to(package_root).as_posix()
        if rel == relative:
            continue
        rows.append("%s  %s" % (_sha256(file_path), rel))
        count += 1
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return relative, count


def _verify_python(package_root: Path) -> None:
    py_files = [str(path) for path in package_root.rglob("*.py")]
    command = [sys.executable, "-m", "py_compile"] + py_files
    proc = subprocess.run(command, cwd=str(package_root), check=False)
    if proc.returncode != 0:
        raise RuntimeError("PACKAGE_PYTHON_COMPILE_FAILED")
    for pycache in package_root.rglob("__pycache__"):
        shutil.rmtree(str(pycache), ignore_errors=True)


def _zip_tree(package_root: Path, output_zip: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(output_zip), "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                arcname = (Path(package_root.name) / path.relative_to(package_root)).as_posix()
                archive.write(str(path), arcname)
    with zipfile.ZipFile(str(output_zip), "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("PACKAGE_ZIP_INTEGRITY_FAILED:%s" % bad)


def build(repo: Path, output_dir: Path) -> Dict[str, object]:
    head = _resolve_head(repo)
    short = head[:8] if head != "UNKNOWN_HEAD" else "unknown"
    package_name = "RC8-W1-REALITY-BANK-%s" % short
    output_zip = output_dir / (package_name + ".zip")
    with tempfile.TemporaryDirectory(prefix="rc8-w1-package-") as temp_dir:
        package_root = Path(temp_dir) / package_name
        package_root.mkdir(parents=True)
        files = _copy_required(repo, package_root)
        files.append(_write_config(package_root))
        files.append(_write_readme(package_root, head))
        files.append(_write_manifest(package_root, head, files))
        hashes_name, hashed_count = _write_hashes(package_root)
        files.append(hashes_name)
        _verify_python(package_root)
        _zip_tree(package_root, output_zip)
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
    parser = argparse.ArgumentParser(description="Build complete RC8 bank reality package")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args(argv)
    try:
        result = build(Path(args.repo).resolve(), Path(args.output_dir).resolve())
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "PACKAGE_BUILD_FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
