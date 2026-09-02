"""G2 repaired product-path autonomous orchestration checks.

FakeOpenCodeSessionProvider replaces only the external transport. All product
actions, R2.2-R2.6 governance and durable state use the real canonical runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = WORKSPACE_ROOT / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT))

from aitest_runtime import product_entry  # noqa: E402
from aitest_runtime.autonomous_orchestration import FakeOpenCodeSessionProvider  # noqa: E402
from aitest_runtime.g2_1.managed_orchestration import G21AutonomousOrchestrationService  # noqa: E402
from aitest_runtime.canonical_runtime import create_canonical_runtime  # noqa: E402
from aitest_runtime.durable_core import canonical_sha256  # noqa: E402


def _source_digest(value: object) -> str:
    return canonical_sha256(value)


def _request(intake_id: str, *, version: str = "TEST-VERSION") -> dict[str, object]:
    return {
        "intake_id": intake_id,
        "operation": "CREATE",
        "scope": {"mode": "EXPLICIT_SET", "project_id": "PFC", "version": version, "repositories": ["cfg-admin", "cfg-data"]},
        "goal": {"title": "Test current PFC version", "intent": "Analyze requirement/code change and test the governed version", "constraints": []},
        "source": {"kind": "USER", "source_ref": f"construction:{intake_id}", "source_digest": _source_digest({"intake_id": intake_id}), "observed_at": "2026-09-01T10:00:00Z", "valid_until": None, "source_precedence": 1},
        "actor": {"type": "USER", "id": "construction-test"},
        "resolution": {"resolution_id": f"resolution:{intake_id}", "request_digest": _source_digest({"resolution": intake_id}), "snapshot_id": f"snapshot:{intake_id}", "fact_set_digest": _source_digest({"facts": []}), "status": "RESOLVED", "reason_code": None, "source_refs": [f"construction:{intake_id}"], "valid_until": "2026-09-02T10:00:00Z"},
    }


def _proposal() -> dict[str, object]:
    return {
        "objective": "Analyze requirement/code impact before designing governed tests",
        "tasks": [
            {"task_key": "analyze-change", "intent": "Analyze requirement and changed code impact", "acceptance_criteria": [{"id": "analysis-evidence", "description": "Impact analysis is evidence-bound"}]},
            {"task_key": "design-tests", "intent": "Design risk-driven governed standard test cases", "acceptance_criteria": [{"id": "case-trace", "description": "Cases trace to requirement and change risk"}]},
        ],
        "dependencies": [{"from": "analyze-change", "to": "design-tests"}],
    }


class FailNextCreateProvider(FakeOpenCodeSessionProvider):
    def __init__(self, directory: str | Path) -> None:
        super().__init__(directory)
        self.fail_next_create = False

    def create_session(self, *, title: str, parent_id: str | None = None):  # type: ignore[override]
        if self.fail_next_create:
            self.fail_next_create = False
            raise RuntimeError("INJECTED_OPENCODE_CREATE_FAILURE")
        return super().create_session(title=title, parent_id=parent_id)


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _mission_count(db: Path) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM mission_projection").fetchone()[0])
    finally:
        conn.close()


def main() -> int:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="pfc-g2-product-") as td:
        root = Path(td)
        spine = root / "runtime-spine.db"
        runtime = create_canonical_runtime(root, db_path=spine)
        provider = FakeOpenCodeSessionProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        legacy = root / "ai-test/state/aitest.db"
        legacy_before = _sha(legacy)

        previous_workspace = os.environ.get("AITEST_WORKSPACE_ROOT")
        original_factory = product_entry.orchestration_service
        os.environ["AITEST_WORKSPACE_ROOT"] = str(root)
        product_entry.orchestration_service = lambda _root=None: service  # type: ignore[assignment]
        try:
            started = product_entry.orchestration_command("DIRECTOR", "start_test", {"request": _request("g2-a")})
            mission_id = started["intake"]["intake"]["mission_id"]
            checks["product_start_creates_active_mission_and_planner"] = (
                started["status"] == "PLANNING"
                and started["planner_session"]["status"] == "PLANNER_SESSION_OPEN"
                and service.status(mission_id)["core"]["mission"]["status"] == "ACTIVE"
            )

            resumed = product_entry.orchestration_command("DIRECTOR", "start_test", {"request": _request("g2-b")})
            checks["same_scope_new_intake_resumes_same_mission"] = (
                resumed["intake"]["status"] == "RESUMED"
                and resumed["intake"]["intake"]["mission_id"] == mission_id
                and _mission_count(spine) == 1
            )

            plan = product_entry.orchestration_command("PLANNER", "propose_plan", {"mission_id": mission_id, "proposal": _proposal()})
            first = plan["next"]
            checks["planner_pass_automatically_hands_off_and_dispatches"] = (
                plan["status"] == "PASS"
                and plan["autonomous_handoff"] == "SCHEDULER"
                and first["status"] == "DISPATCHED"
                and first["agent"] == "aitest-executor"
                and "analyze-change" in first["task_id"]
            )

            rejected = False
            try:
                product_entry.orchestration_command("EXECUTOR", "report_task_outcome", {
                    "mission_id": mission_id,
                    "task_id": first["task_id"],
                    "attempt_id": first["attempt"]["attempt_id"],
                    "session_id": "wrong-session",
                    "outcome": "SUCCEEDED",
                    "summary": "must reject wrong session",
                })
            except RuntimeError as exc:
                rejected = "TASK_OUTCOME_SESSION_MISMATCH" in str(exc)
            checks["worker_outcome_wrong_session_is_rejected"] = rejected

            completed_first = product_entry.orchestration_command("EXECUTOR", "report_task_outcome", {
                "mission_id": mission_id,
                "task_id": first["task_id"],
                "attempt_id": first["attempt"]["attempt_id"],
                "session_id": first["external_session"]["session_id"],
                "outcome": "SUCCEEDED",
                "summary": "analysis evidence complete",
                "external_references": [{"namespace": "TEST", "id": "analysis-evidence"}],
            })
            second = completed_first["next"]
            checks["worker_outcome_automatically_dispatches_dependency_successor"] = (
                completed_first["status"] == "SUCCEEDED"
                and second["status"] == "DISPATCHED"
                and "design-tests" in second["task_id"]
            )

            provider.set_observation(
                second["external_session"]["session_id"],
                message_count=61, compaction_count=0, context_utilization=0.5, healthy=True,
            )
            tick = product_entry.orchestration_command("CONTROL", "control_tick", {})
            rotated_items = [
                item["result"] for item in tick.get("supervision", [])
                if item.get("task_id") == second["task_id"] and item.get("result", {}).get("status") == "ROTATED"
            ]
            observed = rotated_items[0]
            rotation = observed["rotation"]
            checks["runtime_policy_automatically_rotates_on_threshold_without_agent_observe"] = (
                observed["status"] == "ROTATED"
                and "MESSAGE_THRESHOLD" in observed["rotation_reasons"]
                and rotation["root_attempt_id"] == second["attempt"]["root_attempt_id"]
                and rotation["successor_session_id"] != second["external_session"]["session_id"]
            )

            completed_second = product_entry.orchestration_command("EXECUTOR", "report_task_outcome", {
                "mission_id": mission_id,
                "task_id": second["task_id"],
                "attempt_id": rotation["successor_attempt_id"],
                "session_id": rotation["successor_session_id"],
                "outcome": "SUCCEEDED",
                "summary": "case design complete",
            })
            checks["orchestration_loop_reaches_plan_complete"] = completed_second["next"]["status"] == "PLAN_COMPLETE"

            continued = product_entry.orchestration_command("DIRECTOR", "continue_test", {"mission_id": mission_id})
            checks["continue_reads_durable_state_not_conversation"] = continued["status"] == "PLAN_COMPLETE"
        finally:
            product_entry.orchestration_service = original_factory  # type: ignore[assignment]
            if previous_workspace is None:
                os.environ.pop("AITEST_WORKSPACE_ROOT", None)
            else:
                os.environ["AITEST_WORKSPACE_ROOT"] = previous_workspace

        runtime2 = create_canonical_runtime(root, db_path=spine)
        service2 = G21AutonomousOrchestrationService(runtime2, root, session_provider=FakeOpenCodeSessionProvider(root))
        recovered = service2.status(mission_id)
        checks["new_service_instance_recovers_lineage_without_conversation"] = (
            recovered["truth_source"] == "R1_EVENT_STREAM"
            and recovered["conversation_is_not_truth"] is True
            and len(recovered["execution"]["attempts"]) >= 3
            and len(recovered["session_orchestration"]["bindings"]) >= 2
        )
        checks["legacy_aitest_db_not_created_or_modified"] = legacy_before == _sha(legacy)

    with tempfile.TemporaryDirectory(prefix="pfc-g2-crash-") as td:
        root = Path(td)
        runtime = create_canonical_runtime(root, db_path=root / "runtime-spine.db")
        provider = FailNextCreateProvider(root)
        service = G21AutonomousOrchestrationService(runtime, root, session_provider=provider)
        started = service.start_test(_request("g2-crash", version="CRASH-V"))
        mission_id = started["intake"]["intake"]["mission_id"]
        provider.fail_next_create = True
        failed = False
        try:
            service.propose_plan(mission_id, {"objective": "one crash-safe task", "tasks": [{"task_key": "one", "intent": "perform one governed unit", "acceptance_criteria": []}], "dependencies": []})
        except RuntimeError as exc:
            failed = "INJECTED_OPENCODE_CREATE_FAILURE" in str(exc)
        graph = service.runtime.replay_composed(mission_id).extension_state("r1_2_work_graph")
        repaired = service.advance(mission_id)
        checks["external_session_failure_keeps_durable_task_and_repair_reuses_it"] = (
            failed
            and len(graph.tasks) == 1
            and graph.tasks[0].lifecycle_state.value == "ACTIVE"
            and repaired["status"] == "DISPATCHED"
            and len(service.status(mission_id)["work_graph"]["tasks"]) == 1
            and len(service.status(mission_id)["execution"]["attempts"]) == 1
        )

    tool_source = (WORKSPACE_ROOT / ".opencode/tools/aitest.ts").read_text(encoding="utf-8")
    product_source = (RUNTIME_ROOT / "aitest_runtime/product_entry.py").read_text(encoding="utf-8")
    checks["product_tool_exposes_outcome_but_agent_session_health_is_removed"] = (
        '"EXECUTOR"' in tool_source and "report_task_outcome" in tool_source
        and 'action: tool.schema.string().describe("status|report_task_outcome|record_cursor|recover_cursor|register_capability|validate_executor|execute_capability|capability_human_gate|request_human_takeover|reconcile_human_takeover|complete_human_takeover|record_step_result|create_batch")' in tool_source
        and '"EXECUTOR": {"status", "report_task_outcome"}' in product_source
        and "create_session" not in tool_source.split("export const executor = tool({", 1)[1].split("export const g4_director", 1)[0]
        and "rotate_session" not in tool_source.split("export const executor = tool({", 1)[1].split("export const g4_director", 1)[0]
        and "close_session" not in tool_source.split("export const executor = tool({", 1)[1].split("export const g4_director", 1)[0]
        and '"CONTROL": {"status", "control_tick", "reconcile_sessions", "observe_session", "rotate_session"}' in product_source
    )
    checks["production_product_entry_has_no_fake_provider_selection"] = "FakeOpenCodeSessionProvider(" not in product_source

    command_expectations = {
        "aitest-start.md": "action=`start_test`",
        "aitest-continue.md": "action=`continue_test`",
        "aitest-mission-create.md": "action=`start_test`",
        "aitest-plan.md": "action=`propose_plan`",
        "aitest-schedule.md": "action=`advance`",
        "aitest-status.md": "action=`status`",
        "pfc-start.md": "action=`start_test`",
        "kyb-start.md": "action=`start_test`",
    }
    commands = WORKSPACE_ROOT / ".opencode/commands"
    checks["g2_slash_commands_align_with_product_actions"] = all(
        token in (commands / name).read_text(encoding="utf-8") for name, token in command_expectations.items()
    )
    hold_names = ["aitest-preflight.md", "aitest-execute.md", "aitest-evaluate.md", "aitest-diagnose.md", "aitest-defect.md", "aitest-finalize.md", "aitest-teach.md", "aitest-knowledge.md", "aitest-browser-teach.md"]
    checks["future_gate_commands_fail_closed_instead_of_legacy_actions"] = all("HOLD" in (commands / name).read_text(encoding="utf-8") for name in hold_names)

    payload = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
