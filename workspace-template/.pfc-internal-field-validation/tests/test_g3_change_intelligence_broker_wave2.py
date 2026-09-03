from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve()
WORKSPACE = HERE.parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider  # noqa: E402
from aitest_runtime.canonical_runtime import create_canonical_runtime  # noqa: E402
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService  # noqa: E402
from aitest_runtime.g3.code_intelligence import ChangeIntelligenceBroker, analyze_repository  # noqa: E402
from aitest_runtime.g3.service import G3TestingIntelligenceService  # noqa: E402
from aitest_runtime.g3.codegraph_provider import (  # noqa: E402
    CodeGraphContribution,
    CodeGraphProviderResolver,
    ProviderHealth,
    StructuralLineMapping,
)
from aitest_runtime.r3_2.contracts import ImpactEdge, RepositoryCompareRequest  # noqa: E402


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip()


def make_repo(root: Path, name: str, path: str, before: str, after: str) -> tuple[Path, str, str]:
    repo = root / name
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "master")
    git(repo, "config", "user.email", "wave2@example.invalid")
    git(repo, "config", "user.name", "Wave2 Test")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(before, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    target.write_text(after, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    head = git(repo, "rev-parse", "HEAD")
    return repo, base, head


def changed_refs(env: Any) -> set[str]:
    return {ref for item in env.changed_files for ref in item.diff_hunk_refs}


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def intake_request() -> dict[str, Any]:
    return {
        "intake_id": "g3-wave2-durable",
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": "V2", "repositories": ["wave2"]},
        "goal": {"title": "G3 Wave2 provider truth", "intent": "prove provider composition is durable", "constraints": []},
        "source": {
            "kind": "USER", "source_ref": "wave2:test", "source_digest": canonical_digest({"wave2": 2}),
            "observed_at": "2026-09-02T22:00:00Z", "valid_until": None, "source_precedence": 1,
        },
        "actor": {"type": "USER", "id": "wave2-test"},
        "resolution": {
            "resolution_id": "wave2:resolution", "request_digest": canonical_digest({"resolution": 2}),
            "snapshot_id": "wave2:snapshot", "fact_set_digest": canonical_digest([]), "status": "RESOLVED",
            "reason_code": None, "source_refs": ["wave2:test"], "valid_until": "2026-09-03T22:00:00Z",
        },
    }


def minimal_requirement_semantics() -> dict[str, Any]:
    return {
        "source_refs": [{"source_id": "REQ-W2", "source_kind": "REQUIREMENT", "revision": "V2", "locator": "requirement://REQ-W2"}],
        "business_rules": [{"text": "Changed executable behavior remains a governed test obligation", "source_id": "REQ-W2", "code_refs": ["src/Service.java"]}],
        "field_data_rules": [], "state_transitions": [], "positive_paths": [], "negative_paths": [],
        "exception_paths": [], "boundary_rules": [], "permission_rules": [], "cross_system_flows": [],
        "acceptance_criteria": [], "non_functional_risks": [], "unknowns": [],
    }


def line_rows(meta: Mapping[str, Any], path: str) -> list[Mapping[str, Any]]:
    return [item for item in meta.get("line_mapping") or [] if item.get("file_path") == path]


class DeterministicGraphProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self._health = ProviderHealth("codegraph-ai/CodeGraph", "AVAILABLE", "0.20.1", "graph-only", None, "a" * 64, "profile-digest")

    @property
    def health(self) -> ProviderHealth:
        return self._health

    def analyze(
        self,
        repository_path: Path,
        compare_request: RepositoryCompareRequest,
        changed_executable_lines: Sequence[tuple[str, int]],
    ) -> CodeGraphContribution:
        if self.fail:
            return CodeGraphContribution(
                ProviderHealth("codegraph-ai/CodeGraph", "PARTIAL", "0.20.1", "graph-only", "DETERMINISTIC_FAILURE", "a" * 64, "profile-digest"),
                warnings=("CODEGRAPH_QUERY_FAILED:deterministic",),
            )
        mappings = tuple(
            StructuralLineMapping(
                file_path=path,
                line_number=line,
                symbol_id=f"{path}:cg-symbol",
                symbol_name="cg-symbol",
                symbol_kind="METHOD",
                confidence=0.99,
                provider_ref="codegraph:0.20.1:graph-only:test",
                source_provenance=("codegraph:0.20.1:graph-only:test", f"file:{path}:L{line}"),
            )
            for path, line in changed_executable_lines
        )
        edge = ()
        if mappings:
            edge = (
                ImpactEdge(
                    mappings[0].symbol_id,
                    "dependency:callee",
                    "CALL",
                    "OUTBOUND",
                    1,
                    0.99,
                    "codegraph:0.20.1:graph-only:test",
                    ("codegraph:test-edge",),
                ),
            )
        return CodeGraphContribution(
            self._health,
            mappings,
            edge,
            source_refs=("codegraph:0.20.1:graph-only:test",),
            graph_digest="graph-digest-test",
        )


def assert_mixed_partial(
    checks: dict[str, bool],
    key: str,
    repo: Path,
    base: str,
    head: str,
    path: str,
) -> None:
    _, env, meta = analyze_repository({"repository_id": key, "repository_path": str(repo), "base_ref": base, "head_ref": head})
    refs = changed_refs(env)
    rows = line_rows(meta, path)
    row_refs = {str(item["line_ref"]) for item in rows}
    missing = [item for item in rows if item["status"] == "UNMAPPED"]
    mapped = [item for item in rows if item["status"] == "MAPPED_TO_SYMBOL"]
    obligations = [item for item in meta.get("mapping_obligations") or [] if item.get("file_path") == path]
    checks[f"{key}_git_changed_line_truth_preserved"] = bool(refs) and row_refs.issubset(refs)
    checks[f"{key}_mixed_change_has_mapped_and_unmapped_line_truth"] = bool(mapped) and bool(missing)
    checks[f"{key}_unmapped_line_has_exact_obligation"] = all(
        any(row["line_ref"] in (item.get("changed_line_refs") or []) for item in obligations)
        for row in missing
    )
    checks[f"{key}_regex_is_partial_not_complete"] = env.code_intelligence_status == "PARTIAL" and meta["provider_capabilities"].get("CODEGRAPH") == "UNAVAILABLE"


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="g3-wave2-java-") as td:
        repo, base, head = make_repo(
            Path(td),
            "java",
            "src/Service.java",
            "class Service {\n  int apply(int x) {\n    int y = x + 1;\n    return y;\n  }\n}\n",
            "class Service {\n  public int apply(int x) {\n    int y = x + 2;\n    return y;\n  }\n}\n",
        )
        assert_mixed_partial(checks, "java", repo, base, head, "src/Service.java")

    with tempfile.TemporaryDirectory(prefix="g3-wave2-ts-") as td:
        repo, base, head = make_repo(
            Path(td),
            "ts",
            "src/service.ts",
            "function apply(x: number) {\n  const y = x + 1\n  return y\n}\n",
            "export function apply(x: number) {\n  const y = x + 2\n  return y\n}\n",
        )
        assert_mixed_partial(checks, "typescript", repo, base, head, "src/service.ts")

    with tempfile.TemporaryDirectory(prefix="g3-wave2-vue-") as td:
        repo, base, head = make_repo(
            Path(td),
            "vue",
            "src/View.vue",
            "<script setup lang=\"ts\">\nfunction apply(x: number) {\n  const y = x + 1\n  return y\n}\n</script>\n<template><div>ok</div></template>\n",
            "<script setup lang=\"ts\">\nexport function apply(x: number) {\n  const y = x + 2\n  return y\n}\n</script>\n<template><div>ok</div></template>\n",
        )
        assert_mixed_partial(checks, "vue", repo, base, head, "src/View.vue")

    with tempfile.TemporaryDirectory(prefix="g3-wave2-graph-") as td:
        repo, base, head = make_repo(
            Path(td),
            "graph",
            "src/Service.java",
            "class Service {\n  int apply(int x) {\n    return x + 1;\n  }\n}\n",
            "class Service {\n  public int apply(int x) {\n    return x + 2;\n  }\n}\n",
        )
        broker = ChangeIntelligenceBroker(codegraph_provider=DeterministicGraphProvider())
        _, env, meta = analyze_repository({"repository_id": "graph", "repository_path": str(repo), "base_ref": base, "head_ref": head}, broker=broker)
        rows = line_rows(meta, "src/Service.java")
        checks["injected_codegraph_maps_every_relevant_changed_line"] = bool(rows) and all(item["status"] == "MAPPED_TO_SYMBOL" and item["provider"] == "CODEGRAPH" for item in rows)
        checks["injected_codegraph_edges_are_merged"] = any(edge.provider_ref.startswith("codegraph:") for edge in env.impact_edges)
        checks["injected_codegraph_provenance_and_digest_retained"] = meta["provider_capabilities"]["CODEGRAPH"] == "AVAILABLE" and meta["provider_provenance"]["codegraph_graph_digest"] == "graph-digest-test" and "codegraph:0.20.1:graph-only:test" in env.source_refs
        checks["codegraph_enrichment_does_not_replace_git_change_truth"] = changed_refs(env) == {row["line_ref"] for row in rows}
        checks["complete_is_possible_only_with_structural_mapping"] = env.code_intelligence_status == "COMPLETE" and not meta["mapping_obligations"]

        failed_broker = ChangeIntelligenceBroker(codegraph_provider=DeterministicGraphProvider(fail=True))
        _, failed_env, failed_meta = analyze_repository({"repository_id": "graph-fail", "repository_path": str(repo), "base_ref": base, "head_ref": head}, broker=failed_broker)
        checks["codegraph_failure_is_explicit_partial"] = failed_meta["provider_capabilities"]["CODEGRAPH"] == "PARTIAL" and "CODEGRAPH_PARTIAL" in failed_env.warnings
        checks["codegraph_failure_never_erases_git_diff"] = changed_refs(failed_env) == changed_refs(env) and bool(failed_env.changed_files)

    # The real resolver/executable seam is construction-tested without committing a runtime binary.
    with tempfile.TemporaryDirectory(prefix="g3-wave2-codegraph-exec-") as td:
        provider_root = Path(td)
        fake_binary = provider_root / "codegraph-server-win32-x64.exe"
        call_log = provider_root / "calls.log"
        fake_binary.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> '{call_log.as_posix()}'\n"
            "printf '%s\\n' '{\"symbolName\":\"resolvedByCodeGraph\",\"symbolKind\":\"METHOD\",\"startLine\":0,\"endLine\":999,\"uri\":\"src/Service.java\"}'\n",
            encoding="utf-8",
        )
        fake_binary.chmod(0o755)
        binary_sha = hashlib.sha256(fake_binary.read_bytes()).hexdigest()
        runtime_lock = provider_root / "runtime-lock.json"
        runtime_lock.write_text(json.dumps({
            "payloads": {
                "codegraph": {
                    "provider": "codegraph-ai/CodeGraph", "version": "0.20.1", "platform": "windows-x64",
                    "mode": "graph-only", "relative_target": fake_binary.name, "sha256": binary_sha,
                }
            }
        }), encoding="utf-8")
        resolved_provider = CodeGraphProviderResolver.resolve({"runtime_lock_path": str(runtime_lock)})
        repo_exec, base_exec, head_exec = make_repo(
            provider_root, "exec-repo", "src/Service.java",
            "class Service {\n  int apply(int x) { return x + 1; }\n}\n",
            "class Service {\n  public int apply(int x) { return x + 2; }\n}\n",
        )
        exec_broker = ChangeIntelligenceBroker(codegraph_provider=resolved_provider)
        _, exec_env, exec_meta = analyze_repository(
            {"repository_id": "exec-repo", "repository_path": str(repo_exec), "base_ref": base_exec, "head_ref": head_exec},
            broker=exec_broker,
        )
        calls = call_log.read_text(encoding="utf-8") if call_log.is_file() else ""
        checks["codegraph_resolver_requires_pinned_binary_sha"] = exec_meta["provider_health"]["CODEGRAPH"]["binary_sha256"] == binary_sha and exec_meta["provider_health"]["CODEGRAPH"]["version"] == "0.20.1"
        checks["codegraph_executable_provider_really_invokes_graph_only_tool"] = "--graph-only" in calls and "--run-tool codegraph_get_ai_context" in calls and exec_meta["provider_capabilities"]["CODEGRAPH"] == "AVAILABLE"
        checks["codegraph_executable_provider_maps_git_established_lines"] = bool(exec_meta["line_mapping"]) and all(item["status"] == "MAPPED_TO_SYMBOL" and item["provider"] == "CODEGRAPH" for item in exec_meta["line_mapping"]) and bool(exec_env.changed_files)

    with tempfile.TemporaryDirectory(prefix="g3-wave2-codegraph-missing-") as td:
        missing_root = Path(td)
        missing_lock = missing_root / "runtime-lock.json"
        missing_lock.write_text(json.dumps({"payloads": {"codegraph": {
            "provider": "codegraph-ai/CodeGraph", "version": "0.20.1", "platform": "windows-x64",
            "mode": "graph-only", "relative_target": "missing.exe", "sha256": "a" * 64,
        }}}), encoding="utf-8")
        missing_provider = CodeGraphProviderResolver.resolve({"runtime_lock_path": str(missing_lock)})
        checks["missing_codegraph_binary_is_unavailable_not_fake_available"] = missing_provider.health.status == "UNAVAILABLE" and missing_provider.health.version == "0.20.1" and missing_provider.health.mode == "graph-only"

    # Provider health/provenance and line-level obligations must survive R1 write + restart replay.
    with tempfile.TemporaryDirectory(prefix="g3-wave2-durable-") as td:
        durable_root = Path(td)
        spine = durable_root / "state" / "runtime-spine.db"
        spine.parent.mkdir(parents=True, exist_ok=True)
        runtime = create_canonical_runtime(durable_root, db_path=spine)
        orchestration = G21AutonomousOrchestrationService(runtime, durable_root, session_provider=FakeOpenCodeSessionProvider(durable_root))
        mission_id = orchestration.start_test(intake_request())["intake"]["intake"]["mission_id"]
        requirement_service = G3TestingIntelligenceService(runtime)
        requirement = requirement_service.analyze_requirement(mission_id, "REQ-W2", minimal_requirement_semantics())

        repo_partial, base_partial, head_partial = make_repo(
            durable_root, "durable-partial", "src/Service.java",
            "class Service {\n  int apply(int x) {\n    int y = x + 1;\n    return y;\n  }\n}\n",
            "class Service {\n  public int apply(int x) {\n    int y = x + 2;\n    return y;\n  }\n}\n",
        )
        partial = requirement_service.analyze_changes(
            mission_id, "REQ-W2",
            [{"repository_id": "durable-partial", "application_id": "durable-partial", "repository_path": str(repo_partial), "base_ref": base_partial, "head_ref": head_partial}],
            requirement["r3_1_reference"],
        )

        repo_graph, base_graph, head_graph = make_repo(
            durable_root, "durable-graph", "src/GraphService.java",
            "class GraphService {\n  int apply(int x) { return x + 1; }\n}\n",
            "class GraphService {\n  public int apply(int x) { return x + 2; }\n}\n",
        )
        graph_service = G3TestingIntelligenceService(
            runtime, change_intelligence_broker=ChangeIntelligenceBroker(codegraph_provider=DeterministicGraphProvider())
        )
        graph_result = graph_service.analyze_changes(
            mission_id, "REQ-W2",
            [{"repository_id": "durable-graph", "application_id": "durable-graph", "repository_path": str(repo_graph), "base_ref": base_graph, "head_ref": head_graph}],
            requirement["r3_1_reference"],
        )

        restarted = create_canonical_runtime(durable_root, db_path=spine)
        replay = G3TestingIntelligenceService(restarted).state(mission_id)
        partial_fact = replay.by_id(partial["change_analysis"]["fact_id"])
        objective_fact = replay.by_id(partial["coverage_objective"]["fact_id"])
        graph_fact = replay.by_id(graph_result["change_analysis"]["fact_id"])
        partial_repo = dict(partial_fact.payload["repositories"][0]) if partial_fact is not None else {}
        graph_repo = dict(graph_fact.payload["repositories"][0]) if graph_fact is not None else {}
        obligations = list(objective_fact.payload.get("risk_obligations") or []) if objective_fact is not None else []
        checks["durable_provider_health_survives_r1_restart_replay"] = partial_repo.get("provider_health", {}).get("GIT", {}).get("status") == "AVAILABLE" and partial_repo.get("provider_health", {}).get("CODEGRAPH", {}).get("status") == "UNAVAILABLE"
        checks["durable_line_mapping_survives_r1_restart_replay"] = bool(partial_repo.get("line_mapping")) and any(item.get("status") == "UNMAPPED" for item in partial_repo.get("line_mapping") or [])
        checks["durable_missing_symbol_obligation_has_exact_line_ref"] = bool(obligations) and all(item.get("obligation_kind") == "MISSING_SYMBOL_MAPPING" and item.get("changed_line_refs") for item in obligations)
        checks["durable_codegraph_provenance_survives_r1_restart_replay"] = graph_repo.get("provider_health", {}).get("CODEGRAPH", {}).get("status") == "AVAILABLE" and graph_repo.get("provider_provenance", {}).get("codegraph_graph_digest") == "graph-digest-test"
        checks["durable_codegraph_does_not_replace_git_line_truth"] = bool(graph_repo.get("changed_files")) and {r for f in graph_repo.get("changed_files") or [] for r in f.get("diff_hunk_refs") or []} == {m.get("line_ref") for m in graph_repo.get("line_mapping") or []}
        checks["runtime_projection_verifies_after_provider_composition"] = restarted.verify_projection(mission_id).get("ok") is True

    failed = [name for name, ok in checks.items() if not ok]
    print(json.dumps({"status": "PASS" if not failed else "FAIL", "passed": sum(checks.values()), "total": len(checks), "failed": failed, "checks": checks}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
