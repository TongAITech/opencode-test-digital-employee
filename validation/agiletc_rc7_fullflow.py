from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path
from types import MethodType
from urllib.parse import urlparse

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_code_evaluator import DshCodeEvaluator
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc7_runtime.dsh_test_design_evaluator import DshTestDesignEvaluator
from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge
from rc7_runtime.reality_recon import RuntimeRealityReconService


RC7_RUNTIME_STATUS_TOOL = "mcp__pfc_aitest_rc7__runtime_status"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")


def _task_state(control: ClosedLoopControlPlane, task_id: str) -> str:
    return control.scheduler.task(task_id).state.value


def _snapshot(truth: TruthRuntime, mission_id: str) -> dict:
    return {
        "mission": truth.query("rc7_mission", mission_id=mission_id),
        "tasks": truth.query("rc7_task", mission_id=mission_id),
        "gaps": truth.query("rc7_gap", mission_id=mission_id),
        "artifacts": truth.query("rc7_artifact", mission_id=mission_id),
        "evidence": truth.query("rc7_evidence", mission_id=mission_id),
        "evaluations": truth.query("rc7_evaluation", mission_id=mission_id),
        "agent_runtime_events": truth.query("agent_runtime_event", mission_id=mission_id),
    }


def _external_ref_valid(ref: str, *, target: Path, source_revision: str) -> bool:
    if ref.startswith("file://"):
        return Path(ref[len("file://"):]).exists()
    if ref.startswith("git://"):
        return source_revision in ref and "didi/AgileTC" in ref
    if ref.startswith("git-empty-tree://"):
        return ref == "git-empty-tree://4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    parsed = urlparse(ref)
    if parsed.scheme == "env":
        return bool(parsed.netloc or parsed.path)
    return False


def _install_external_input_validation_shim(
    control: ClosedLoopControlPlane,
    *,
    target: Path,
    source_revision: str,
) -> None:
    """Validation-only continuation after recording the product scheduler defect.

    Stable RC7 currently treats every input_artifact_ref as an R1 Artifact id.
    Mission Graph external URI inputs therefore never become READY even after
    Reality Recon passes.  This shim does not fabricate Artifacts: canonical
    Artifact refs still use the original scheduler check, while external refs
    must resolve to the checked-out AgileTC reality captured above.
    """
    scheduler = control.scheduler
    canonical_validator = scheduler._inputs_valid

    def _validation_inputs_valid(self, refs):
        canonical = []
        external = []
        for value in refs:
            ref = str(value)
            if "://" in ref:
                external.append(ref)
            else:
                canonical.append(ref)
        return canonical_validator(canonical) and all(
            _external_ref_valid(ref, target=target, source_revision=source_revision)
            for ref in external
        )

    scheduler._inputs_valid = MethodType(_validation_inputs_valid, scheduler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--dsh-bin", required=True)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    target = Path(args.target).resolve()
    output = Path(args.output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    r1 = output / "runtime-state" / "r1" / "event-stream.jsonl"
    state_root = output / "runtime-state"
    evidence_root = output / "evidence"
    mission_id = "AGILETC-FULLFLOW-" + args.source_revision[:12]
    release_id = "AGILETC-master"
    empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    goal = (
        "Use the RC7 DSH testing digital employee to validate AgileTC end-to-end: "
        "requirements, code, test design, executable scripts, runtime preparation, "
        "real execution, oracle/evidence, diagnosis/defect, convergence and report."
    )
    summary = {
        "schema_version": "pfc.aitest.rc7.agiletc-fullflow-validation.v2",
        "mission_id": mission_id,
        "release_id": release_id,
        "source_revision": args.source_revision,
        "target": str(target),
        "stages": [],
        "known_product_gaps": [],
        "validation_shims": [],
        "status": "IN_PROGRESS",
        "blocking_reason": None,
    }

    def stage(name: str, status: str, **extra: object) -> None:
        row = {"stage": name, "status": status}
        row.update(extra)
        summary["stages"].append(row)
        _write(output / "fullflow-summary.json", summary)

    try:
        start = start_or_resume(
            r1_path=str(r1),
            mission_id=mission_id,
            release_id=release_id,
            goal=goal,
            external_inputs={
                "REQUIREMENT_ANALYSIS": (
                    "file://" + str(target / "README_zh-CN.md"),
                    "file://" + str(target / "agiletc使用说明.md"),
                ),
                "CODE_ANALYSIS": (
                    "file://" + str(target),
                    "git://didi/AgileTC@" + args.source_revision,
                    "git-empty-tree://" + empty_tree,
                ),
            },
            graph_version="v2",
        )
        stage("MISSION_BOOTSTRAP", "PASS", result=start)

        truth = TruthRuntime(r1)
        control = ClosedLoopControlPlane(truth, release_id, mission_id)
        reality_task = next(
            row for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("node") == "REALITY_RECON"
        )
        build_log = output / "agiletc-maven-test.log"
        app_log = output / "agiletc-app.log"
        probe_log = output / "agiletc-http-probe.txt"
        reality = RuntimeRealityReconService(evidence_root=str(evidence_root)).reconcile(
            control,
            str(reality_task["task_id"]),
            facts={
                "release_id": release_id,
                "source_revision": args.source_revision,
                "repository_ref": "https://github.com/didi/AgileTC.git#master",
                "runtime_profile": "github-actions+dsh-headless+local-openai-compatible-model",
                "target_root": str(target),
                "maven_test_log": str(build_log),
                "application_log": str(app_log),
                "http_probe": str(probe_log),
            },
            evidence_refs=[
                "file://" + str(build_log),
                "file://" + str(app_log),
                "file://" + str(probe_log),
                "git://didi/AgileTC@" + args.source_revision,
            ],
        )
        stage("REALITY_RECON", reality.task_state, artifact_id=reality.artifact_id, evidence_ids=list(reality.evidence_ids))

        requirement_task = next(
            row for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("node") == "REQUIREMENT_ANALYSIS"
        )
        if requirement_task.get("state") != "READY":
            external_refs = [str(ref) for ref in requirement_task.get("input_artifact_refs", []) if "://" in str(ref)]
            if not external_refs:
                raise RuntimeError("REQUIREMENT_NOT_READY_WITHOUT_EXTERNAL_INPUTS")
            if not all(_external_ref_valid(ref, target=target, source_revision=args.source_revision) for ref in external_refs):
                raise RuntimeError("EXTERNAL_INPUT_REALITY_VALIDATION_FAILED")
            summary["known_product_gaps"].append({
                "id": "RC7-AGILETC-001",
                "title": "Mission external URI inputs are treated as Artifact ids by TaskScheduler",
                "impact": "Reality PASS cannot release Requirement/Code tasks when file:// or git:// inputs are present",
                "proof": {
                    "requirement_state_after_reality": requirement_task.get("state"),
                    "external_refs": external_refs,
                    "scheduler_contract": "TaskScheduler._inputs_valid queries rc7_artifact for every input_artifact_ref",
                },
            })
            _install_external_input_validation_shim(control, target=target, source_revision=args.source_revision)
            summary["validation_shims"].append("EXTERNAL_INPUT_REALITY_AWARE_READINESS")
            refreshed = control.refresh_ready()
            stage(
                "EXTERNAL_INPUT_SCHEDULER_GAP",
                "DEFECT_RECORDED_CONTINUATION_SHIM_ACTIVE",
                defect_id="RC7-AGILETC-001",
                ready_after_shim=[task.node for task in refreshed],
            )

        authority = RC7AuthorityRuntime(b"agiletc-rc7-validation-signing-key-2026")
        launcher = DshHeadlessWorkerLauncher(
            dsh_bin=args.dsh_bin,
            patch_path=args.patch,
            cwd=str(target),
            truth=truth,
            authority=authority,
            coordinator_instance_id="coordinator-agiletc-validation",
            release_id=release_id,
            state_root=str(state_root),
            timeout_seconds=600,
            env={
                "PFC_WORKSPACE": str(target),
                "PFC_AITEST_HOME": str(repo_root),
                "PFC_AITEST_STATE_DIR": str(state_root),
                "PFC_RC7_R1_PATH": str(r1),
                "PYTHONPATH": str(repo_root),
            },
        )
        bridge = DshTaskWorkerBridge(control, launcher)

        req_run = bridge.run_next()
        if req_run is None or control.scheduler.task(req_run.task_id).node != "REQUIREMENT_ANALYSIS":
            raise RuntimeError("REQUIREMENT_DSH_WORKER_NOT_DISPATCHED")
        stage(
            "REQUIREMENT_ANALYSIS_PRODUCER",
            req_run.task_state,
            task_id=req_run.task_id,
            dsh_session_id=req_run.dsh_session_id,
            tool_call_count=req_run.tool_call_count,
            artifact_ids=list(req_run.output_artifact_ids),
            evidence_ids=list(req_run.evidence_ids),
        )

        summary["known_product_gaps"].append({
            "id": "RC7-AGILETC-002",
            "title": "Independent DSH evaluators default to stale RC6 runtime_status MCP tool alias",
            "impact": "RC7-only MCP profile may expose no mcp__pfc_aitest_rc6__runtime_status tool",
            "continuation": "Validation passes the actual RC7 runtime_status alias explicitly; stable product code remains unchanged",
        })
        summary["validation_shims"].append("RC7_REVIEWER_RUNTIME_STATUS_TOOL_ALIAS")
        req_eval = DshRequirementEvaluator(
            launcher,
            allowed_tools=(RC7_RUNTIME_STATUS_TOOL,),
        ).evaluate_and_apply(control, req_run.task_id, req_run.output_artifact_ids[0])
        req_state = _task_state(control, req_run.task_id)
        stage(
            "REQUIREMENT_SUFFICIENCY",
            req_state,
            reviewer_worker_id=req_eval.reviewer_worker_id,
            reviewer_session_id=req_eval.reviewer_session_id,
            evaluation_result=req_eval.loop_result.evaluation.result.value,
            gap_ids=[gap.gap_id for gap in req_eval.loop_result.gaps],
        )
        if req_state != "PASS":
            raise RuntimeError("REQUIREMENT_NOT_ACCEPTED:%s" % req_state)

        code_run = bridge.run_next()
        if code_run is None or control.scheduler.task(code_run.task_id).node != "CODE_ANALYSIS":
            raise RuntimeError("CODE_DSH_WORKER_NOT_DISPATCHED")
        stage(
            "CODE_ANALYSIS_PRODUCER",
            code_run.task_state,
            task_id=code_run.task_id,
            dsh_session_id=code_run.dsh_session_id,
            tool_call_count=code_run.tool_call_count,
            artifact_ids=list(code_run.output_artifact_ids),
            evidence_ids=list(code_run.evidence_ids),
        )
        code_eval = DshCodeEvaluator(
            launcher,
            reviewer_allowed_tools=(RC7_RUNTIME_STATUS_TOOL, "git", "codegraph"),
        ).evaluate_and_apply(
            control,
            code_run.task_id,
            code_run.output_artifact_ids[0],
            target_id="git://didi/AgileTC@" + args.source_revision,
        )
        code_state = _task_state(control, code_run.task_id)
        stage(
            "CODE_SUFFICIENCY",
            code_state,
            reviewer_worker_id=code_eval.reviewer_worker_id,
            reviewer_session_id=code_eval.reviewer_session_id,
            evaluation_result=code_eval.loop_result.evaluation.result.value,
            gap_ids=[gap.gap_id for gap in code_eval.loop_result.gaps],
            analyzer_tool_evidence_ids=list(code_eval.analyzer_tool_evidence_ids),
        )
        if code_state != "PASS":
            raise RuntimeError("CODE_NOT_ACCEPTED:%s" % code_state)

        design_run = bridge.run_next()
        if design_run is None or control.scheduler.task(design_run.task_id).node != "TEST_DESIGN":
            raise RuntimeError("TEST_DESIGN_DSH_WORKER_NOT_DISPATCHED")
        stage(
            "TEST_DESIGN_PRODUCER",
            design_run.task_state,
            task_id=design_run.task_id,
            dsh_session_id=design_run.dsh_session_id,
            tool_call_count=design_run.tool_call_count,
            artifact_ids=list(design_run.output_artifact_ids),
            evidence_ids=list(design_run.evidence_ids),
        )
        design_eval = DshTestDesignEvaluator(
            launcher,
            reviewer_allowed_tools=(RC7_RUNTIME_STATUS_TOOL, "read_text", "codegraph_query"),
        ).evaluate_and_apply(control, design_run.task_id, design_run.output_artifact_ids[0])
        design_state = _task_state(control, design_run.task_id)
        stage(
            "TEST_DESIGN_SUFFICIENCY",
            design_state,
            reviewer_worker_id=design_eval.reviewer_worker_id,
            reviewer_session_id=design_eval.reviewer_session_id,
            evaluation_result=design_eval.loop_result.evaluation.result.value,
            case_count=design_eval.loop_result.case_count,
            semantic_coverage=design_eval.loop_result.semantic_coverage,
            gap_ids=[gap.gap_id for gap in design_eval.loop_result.gaps],
        )
        if design_state != "PASS":
            raise RuntimeError("TEST_DESIGN_NOT_ACCEPTED:%s" % design_state)

        script_task = next(
            row for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("node") == "SCRIPT_READINESS"
        )
        stage("SCRIPT_READINESS_BOUNDARY", str(script_task.get("state")), task_id=str(script_task.get("task_id")))
        raise RuntimeError("FULLFLOW_CONTINUATION_REQUIRES_CANONICAL_SCRIPT_AND_EXECUTION_COMPOSITION")

    except Exception as exc:
        summary["status"] = "HOLD"
        summary["blocking_reason"] = "%s:%s" % (type(exc).__name__, str(exc))
        summary["traceback"] = traceback.format_exc()
        try:
            truth = TruthRuntime(r1)
            summary["r1_snapshot"] = _snapshot(truth, mission_id)
        except Exception as snapshot_exc:
            summary["snapshot_error"] = str(snapshot_exc)
        _write(output / "fullflow-summary.json", summary)
        print(json.dumps({"status": "HOLD", "reason": summary["blocking_reason"]}, ensure_ascii=False))
        return 2

    summary["status"] = "PASS" if not summary["known_product_gaps"] else "HOLD_PRODUCT_GAPS"
    summary["blocking_reason"] = None if summary["status"] == "PASS" else "KNOWN_PRODUCT_GAPS_REQUIRE_STABLE_FIX"
    summary["r1_snapshot"] = _snapshot(TruthRuntime(r1), mission_id)
    _write(output / "fullflow-summary.json", summary)
    print(json.dumps({"status": summary["status"], "mission_id": mission_id}, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
