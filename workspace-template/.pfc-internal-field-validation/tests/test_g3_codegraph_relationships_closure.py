from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from aitest_runtime.g3.code_intelligence import ChangeIntelligenceBroker, analyze_repository
from aitest_runtime.g3.codegraph_provider import CodeGraphProviderResolver


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip()


def make_repo(root: Path) -> tuple[Path, str, str]:
    repo = root / "repo"
    (repo / "src").mkdir(parents=True)
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.email", "closure@example.invalid")
    git(repo, "config", "user.name", "Closure Test")
    (repo / "src/Service.java").write_text("class Service {\n  int apply(int x) { return x + 1; }\n}\n", encoding="utf-8")
    (repo / "src/Caller.java").write_text("class Caller { void call() {} }\n", encoding="utf-8")
    (repo / "src/Callee.java").write_text("class Callee { void target() {} }\n", encoding="utf-8")
    (repo / "src/Dependency.java").write_text("class Dependency {}\n", encoding="utf-8")
    (repo / "src/Impact.java").write_text("class Impact {}\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "src/Service.java").write_text("class Service {\n  public int apply(int x) { return x + 2; }\n}\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    return repo, base, git(repo, "rev-parse", "HEAD")


def write_binary(path: Path, *, fail_callers: bool) -> str:
    program = f'''#!/usr/bin/env python3
import json
import pathlib
import sys
args = sys.argv[1:]
tool = args[args.index("--run-tool") + 1]
workspace = pathlib.Path(args[args.index("--workspace") + 1])
if {str(fail_callers)} and tool == "codegraph_get_callers":
    print("caller query unavailable", file=sys.stderr)
    raise SystemExit(9)
def node(name, file_name, node_id):
    return {{"nodeId": node_id, "symbolName": name, "filePath": str(workspace / "src" / file_name), "line": 0, "depth": 1}}
if tool == "codegraph_get_ai_context":
    value = {{"nodeId": "service-apply", "symbolName": "Service.apply", "symbolKind": "METHOD", "filePath": str(workspace / "src" / "Service.java"), "startLine": 0, "endLine": 99}}
elif tool == "codegraph_get_callers":
    value = {{"callers": [node("Caller.call", "Caller.java", "caller-1")]}}
elif tool == "codegraph_get_callees":
    value = {{"callees": [node("Callee.target", "Callee.java", "callee-1")]}}
elif tool == "codegraph_get_dependency_graph":
    value = {{"dependencies": [node("Dependency", "Dependency.java", "dependency-1")]}}
elif tool == "codegraph_analyze_impact":
    value = {{"affected": [node("Impact", "Impact.java", "impact-1")]}}
else:
    print("unsupported tool", file=sys.stderr)
    raise SystemExit(11)
print(json.dumps(value))
'''
    path.write_text(program, encoding="utf-8")
    path.chmod(0o755)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provider(root: Path, binary: Path, sha: str):
    lock = root / "runtime-lock.json"
    lock.write_text(json.dumps({"payloads": {"codegraph": {
        "provider": "codegraph-ai/CodeGraph",
        "version": "0.20.1",
        "platform": "linux-x64",
        "mode": "graph-only",
        "relative_target": binary.name,
        "sha256": sha,
    }}}), encoding="utf-8")
    return CodeGraphProviderResolver.resolve({"runtime_lock_path": str(lock)})


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g3-codegraph-closure-") as td:
        root = Path(td)
        repo, base, head = make_repo(root)
        binary = root / "codegraph-server"
        sha = write_binary(binary, fail_callers=False)
        broker = ChangeIntelligenceBroker(codegraph_provider=provider(root, binary, sha))
        _request, env, meta = analyze_repository({
            "repository_id": "relationship-closure",
            "repository_path": str(repo),
            "base_ref": base,
            "head_ref": head,
        }, broker=broker)
        cg_edges = [edge for edge in env.impact_edges if str(edge.provider_ref).startswith("codegraph:")]
        kinds = {edge.edge_kind for edge in cg_edges}
        provenance = {ref for edge in cg_edges for ref in edge.source_provenance}
        checks["pinned_graph_only_provider_is_available"] = meta["provider_capabilities"]["CODEGRAPH"] == "AVAILABLE" and meta["provider_health"]["CODEGRAPH"]["binary_sha256"] == sha
        checks["real_caller_relationship_normalized"] = "CALLER" in kinds
        checks["real_callee_relationship_normalized"] = "CALLEE" in kinds
        checks["real_dependency_relationship_normalized"] = "DEPENDENCY" in kinds
        checks["real_impact_relationship_normalized"] = "IMPACT" in kinds
        checks["relationship_edges_keep_exact_tool_provenance"] = all(any(ref.startswith("codegraph-tool:") for ref in edge.source_provenance) for edge in cg_edges) and "codegraph-tool:codegraph_get_callers" in provenance
        git_refs_before = {ref for item in env.changed_files for ref in item.diff_hunk_refs}
        checks["git_remains_only_changed_line_truth"] = bool(git_refs_before) and all(ref.startswith("src/Service.java:L") for ref in git_refs_before)
        checks["complete_structural_truth_requires_successful_relationship_queries"] = env.code_intelligence_status == "COMPLETE" and not meta["mapping_obligations"]

        partial_sha = write_binary(binary, fail_callers=True)
        partial_broker = ChangeIntelligenceBroker(codegraph_provider=provider(root, binary, partial_sha))
        _request2, partial_env, partial_meta = analyze_repository({
            "repository_id": "relationship-closure-partial",
            "repository_path": str(repo),
            "base_ref": base,
            "head_ref": head,
        }, broker=partial_broker)
        obligations = partial_meta.get("mapping_obligations") or []
        git_refs_after = {ref for item in partial_env.changed_files for ref in item.diff_hunk_refs}
        checks["failed_relationship_query_downgrades_codegraph_partial"] = partial_meta["provider_capabilities"]["CODEGRAPH"] == "PARTIAL" and "CODEGRAPH_PARTIAL" in partial_env.warnings
        checks["failed_relationship_query_creates_explicit_obligation"] = any(item.get("obligation_kind") == "CODEGRAPH_STRUCTURAL_RELATIONSHIPS_PARTIAL" for item in obligations)
        checks["line_to_symbol_never_false_certifies_structural_complete"] = partial_env.code_intelligence_status == "PARTIAL" and any(row.get("provider") == "CODEGRAPH" for row in partial_meta["line_mapping"])
        checks["partial_codegraph_never_rewrites_git_truth"] = git_refs_after == git_refs_before

    failed = [key for key, value in checks.items() if not value]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
