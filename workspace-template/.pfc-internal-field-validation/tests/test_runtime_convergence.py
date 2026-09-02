"""G1 repaired product-runtime convergence checks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT))

from aitest_runtime.canonical_runtime import (  # noqa: E402
    LEGACY_STORE_MODE,
    bootstrap_mission,
    canonical_db_path,
    create_canonical_runtime,
    runtime_status,
)


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    checks: dict[str, bool] = {}
    pfc_tool = (WORKSPACE_ROOT / ".opencode" / "tools" / "pfc.ts").read_text(encoding="utf-8")
    aitest_tool = (WORKSPACE_ROOT / ".opencode" / "tools" / "aitest.ts").read_text(encoding="utf-8")
    product_entry = (RUNTIME_ROOT / "aitest_runtime" / "product_entry.py").read_text(encoding="utf-8")
    process_bridge = (WORKSPACE_ROOT / "pfc-field-validation" / "pfc_web_runtime.py").read_text(encoding="utf-8")
    process_impl = (WORKSPACE_ROOT / "pfc-field-validation" / "pfc_opencode_process.py").read_text(encoding="utf-8")
    package_init = (RUNTIME_ROOT / "aitest_runtime" / "__init__.py").read_text(encoding="utf-8")

    old_env = {key: os.environ.get(key) for key in ("AITEST_RUNTIME_SPINE_DB", "PFC_CONTROL_ROOT", "PFC_REPO_ROOT")}
    try:
        for key in old_env:
            os.environ.pop(key, None)
        with tempfile.TemporaryDirectory(prefix="pfc-g1-authority-none-") as td:
            root = Path(td)
            failed = False
            try:
                canonical_db_path(root)
            except RuntimeError as exc:
                failed = "CANONICAL_RUNTIME_AUTHORITY_UNRESOLVED" in str(exc)
            checks["missing_authority_fails_closed"] = failed
            checks["missing_authority_creates_no_workspace_spine"] = not (root / "ai-test/state/runtime-spine.db").exists()

        with tempfile.TemporaryDirectory(prefix="pfc-g1-pointer-") as td:
            project = Path(td)
            workspace = project / "cfg-ai-test-workspace-r1r4"
            durable = project / ".pfc-r1r4" / "durable"
            control = project / ".pfc-r1r4"
            workspace.mkdir(parents=True)
            durable.mkdir(parents=True)
            control.mkdir(parents=True, exist_ok=True)
            (control / "current.json").write_text(json.dumps({
                "active_workspace": str(workspace.resolve()),
                "durable_root": str(durable.resolve()),
                "package_id": "TEST",
                "workspace_identity": "PFC_R1_R4_FIELD_VALIDATION_WORKSPACE",
            }), encoding="utf-8")
            resolved = canonical_db_path(workspace)
            checks["pointer_resolves_durable_spine"] = resolved == (durable / "state/runtime-spine.db").resolve()
            checks["pointer_does_not_resolve_workspace_local_spine"] = resolved != (workspace / "ai-test/state/runtime-spine.db").resolve()
            conflict = False
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str((workspace / "wrong/runtime-spine.db").resolve())
            try:
                canonical_db_path(workspace)
            except RuntimeError as exc:
                conflict = "CANONICAL_RUNTIME_AUTHORITY_CONFLICT" in str(exc)
            finally:
                os.environ.pop("AITEST_RUNTIME_SPINE_DB", None)
            checks["env_pointer_authority_conflict_fails_closed"] = conflict

        with tempfile.TemporaryDirectory(prefix="pfc-g1-runtime-") as td:
            root = Path(td)
            (root / "ai-test/state").mkdir(parents=True)
            legacy_source = WORKSPACE_ROOT / "ai-test/state/aitest.db"
            legacy_target = root / "ai-test/state/aitest.db"
            if legacy_source.is_file():
                shutil.copy2(legacy_source, legacy_target)
            legacy_before = sha256(legacy_target)
            spine = root / "durable/state/runtime-spine.db"
            spine.parent.mkdir(parents=True)
            os.environ["AITEST_RUNTIME_SPINE_DB"] = str(spine)
            runtime = create_canonical_runtime(root)
            extension_ids = {m.extension_id for m in runtime.extension_registry.manifests}
            bootstrap = bootstrap_mission(
                root,
                mission_id="g1-mission",
                goal_id="g1-goal",
                goal={"objective": "prove canonical product runtime convergence"},
                attributes={"project": "PFC", "gate": "G1"},
            )
            status = runtime_status(root)
            checks.update({
                "explicit_authority_is_exact_spine": runtime.db_path == spine.resolve(),
                "single_runtime_extension_count_27_with_additive_g4": len(extension_ids) == 27 and "g2_1_session_control" in extension_ids and "g3_testing_intelligence_product_integration" in extension_ids and "g4_real_execution_goal_convergence" in extension_ids,
                "r1_work_graph_present": "r1_2_work_graph" in extension_ids,
                "r2_session_orchestration_present": "r2_5_session_orchestration" in extension_ids,
                "r3_case_intelligence_present": "r3_3_test_strategy_standard_case_design" in extension_ids,
                "r3_defect_hunter_present": "r3_6_defect_investigation_rca" in extension_ids,
                "r4_closed_loop_present": "r4_8_closed_loop_continuous_quality_runtime_integration" in extension_ids,
                "mission_bootstrap_uses_event_stream": bootstrap.get("truth_source") == "R1_EVENT_STREAM" and bootstrap.get("head_seq") == 3,
                "status_uses_event_stream": status.get("truth_source") == "R1_EVENT_STREAM" and status.get("conversation_is_not_truth") is True,
                "legacy_store_declared_reference_only": (status.get("legacy_store") or {}).get("mode") == LEGACY_STORE_MODE,
                "legacy_store_not_modified": legacy_before == sha256(legacy_target),
            })
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    forbidden_local_fallback = 'path.join(workspace, "ai-test", "state", "runtime-spine.db")'
    checks.update({
        "pfc_tool_has_no_workspace_local_spine_fallback": forbidden_local_fallback not in pfc_tool,
        "aitest_tool_has_no_workspace_local_spine_fallback": forbidden_local_fallback not in aitest_tool,
        "tools_have_no_legacy_db_env": "AITEST_DB_PATH" not in pfc_tool and "AITEST_DB_PATH" not in aitest_tool,
        "product_entry_has_no_legacy_runtime_import": all(token not in product_entry for token in ("from . import mission", "from . import quality", "from . import scheduler", "from . import defects", "pfc_harness")),
        "package_init_has_no_legacy_common_import": "from .common" not in package_init,
        "process_bridge_no_legacy_harness_import": "pfc_harness" not in process_bridge,
        "process_impl_no_legacy_runtime_import_or_db": all(token not in process_impl for token in ("pfc_harness", "AITEST_DB_PATH", "aitest_runtime.mission", "aitest_runtime.scheduler", "aitest_runtime.defects")),
        "process_impl_pins_bank_opencode_1_18_3": 'EXPECTED_OPENCODE_VERSION = "1.18.3"' in process_impl,
        "opencode_probe_and_launch_use_same_git_bash_command_authority": '_git_bash_argv(["--version"])' in process_impl and '_git_bash_argv(["web", "--hostname", "127.0.0.1", "--port", str(port)])' in process_impl and 'shutil.which("opencode")' not in process_impl,
        "dynamic_opencode_endpoint_is_inherited_by_agent_process": 'child_env["AITEST_OPENCODE_ENDPOINT"] = endpoint' in process_impl and 'env=child_env' in process_impl,
        "windows_pid_probe_is_read_only": 'OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION' in process_impl and 'if os.name != "nt":' in process_impl,
        "windows_stop_forbids_taskkill_tree": '["taskkill", "/PID", str(number), "/F"]' in process_impl and '"/T"' not in process_impl.replace('`/T`', ''),
        "tools_use_canonical_product_entry": "aitest_runtime.product_entry" in pfc_tool and "aitest_runtime.product_entry" in aitest_tool,
        "tools_no_system_python_fallback": all(token not in (pfc_tool + aitest_tool) for token in ('["py", "-3"]', '["python3"]')),
    })

    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
