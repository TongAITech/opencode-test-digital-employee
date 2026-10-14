from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from rc6_release.dsh import write_patch
from rc6_runtime import (
    AgentRuntimeError,
    AgentRuntimeProofValidator,
    AgentRuntimeQualificationResult,
    AuthorityRuntime,
    DshHeadlessWorkerLauncher,
    IndependentRequirementSufficiencyGate,
    MissionRuntime,
    TruthRuntime,
    append_gap,
    append_requirement_analysis,
    append_requirement_review,
    normalize_requirement_analysis,
    normalize_requirement_review,
)

RELEASE_ID = "RC6-AGENT-RUNTIME-QUALIFICATION"
REQUIREMENT_ID = "QUAL-REQ-BOUNDARY-001"
FIXTURE_REF = "qualification-fixture://missing-boundary-rule"
SOURCE_REQUIREMENT = (
    "交易金额必须大于0且不超过500000.00元；500000.00元必须允许通过；"
    "500000.01元及以上必须拒绝，并返回明确的超限业务结果。"
)


def _runtime_key(state_root: Path) -> bytes:
    path = state_root / "control" / "authority.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    key = path.read_bytes()
    if len(key) < 16:
        raise AgentRuntimeError("AUTHORITY_KEY_INVALID")
    return key


def _resolve_dsh(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env = os.environ.get("PFC_DSH_BIN")
    if env:
        return env
    return shutil.which("dsh") or ""


def _json_prompt_header(agent_id: str, worker_instance_id: str, mission_id: str) -> str:
    return f"""你是 RC6 的独立专业 Worker，不是 Coordinator。
agent_id={agent_id}
worker_instance_id={worker_instance_id}
mission_id={mission_id}

NON-NEGOTIABLE:
1. 先真实调用一次 mcp__pfc_aitest_rc6__runtime_status。不要伪造 tool call。
2. 你只能完成本 Worker 的专业职责，禁止替代 Coordinator 或其他 Worker。
3. 最终只输出一个 JSON object，不要 Markdown fence，不要附加解释。
4. 不要声称 Gate PASS；最终 Gate 由独立 Sufficiency Worker + deterministic runtime 计算。
"""


def _analysis_prompt(worker_id: str, mission_id: str, attempt: int, gap_ids: Optional[List[str]] = None) -> str:
    gap_ids = list(gap_ids or [])
    fault = attempt == 1
    instruction = (
        "这是资格验证的故障注入 Attempt #1：必须故意保留 missing_boundary_rule。"
        "因此 boundaries 必须输出空数组 []，known_omission 必须为 missing_boundary_rule。"
        "除该边界缺口外，其余分析必须尽量完整。"
        if fault else
        "这是 Repair Attempt #2。必须只针对收到的 gap 做专业修复，并完整恢复分析。"
        "boundaries 必须明确包含 500000.00 为包含边界、500000.01 为拒绝边界；known_omission 必须为 null。"
    )
    schema = """
输出字段必须至少包含：
{
  "br": [object...],
  "sr": [object...],
  "tr": [object...],
  "source_assertions": [{"id":"S1","text":"..."}, ...],
  "atomic_statements": [{"id":"A1","text":"...","source_ref":"S1","testable":true}, ...],
  "trace_links": [{"source_id":"S1","atomic_id":"A1","evidence_ref":"source://QUAL-REQ-BOUNDARY-001"}, ...],
  "evidence_refs": ["source://QUAL-REQ-BOUNDARY-001"],
  "business_rules": [object...],
  "roles": [object...],
  "preconditions": [object...],
  "normal_paths": [object...],
  "negative_paths": [object...],
  "boundaries": [object...],
  "states": [object...],
  "data_constraints": [object...],
  "dependencies": [object...],
  "side_effects": [object...],
  "known_omission": "missing_boundary_rule" | null
}
source_assertions 与 atomic_statements 必须全部有 trace_links，atomic_statements 的 testable 必须为 true。
br/sr/tr 可以是简洁结构化对象，但不能省略字段。
"""
    return _json_prompt_header("pfc-requirement-analysis", worker_id, mission_id) + f"""
职责：Requirement Analysis。
Attempt: {attempt}
输入 requirement_id={REQUIREMENT_ID}
输入需求原文：{SOURCE_REQUIREMENT}
Repair gaps: {json.dumps(gap_ids, ensure_ascii=False)}
{instruction}
{schema}
"""


def _review_prompt(worker_id: str, mission_id: str, analysis: Dict[str, Any], attempt: int) -> str:
    return _json_prompt_header("pfc-requirement-sufficiency", worker_id, mission_id) + f"""
职责：独立 Requirement Sufficiency Review。你不是 Analyzer，禁止修改分析内容。
Review Attempt: {attempt}
源需求：{SOURCE_REQUIREMENT}
待审 Analysis：
{json.dumps(analysis, ensure_ascii=False, sort_keys=True)}

必须独立检查：原子化、traceability、testability、business rules、roles、preconditions、normal/negative paths、boundaries、states、data constraints、dependencies、side effects。
特别检查源需求中的金额边界规则是否被 Analysis 明确覆盖。
如果缺失 500000.00 包含边界或 500000.01 拒绝边界，decision 必须为 GAPS，gap_ids 必须包含 missing_boundary_rule。
只有没有任何 gap 才允许 decision=PASS。

最终 JSON schema：
{{
  "decision": "PASS" | "GAPS",
  "gap_ids": ["..."],
  "evidence_refs": ["review://real-dsh-sufficiency"],
  "summary": "..."
}}
"""


def _event_names(truth: TruthRuntime, mission_id: str) -> List[str]:
    names: List[str] = []
    for event in truth.store.iter_raw():
        payload = event.get("payload")
        if isinstance(payload, dict) and payload.get("mission_id") == mission_id:
            names.append(str(event.get("event_type")))
    return names


def run_real_vertical_slice(
    *,
    home: str,
    dsh_bin: Optional[str] = None,
    patch_path: Optional[str] = None,
    coordinator_instance_id: Optional[str] = None,
    timeout_seconds: int = 300,
) -> AgentRuntimeQualificationResult:
    root = Path(home).resolve()
    state_root = Path(os.environ.get("PFC_AITEST_STATE_DIR", str(root / "runtime-state"))).resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    coordinator_id = coordinator_instance_id or ("coord-" + uuid.uuid4().hex)
    mission_id = "RC6-ARQ-" + time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]

    missions = MissionRuntime(str(state_root / "missions"))
    missions.create(mission_id, RELEASE_ID)
    truth = TruthRuntime(state_root / "r1" / "event-stream.jsonl")
    authority = AuthorityRuntime(_runtime_key(state_root))

    resolved_dsh = _resolve_dsh(dsh_bin)
    patch = Path(patch_path).resolve() if patch_path else (state_root / "rc6.cordis.yml")
    if not patch.is_file():
        write_patch(patch, root, sys.executable)

    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=resolved_dsh or "dsh",
        patch_path=str(patch),
        cwd=str(root),
        truth=truth,
        authority=authority,
        coordinator_instance_id=coordinator_id,
        release_id=RELEASE_ID,
        state_root=str(state_root),
        timeout_seconds=timeout_seconds,
        env={
            "PFC_AITEST_HOME": str(root),
            "PFC_AITEST_STATE_DIR": str(state_root),
            "PYTHONPATH": str(root) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        },
    )

    worker_ids: List[str] = []
    sessions: List[str] = []
    first_status: Optional[str] = None
    second_status: Optional[str] = None
    try:
        if not resolved_dsh:
            launcher.emit_control_event("ROUTING_INTEGRITY_FAIL", mission_id, reason="DSH_NOT_AVAILABLE")
            return AgentRuntimeQualificationResult(
                status="NOT_PROVEN",
                mission_id=mission_id,
                coordinator_instance_id=coordinator_id,
                reason="ROUTING_INTEGRITY_FAIL:DSH_NOT_AVAILABLE",
                r1_event_count=len(_event_names(truth, mission_id)),
                r1_proof_event_ids=(),
                worker_instance_ids=(),
                dsh_session_ids=(),
                first_gate_status=None,
                second_gate_status=None,
            )

        analysis_assignment_1 = launcher.assign(
            agent_id="pfc-requirement-analysis",
            role="REQUIREMENT_ANALYZER",
            phase="REQUIREMENT_ANALYSIS",
            mission_id=mission_id,
            attempt_id="analysis-attempt-1",
            scope=REQUIREMENT_ID,
            input_refs=(FIXTURE_REF,),
            allowed_artifact_types=("requirement_analysis",),
            allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
        )
        analysis_worker_1, analysis_output_1 = launcher.execute(
            analysis_assignment_1,
            _analysis_prompt(analysis_assignment_1.worker_instance_id, mission_id, 1),
        )
        worker_ids.append(analysis_worker_1.worker_instance_id)
        sessions.append(str(analysis_worker_1.dsh_session_id))
        analysis_1 = normalize_requirement_analysis(
            analysis_output_1,
            release_id=RELEASE_ID,
            requirement_id=REQUIREMENT_ID,
            worker=analysis_worker_1,
            attempt_number=1,
        )
        append_requirement_analysis(truth, analysis_1)

        review_assignment_1 = launcher.assign(
            agent_id="pfc-requirement-sufficiency",
            role="REQUIREMENT_REVIEWER",
            phase="REQUIREMENT_ANALYSIS",
            mission_id=mission_id,
            attempt_id="sufficiency-attempt-1",
            scope=analysis_1["analysis_id"],
            input_refs=(analysis_worker_1.output_refs[0],),
            allowed_artifact_types=("requirement_review", "analysis_gap"),
            allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
        )
        launcher.emit_control_event(
            "SUFFICIENCY_STARTED",
            mission_id,
            reviewer_worker_instance_id=review_assignment_1.worker_instance_id,
            analysis_id=analysis_1["analysis_id"],
            attempt="1",
        )
        review_worker_1, review_output_1 = launcher.execute(
            review_assignment_1,
            _review_prompt(review_assignment_1.worker_instance_id, mission_id, analysis_1, 1),
        )
        worker_ids.append(review_worker_1.worker_instance_id)
        sessions.append(str(review_worker_1.dsh_session_id))
        review_1 = normalize_requirement_review(
            review_output_1,
            release_id=RELEASE_ID,
            requirement_id=REQUIREMENT_ID,
            analysis=analysis_1,
            analyzer=analysis_worker_1,
            reviewer=review_worker_1,
            attempt_number=1,
        )
        append_requirement_review(truth, review_1)

        if str(review_1.get("decision", "")).upper() == "PASS":
            launcher.emit_control_event(
                "ROUTING_INTEGRITY_FAIL",
                mission_id,
                reason="FIRST_SUFFICIENCY_FALSE_PASS",
                reviewer_worker_instance_id=review_worker_1.worker_instance_id,
            )
            raise AgentRuntimeError("FIRST_SUFFICIENCY_FALSE_PASS")
        if "missing_boundary_rule" not in review_1.get("gap_ids", []):
            raise AgentRuntimeError("EXPECTED_MISSING_BOUNDARY_GAP_NOT_FOUND")

        gate = IndependentRequirementSufficiencyGate()
        gate_1 = gate.evaluate(analysis_1, review_1)
        first_status = gate_1.status
        if gate_1.passed:
            raise AgentRuntimeError("FIRST_SUFFICIENCY_MUST_FAIL")
        if "REQ_BOUNDARY_RULE_MISSING" not in gate_1.reasons:
            raise AgentRuntimeError("DETERMINISTIC_BOUNDARY_GAP_NOT_FOUND")
        gap_artifact_id = append_gap(truth, review_1, "missing_boundary_rule", "OPEN")
        launcher.emit_control_event(
            "SUFFICIENCY_GAP_FOUND",
            mission_id,
            analysis_id=analysis_1["analysis_id"],
            review_id=review_1["id"],
            gap_id="missing_boundary_rule",
            gap_artifact_id=gap_artifact_id,
            gate_reasons=list(gate_1.reasons),
        )

        launcher.emit_control_event(
            "REPAIR_REQUESTED",
            mission_id,
            gap_id="missing_boundary_rule",
            previous_analysis_id=analysis_1["analysis_id"],
            requested_agent_id="pfc-requirement-analysis",
        )
        analysis_assignment_2 = launcher.assign(
            agent_id="pfc-requirement-analysis",
            role="REQUIREMENT_ANALYZER",
            phase="REQUIREMENT_ANALYSIS",
            mission_id=mission_id,
            attempt_id="analysis-attempt-2",
            scope=REQUIREMENT_ID,
            input_refs=(analysis_worker_1.output_refs[0], "gap://missing_boundary_rule"),
            allowed_artifact_types=("requirement_analysis",),
            allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            generation=1,
        )
        launcher.emit_reassigned(analysis_worker_1, analysis_assignment_2)
        analysis_worker_2, analysis_output_2 = launcher.execute(
            analysis_assignment_2,
            _analysis_prompt(analysis_assignment_2.worker_instance_id, mission_id, 2, ["missing_boundary_rule"]),
        )
        worker_ids.append(analysis_worker_2.worker_instance_id)
        sessions.append(str(analysis_worker_2.dsh_session_id))
        analysis_2 = normalize_requirement_analysis(
            analysis_output_2,
            release_id=RELEASE_ID,
            requirement_id=REQUIREMENT_ID,
            worker=analysis_worker_2,
            attempt_number=2,
        )
        append_requirement_analysis(truth, analysis_2)

        review_assignment_2 = launcher.assign(
            agent_id="pfc-requirement-sufficiency",
            role="REQUIREMENT_REVIEWER",
            phase="REQUIREMENT_ANALYSIS",
            mission_id=mission_id,
            attempt_id="sufficiency-attempt-2",
            scope=analysis_2["analysis_id"],
            input_refs=(analysis_worker_2.output_refs[0], "gap://missing_boundary_rule"),
            allowed_artifact_types=("requirement_review", "analysis_gap"),
            allowed_tools=("mcp__pfc_aitest_rc6__runtime_status",),
            generation=1,
        )
        launcher.emit_control_event(
            "SUFFICIENCY_REEVALUATED",
            mission_id,
            reviewer_worker_instance_id=review_assignment_2.worker_instance_id,
            analysis_id=analysis_2["analysis_id"],
            attempt="2",
        )
        review_worker_2, review_output_2 = launcher.execute(
            review_assignment_2,
            _review_prompt(review_assignment_2.worker_instance_id, mission_id, analysis_2, 2),
        )
        worker_ids.append(review_worker_2.worker_instance_id)
        sessions.append(str(review_worker_2.dsh_session_id))
        review_2 = normalize_requirement_review(
            review_output_2,
            release_id=RELEASE_ID,
            requirement_id=REQUIREMENT_ID,
            analysis=analysis_2,
            analyzer=analysis_worker_2,
            reviewer=review_worker_2,
            attempt_number=2,
        )
        append_requirement_review(truth, review_2)
        gate_2 = gate.evaluate(analysis_2, review_2)
        second_status = gate_2.status
        if str(review_2.get("decision", "")).upper() != "PASS":
            raise AgentRuntimeError("SECOND_SUFFICIENCY_REVIEW_NOT_PASS")
        if not gate_2.passed:
            raise AgentRuntimeError("SECOND_SUFFICIENCY_DETERMINISTIC_GATE_NOT_PASS:%s" % ",".join(gate_2.reasons))

        append_gap(truth, {
            **review_2,
            "id": review_1["id"],
            "subject_analysis_id": analysis_2["analysis_id"],
        }, "missing_boundary_rule", "CLOSED")
        launcher.emit_control_event(
            "SUFFICIENCY_PASSED",
            mission_id,
            analysis_id=analysis_2["analysis_id"],
            review_id=review_2["id"],
            gate_status=gate_2.status,
            reviewer_worker_instance_id=review_worker_2.worker_instance_id,
        )

        proof_status, proof_ids = AgentRuntimeProofValidator().validate(truth, mission_id, coordinator_id)
        if proof_status != "PASS":
            raise AgentRuntimeError("R1_AGENT_RUNTIME_PROOF_NOT_PASS")
        if len(set(worker_ids)) != 4 or len(set(sessions)) != 4:
            raise AgentRuntimeError("INDEPENDENT_WORKER_IDENTITY_PROOF_FAILED")

        return AgentRuntimeQualificationResult(
            status="AGENT_RUNTIME_PASS",
            mission_id=mission_id,
            coordinator_instance_id=coordinator_id,
            reason=None,
            r1_event_count=len(_event_names(truth, mission_id)),
            r1_proof_event_ids=proof_ids,
            worker_instance_ids=tuple(worker_ids),
            dsh_session_ids=tuple(sessions),
            first_gate_status=first_status,
            second_gate_status=second_status,
        )
    except AgentRuntimeError as exc:
        return AgentRuntimeQualificationResult(
            status="AGENT_RUNTIME_FAIL",
            mission_id=mission_id,
            coordinator_instance_id=coordinator_id,
            reason=str(exc),
            r1_event_count=len(_event_names(truth, mission_id)),
            r1_proof_event_ids=(),
            worker_instance_ids=tuple(worker_ids),
            dsh_session_ids=tuple(sessions),
            first_gate_status=first_status,
            second_gate_status=second_status,
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc6_release.agent_qualification")
    parser.add_argument("--home", default=os.environ.get("PFC_AITEST_HOME", "."))
    parser.add_argument("--dsh")
    parser.add_argument("--patch")
    parser.add_argument("--coordinator-instance-id")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    result = run_real_vertical_slice(
        home=args.home,
        dsh_bin=args.dsh,
        patch_path=args.patch,
        coordinator_instance_id=args.coordinator_instance_id,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    if result.status == "AGENT_RUNTIME_PASS":
        return 0
    if result.status == "NOT_PROVEN":
        return 4
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
