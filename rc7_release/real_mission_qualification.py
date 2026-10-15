from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# Imports are intentionally retained for their R1 event registration side effects
# before TruthRuntime rebuilds a field event stream.
import rc6_runtime.agent_runtime  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.dsh_proof import DshR1ProofReader, DshProofError
from rc7_runtime.runtime_identity import RUNTIME_IDENTITY_KIND, RUNTIME_IDENTITY_SOURCE
from rc7_runtime.session_continuity import SESSION_ARTIFACT, SESSION_EVENT, install_session_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


SCHEMA_VERSION = "pfc.aitest.rc7.real-mission-qualification.v1"
GATE = "REAL_MISSION_PASS"
ALLOWED_SUFFICIENCY = {"SUFFICIENT", "SUFFICIENT_WITH_RESIDUAL_RISK"}
TERMINAL_DEFECT_STATES = {"CLOSED", "DUPLICATE", "NOT_A_DEFECT"}
DOMAIN_NODES = {
    "REQUIREMENT_ANALYSIS",
    "CODE_ANALYSIS",
    "TEST_DESIGN",
    "SCRIPT_READINESS",
    "DEFECT",
}
FORBIDDEN_DOMAIN_WORKER_MARKERS = (
    "director",
    "coordinator",
    "mission-controller",
    "mission_controller",
    "mission-evidence-builder",
    "mission_evidence_builder",
)
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class RealMissionQualificationError(RuntimeError):
    pass


def _write_json(path: str, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _add(blockers: List[str], condition: bool, reason: str) -> bool:
    if not condition:
        blockers.append(reason)
        return False
    return True


def _event_payloads(truth: TruthRuntime, event_type: str, mission_id: str) -> List[Tuple[int, Dict[str, Any]]]:
    rows = []
    for raw in truth.store.iter_raw():
        if raw.get("event_type") != event_type:
            continue
        payload = raw.get("payload")
        if not isinstance(payload, dict) or payload.get("mission_id") != mission_id:
            continue
        seq = raw.get("seq")
        if not isinstance(seq, int):
            continue
        rows.append((seq, payload))
    return sorted(rows, key=lambda item: item[0])


def _runtime_identity(
    truth: TruthRuntime,
    *,
    mission_id: str,
    source_commit: str,
    blockers: List[str],
) -> Optional[str]:
    expected = "git://%s" % source_commit
    matches = [
        row
        for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == RUNTIME_IDENTITY_KIND
        and row.get("source_ref") == RUNTIME_IDENTITY_SOURCE
    ]
    exact = [row for row in matches if row.get("content_ref") == expected]
    _add(blockers, len(exact) == 1, "RUNTIME_IDENTITY_CURRENT_COMMIT_NOT_PROVEN")
    if len(exact) != 1:
        return None
    conflicting = [row for row in matches if row.get("content_ref") != expected]
    _add(blockers, not conflicting, "RUNTIME_IDENTITY_CONFLICTING_COMMIT")
    return str(exact[0]["evidence_id"])


def _mission_evaluation(
    truth: TruthRuntime,
    *,
    mission: Mapping[str, Any],
    blockers: List[str],
) -> Optional[Mapping[str, Any]]:
    evaluation_id = mission.get("latest_evaluation_id")
    _add(blockers, isinstance(evaluation_id, str) and bool(evaluation_id), "MISSION_LATEST_EVALUATION_MISSING")
    if not isinstance(evaluation_id, str) or not evaluation_id:
        return None
    rows = truth.query("rc7_evaluation", evaluation_id=evaluation_id)
    _add(blockers, len(rows) == 1, "MISSION_LATEST_EVALUATION_NOT_UNIQUE")
    if len(rows) != 1:
        return None
    row = rows[0]
    _add(blockers, row.get("mission_id") == mission.get("mission_id"), "MISSION_EVALUATION_IDENTITY_MISMATCH")
    _add(blockers, row.get("node") == "MISSION_EVALUATION", "MISSION_EVALUATION_NODE_INVALID")
    _add(blockers, row.get("result") == "PASS", "MISSION_EVALUATION_NOT_PASS")
    dimensions = row.get("dimensions")
    if not isinstance(dimensions, dict):
        blockers.append("MISSION_EVALUATION_DIMENSIONS_MISSING")
        return row
    _add(
        blockers,
        dimensions.get("sufficiency_state") == mission.get("sufficiency_state"),
        "MISSION_SUFFICIENCY_EVALUATION_MISMATCH",
    )
    metrics = dimensions.get("metrics")
    if mission.get("sufficiency_state") == "SUFFICIENT_WITH_RESIDUAL_RISK":
        _add(
            blockers,
            isinstance(metrics, dict) and metrics.get("residual_risks_pending_acceptance") == 0,
            "RESIDUAL_RISK_NOT_DISPOSITIONED",
        )
    return row


def _worker_proof(
    truth: TruthRuntime,
    *,
    mission_id: str,
    blockers: List[str],
) -> Tuple[Dict[str, Any], List[str]]:
    evidence_rows = [
        row
        for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == "DSH_RUNTIME_PROOF"
        and isinstance(row.get("source_ref"), str)
        and str(row.get("source_ref")).startswith("dsh://worker/")
    ]
    worker_ids = sorted(
        {
            str(row["source_ref"])[len("dsh://worker/"):]
            for row in evidence_rows
            if str(row["source_ref"])[len("dsh://worker/"):]
        }
    )
    _add(blockers, bool(worker_ids), "REAL_DSH_WORKER_EVIDENCE_MISSING")

    task_rows = truth.query("rc7_task", mission_id=mission_id)
    domain_tasks = [
        row
        for row in task_rows
        if row.get("node") in DOMAIN_NODES
        and row.get("task_type") != "EVALUATE"
        and row.get("state") == "PASS"
    ]
    _add(blockers, bool(domain_tasks), "PASS_DOMAIN_TASK_MISSING")

    dsh_subject_tasks = set()
    evidence_ids = []
    for row in evidence_rows:
        evidence_ids.append(str(row["evidence_id"]))
        for subject in row.get("subject_refs", []):
            if isinstance(subject, str):
                dsh_subject_tasks.add(subject)

    director_did_domain_work = False
    for task in domain_tasks:
        task_id = str(task.get("task_id", ""))
        owner = str(task.get("lease_owner") or "")
        lowered = owner.lower()
        if not owner or any(marker in lowered for marker in FORBIDDEN_DOMAIN_WORKER_MARKERS):
            director_did_domain_work = True
        if task_id not in dsh_subject_tasks:
            blockers.append("DOMAIN_TASK_DSH_RUNTIME_PROOF_MISSING:%s" % task_id)
        if owner and owner not in worker_ids:
            blockers.append("DOMAIN_TASK_LEASE_NOT_DSH_WORKER:%s" % task_id)

    reader = DshR1ProofReader()
    receipts = []
    workers_with_calls = []
    for worker_id in worker_ids:
        try:
            proofs = reader.tool_calls(
                truth,
                mission_id=mission_id,
                worker_instance_id=worker_id,
            )
        except DshProofError as exc:
            blockers.append("DSH_TOOL_PROOF_INVALID:%s:%s" % (worker_id, exc))
            continue
        if proofs:
            workers_with_calls.append(worker_id)
            receipts.extend(proof.call_ref for proof in proofs)
    _add(blockers, bool(receipts), "REAL_DSH_TOOL_CALL_RECEIPTS_MISSING")
    _add(blockers, not director_did_domain_work, "DIRECTOR_OR_CONTROL_PLANE_DID_DOMAIN_WORK")

    return (
        {
            "real_dsh": bool(worker_ids) and bool(receipts),
            "worker_ids": worker_ids,
            "workers_with_real_tool_calls": sorted(workers_with_calls),
            "tool_receipts": sorted(set(receipts)),
            "director_did_domain_work": director_did_domain_work,
        },
        evidence_ids,
    )


def _session_continuity(
    truth: TruthRuntime,
    *,
    mission_id: str,
    blockers: List[str],
) -> Dict[str, Any]:
    histories: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for seq, payload in _event_payloads(truth, SESSION_EVENT, mission_id):
        handoff_id = payload.get("handoff_id")
        if isinstance(handoff_id, str) and handoff_id:
            histories.setdefault(handoff_id, []).append((seq, payload))

    valid = []
    for handoff_id, history in histories.items():
        prepared = [item for item in history if item[1].get("status") == "PREPARED"]
        activated = [item for item in history if item[1].get("status") == "ACTIVATED"]
        if not prepared or not activated:
            continue
        p_seq, p = prepared[-1]
        a_seq, a = activated[-1]
        if a_seq <= p_seq:
            continue
        if p.get("task_id") != a.get("task_id") or p.get("mission_id") != a.get("mission_id"):
            continue
        predecessor = p.get("predecessor_session_ref")
        successor = a.get("successor_session_ref")
        if not isinstance(predecessor, str) or not isinstance(successor, str) or predecessor == successor:
            continue
        task_rows = truth.query("rc7_task", task_id=str(a.get("task_id")))
        if len(task_rows) != 1 or task_rows[0].get("mission_id") != mission_id:
            continue
        valid.append((handoff_id, str(a.get("task_id")), predecessor, successor, p_seq, a_seq))

    _add(blockers, bool(valid), "SESSION_A_TO_B_ROTATION_NOT_PROVEN")
    if not valid:
        return {
            "session_ids": [],
            "same_mission": False,
            "same_task_continuity": False,
            "rotation_observed": False,
        }
    handoff_id, task_id, predecessor, successor, prepared_seq, activated_seq = valid[-1]
    return {
        "handoff_id": handoff_id,
        "task_id": task_id,
        "session_ids": [predecessor, successor],
        "same_mission": True,
        "same_task_continuity": True,
        "rotation_observed": True,
        "prepared_r1_seq": prepared_seq,
        "activated_r1_seq": activated_seq,
    }


def _gap_history(truth: TruthRuntime, gap_id: str) -> List[Mapping[str, Any]]:
    return truth.projection.history("rc7_gap", gap_id)


def _artifact_revision_pair(
    truth: TruthRuntime,
    *,
    artifact_ids: Iterable[str],
) -> Optional[Tuple[str, int, int]]:
    for artifact_id in artifact_ids:
        history = truth.projection.history("rc7_artifact", artifact_id)
        if len(history) < 2:
            continue
        versions = sorted({int(row.get("version", 0)) for row in history})
        if len(versions) >= 2:
            return artifact_id, versions[0], versions[-1]
    return None


def _gap_repair(
    truth: TruthRuntime,
    *,
    mission_id: str,
    blockers: List[str],
) -> Tuple[Dict[str, Any], List[str]]:
    resolved = [
        row
        for row in truth.query("rc7_gap", mission_id=mission_id)
        if row.get("state") == "RESOLVED" and row.get("category") != "PRODUCT_DEFECT"
    ]
    candidates = []
    for gap in resolved:
        gap_id = str(gap["gap_id"])
        states = [str(row.get("state")) for row in _gap_history(truth, gap_id)]
        if not all(state in states for state in ("REPAIRING", "EVIDENCE_PENDING", "RESOLVED")):
            continue
        repair_tasks = [
            row
            for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("task_type") == "REPAIR"
            and row.get("state") == "PASS"
            and gap_id in row.get("gap_refs", [])
        ]
        resolution_id = gap.get("resolution_evaluation_id")
        evaluations = truth.query("rc7_evaluation", evaluation_id=resolution_id) if isinstance(resolution_id, str) else []
        if len(repair_tasks) != 1 or len(evaluations) != 1:
            continue
        resolution = evaluations[0]
        source_tasks = [
            row
            for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("task_type") != "REPAIR"
            and row.get("node") == gap.get("source_node")
            and gap_id in row.get("gap_refs", [])
            and row.get("evaluation_id") == resolution_id
            and row.get("state") == "PASS"
        ]
        if len(source_tasks) != 1:
            continue
        source_task = source_tasks[0]
        pair = _artifact_revision_pair(
            truth,
            artifact_ids=resolution.get("artifact_refs", []),
        )
        if pair is None:
            continue
        if resolution.get("evaluator_ref") == source_task.get("lease_owner"):
            continue
        candidates.append((gap, repair_tasks[0], resolution, source_task, pair))

    _add(blockers, bool(candidates), "GAP_REPAIR_REEVALUATION_REVISION_LINEAGE_NOT_PROVEN")
    if not candidates:
        return (
            {
                "gap_id": "",
                "repair_task_id": "",
                "independent_evaluation_ref": "",
                "artifact_before_revision": None,
                "artifact_after_revision": None,
                "gap_closed_by_independent_evaluation": False,
            },
            [],
        )
    gap, repair, resolution, source_task, pair = candidates[-1]
    artifact_id, before, after = pair
    refs = []
    for value in list(gap.get("evidence_refs", [])) + list(resolution.get("evidence_refs", [])):
        if isinstance(value, str) and value and value not in refs:
            refs.append(value)
    return (
        {
            "gap_id": str(gap["gap_id"]),
            "repair_task_id": str(repair["task_id"]),
            "source_task_id": str(source_task["task_id"]),
            "artifact_id": artifact_id,
            "artifact_before_revision": before,
            "artifact_after_revision": after,
            "independent_evaluation_ref": str(resolution["evaluation_id"]),
            "gap_closed_by_independent_evaluation": True,
        },
        refs,
    )


def _defect_flow(
    truth: TruthRuntime,
    *,
    mission_id: str,
    blockers: List[str],
) -> Tuple[Dict[str, Any], List[str]]:
    product_gaps = [
        row
        for row in truth.query("rc7_gap", mission_id=mission_id)
        if row.get("category") == "PRODUCT_DEFECT"
    ]
    trusted_product_failures = [
        row
        for row in truth.query("rc7_evaluation", mission_id=mission_id)
        if row.get("node") == "EXECUTION"
        and isinstance(row.get("dimensions"), dict)
        and row["dimensions"].get("failure_class") == "PRODUCT"
        and row["dimensions"].get("test_result") == "FAIL"
    ]
    if not product_gaps and not trusted_product_failures:
        return {"status": "NOT_TRIGGERED_NO_TRUSTED_FAIL", "defect_ids": []}, []
    _add(blockers, bool(product_gaps), "TRUSTED_PRODUCT_FAIL_WITHOUT_PRODUCT_GAP")
    unresolved = [row for row in product_gaps if row.get("state") != "RESOLVED"]
    _add(blockers, not unresolved, "PRODUCT_DEFECT_GAP_NOT_RESOLVED")
    defects = truth.query("rc7_defect", mission_id=mission_id)
    terminal = [row for row in defects if row.get("state") in TERMINAL_DEFECT_STATES]
    _add(blockers, bool(terminal), "PRODUCT_DEFECT_TERMINAL_DISPOSITION_MISSING")
    refs = []
    for row in terminal:
        for value in row.get("evidence_refs", []):
            if isinstance(value, str) and value and value not in refs:
                refs.append(value)
    return {
        "status": "VERIFIED" if product_gaps and not unresolved and terminal else "UNVERIFIED",
        "defect_ids": sorted(str(row["defect_id"]) for row in terminal),
        "terminal_states": sorted({str(row["state"]) for row in terminal}),
    }, refs


def evaluate_real_mission(
    *,
    r1_path: str,
    mission_id: str,
    source_commit: str,
) -> Dict[str, Any]:
    commit = source_commit.strip().lower() if isinstance(source_commit, str) else ""
    if not _SHA_RE.match(commit):
        raise ValueError("INVALID_SOURCE_COMMIT")
    if not mission_id:
        raise ValueError("MISSION_ID_REQUIRED")

    install_rc7_truth_overlay()
    install_session_overlay()
    truth = TruthRuntime(Path(r1_path).resolve())
    blockers: List[str] = []

    missions = truth.query("rc7_mission", mission_id=mission_id)
    _add(blockers, len(missions) == 1, "MISSION_NOT_FOUND_OR_NOT_UNIQUE")
    mission = missions[0] if len(missions) == 1 else {}
    _add(blockers, mission.get("state") == "CONVERGED", "MISSION_NOT_CONVERGED")
    _add(blockers, mission.get("sufficiency_state") in ALLOWED_SUFFICIENCY, "MISSION_TEST_SUFFICIENCY_INVALID")
    _add(blockers, not mission.get("open_gap_ids"), "MISSION_OPEN_GAPS_REMAIN")
    _add(blockers, not mission.get("active_task_ids"), "MISSION_ACTIVE_TASKS_REMAIN")

    identity_id = _runtime_identity(
        truth,
        mission_id=mission_id,
        source_commit=commit,
        blockers=blockers,
    )
    mission_eval = _mission_evaluation(truth, mission=mission, blockers=blockers) if mission else None
    worker_proof, worker_evidence = _worker_proof(truth, mission_id=mission_id, blockers=blockers)
    session = _session_continuity(truth, mission_id=mission_id, blockers=blockers)
    repair, repair_evidence = _gap_repair(truth, mission_id=mission_id, blockers=blockers)
    defect, defect_evidence = _defect_flow(truth, mission_id=mission_id, blockers=blockers)

    evidence_refs: List[str] = []
    if identity_id:
        evidence_refs.append(identity_id)
    if mission_eval:
        for value in mission_eval.get("evidence_refs", []):
            if isinstance(value, str) and value and value not in evidence_refs:
                evidence_refs.append(value)
    for value in worker_evidence + repair_evidence + defect_evidence:
        if value and value not in evidence_refs:
            evidence_refs.append(value)
    formal_execution = [
        row
        for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == "RUNTIME_EXECUTION_RECORD"
        and row.get("source_ref") == "runtime://formal-execution"
    ]
    _add(blockers, bool(formal_execution), "FORMAL_RUNTIME_EXECUTION_EVIDENCE_MISSING")
    for row in formal_execution:
        value = str(row.get("evidence_id", ""))
        if value and value not in evidence_refs:
            evidence_refs.append(value)

    residual_dispositioned = True
    if mission.get("sufficiency_state") == "SUFFICIENT_WITH_RESIDUAL_RISK" and mission_eval:
        metrics = mission_eval.get("dimensions", {}).get("metrics", {})
        residual_dispositioned = isinstance(metrics, dict) and metrics.get("residual_risks_pending_acceptance") == 0

    status = "PASS" if not blockers else "HOLD"
    return {
        "schema_version": SCHEMA_VERSION,
        "gate": GATE,
        "status": status,
        "qualification_kind": "BANK_REAL_MISSION",
        "source_truth": "R1_EVENT_STREAM_PLUS_RUNTIME_BUILD_IDENTITY",
        "source_commit": commit,
        "mission_id": mission_id,
        "mission_state": mission.get("state") if mission else None,
        "test_sufficiency": mission.get("sufficiency_state") if mission else None,
        "residual_risk_dispositioned": residual_dispositioned,
        "r1_event_stream_ref": "file://%s" % Path(r1_path).resolve(),
        "evidence_refs": evidence_refs,
        "worker_proof": worker_proof,
        "session_continuity": session,
        "gap_repair": repair,
        "defect_flow": defect,
        "blocking_reasons": blockers,
        "completion_authority": "MISSION_SUFFICIENCY_PLUS_REALITY_EVIDENCE",
        "plan_complete_is_test_sufficient": False,
        "workflow_complete_is_mission_complete": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.real_mission_qualification")
    parser.add_argument("--r1", required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_real_mission(
        r1_path=args.r1,
        mission_id=args.mission_id,
        source_commit=args.source_commit,
    )
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.require_pass and result["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
