from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCHEMA_VERSION = "pfc.aitest.rc7.final-qualification.v1"
REQUIRED_GATES = (
    "ENGINEERING_PASS",
    "ADMIN_PLATFORM_PASS",
    "REAL_MISSION_PASS",
    "DELIVERY_PASS",
)
ALLOWED_SUFFICIENCY = {"SUFFICIENT", "SUFFICIENT_WITH_RESIDUAL_RISK"}
# Final PASS is intentionally narrower than the base real-Mission diagnostic.
# The release gate accepts only the strict R1-derived task-scoped worker proof.
ALLOWED_REALITY_KINDS = {"BANK_REAL_MISSION_STRICT_TASK_RECEIPTS"}
ALLOWED_DEFECT_DISPOSITIONS = {"VERIFIED", "NOT_TRIGGERED_NO_TRUSTED_FAIL"}
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _load_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.is_file():
        return None
    with file_path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ValueError("QUALIFICATION_EVIDENCE_MUST_BE_OBJECT:%s" % path)
    return value


def _common_errors(report: Optional[Dict[str, Any]], gate: str, source_commit: str) -> List[str]:
    if report is None:
        return ["%s:EVIDENCE_MISSING" % gate]
    errors = []
    if report.get("gate") != gate:
        errors.append("%s:GATE_MISMATCH" % gate)
    if report.get("status") != "PASS":
        errors.append("%s:STATUS_NOT_PASS" % gate)
    if report.get("source_commit") != source_commit:
        errors.append("%s:SOURCE_COMMIT_MISMATCH" % gate)
    return errors


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def _validate_real_mission(report: Optional[Dict[str, Any]], source_commit: str) -> List[str]:
    gate = "REAL_MISSION_PASS"
    errors = _common_errors(report, gate, source_commit)
    if report is None:
        return errors

    if report.get("qualification_kind") not in ALLOWED_REALITY_KINDS:
        errors.append("%s:REALITY_KIND_INVALID" % gate)
    if not isinstance(report.get("mission_id"), str) or not report.get("mission_id", "").strip():
        errors.append("%s:MISSION_ID_MISSING" % gate)
    if report.get("mission_state") != "CONVERGED":
        errors.append("%s:MISSION_NOT_CONVERGED" % gate)

    sufficiency = report.get("test_sufficiency")
    if sufficiency not in ALLOWED_SUFFICIENCY:
        errors.append("%s:TEST_SUFFICIENCY_INVALID" % gate)
    if sufficiency == "SUFFICIENT_WITH_RESIDUAL_RISK" and report.get("residual_risk_dispositioned") is not True:
        errors.append("%s:RESIDUAL_RISK_NOT_DISPOSITIONED" % gate)

    if not isinstance(report.get("r1_event_stream_ref"), str) or not report.get("r1_event_stream_ref", "").strip():
        errors.append("%s:R1_EVENT_STREAM_REF_MISSING" % gate)
    if not _nonempty_list(report.get("evidence_refs")):
        errors.append("%s:EVIDENCE_REFS_MISSING" % gate)

    worker = report.get("worker_proof")
    if not isinstance(worker, dict):
        errors.append("%s:WORKER_PROOF_MISSING" % gate)
    else:
        if worker.get("real_dsh") is not True:
            errors.append("%s:REAL_DSH_NOT_PROVEN" % gate)
        if not _nonempty_list(worker.get("tool_receipts")):
            errors.append("%s:TOOL_RECEIPTS_MISSING" % gate)
        if worker.get("director_did_domain_work") is not False:
            errors.append("%s:DIRECTOR_DOMAIN_WORK_NOT_EXCLUDED" % gate)

    task_proof = report.get("task_scoped_worker_proof")
    if not isinstance(task_proof, dict) or not task_proof:
        errors.append("%s:TASK_SCOPED_WORKER_PROOF_MISSING" % gate)
    else:
        for task_id, proof in sorted(task_proof.items()):
            if not isinstance(task_id, str) or not task_id.strip() or not isinstance(proof, dict):
                errors.append("%s:TASK_SCOPED_WORKER_PROOF_INVALID" % gate)
                continue
            if proof.get("proven") is not True:
                errors.append("%s:TASK_SCOPED_WORKER_NOT_PROVEN:%s" % (gate, task_id))
            if not isinstance(proof.get("lease_owner"), str) or not proof.get("lease_owner", "").strip():
                errors.append("%s:TASK_LEASE_OWNER_MISSING:%s" % (gate, task_id))
            if proof.get("owner_dsh_runtime_proven") is not True:
                errors.append("%s:TASK_DSH_OWNER_NOT_PROVEN:%s" % (gate, task_id))
            if not _nonempty_list(proof.get("tool_receipts")):
                errors.append("%s:TASK_TOOL_RECEIPT_MISSING:%s" % (gate, task_id))

    session = report.get("session_continuity")
    if not isinstance(session, dict):
        errors.append("%s:SESSION_CONTINUITY_MISSING" % gate)
    else:
        session_ids = session.get("session_ids")
        if not _nonempty_list(session_ids) or len(set(session_ids)) < 2:
            errors.append("%s:SESSION_ROTATION_NOT_PROVEN" % gate)
        if session.get("same_mission") is not True:
            errors.append("%s:SAME_MISSION_CONTINUITY_NOT_PROVEN" % gate)
        if session.get("same_task_continuity") is not True:
            errors.append("%s:SAME_TASK_CONTINUITY_NOT_PROVEN" % gate)
        if session.get("rotation_observed") is not True:
            errors.append("%s:ROTATION_EVENT_NOT_PROVEN" % gate)

    repair = report.get("gap_repair")
    if not isinstance(repair, dict):
        errors.append("%s:GAP_REPAIR_PROOF_MISSING" % gate)
    else:
        required_strings = ("gap_id", "repair_task_id", "independent_evaluation_ref")
        for key in required_strings:
            if not isinstance(repair.get(key), str) or not repair.get(key, "").strip():
                errors.append("%s:GAP_REPAIR_%s_MISSING" % (gate, key.upper()))
        before = repair.get("artifact_before_revision")
        after = repair.get("artifact_after_revision")
        if before is None or after is None or before == after:
            errors.append("%s:ARTIFACT_REVISION_DID_NOT_ADVANCE" % gate)
        if repair.get("gap_closed_by_independent_evaluation") is not True:
            errors.append("%s:GAP_NOT_CLOSED_BY_EVALUATION" % gate)

    defect = report.get("defect_flow")
    if not isinstance(defect, dict) or defect.get("status") not in ALLOWED_DEFECT_DISPOSITIONS:
        errors.append("%s:DEFECT_FLOW_UNDISPOSITIONED" % gate)

    return errors


def _validate_delivery(report: Optional[Dict[str, Any]], source_commit: str) -> List[str]:
    gate = "DELIVERY_PASS"
    errors = _common_errors(report, gate, source_commit)
    if report is None:
        return errors

    if not isinstance(report.get("package_name"), str) or not report.get("package_name", "").strip():
        errors.append("%s:PACKAGE_NAME_MISSING" % gate)
    digest = report.get("package_sha256")
    if not isinstance(digest, str) or not re.match(r"^[0-9a-fA-F]{64}$", digest):
        errors.append("%s:PACKAGE_SHA256_INVALID" % gate)
    for key in (
        "clean_windows_unpack",
        "package_local_python_verify",
        "package_local_codegraph_verify",
        "package_verify",
        "package_entrypoint_verify",
        "admin_startup_verify",
    ):
        if report.get(key) != "PASS":
            errors.append("%s:%s_NOT_PASS" % (gate, key.upper()))
    codegraph_hash = report.get("package_local_codegraph_sha256")
    if not isinstance(codegraph_hash, str) or not re.match(r"^[0-9a-fA-F]{64}$", codegraph_hash):
        errors.append("%s:PACKAGE_LOCAL_CODEGRAPH_SHA256_INVALID" % gate)
    return errors


def evaluate_final_qualification(
    source_commit: str,
    engineering: Optional[Dict[str, Any]],
    admin: Optional[Dict[str, Any]],
    real_mission: Optional[Dict[str, Any]],
    delivery: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not _SHA_RE.match(source_commit or ""):
        raise ValueError("INVALID_SOURCE_COMMIT")

    gate_errors = {
        "ENGINEERING_PASS": _common_errors(engineering, "ENGINEERING_PASS", source_commit),
        "ADMIN_PLATFORM_PASS": _common_errors(admin, "ADMIN_PLATFORM_PASS", source_commit),
        "REAL_MISSION_PASS": _validate_real_mission(real_mission, source_commit),
        "DELIVERY_PASS": _validate_delivery(delivery, source_commit),
    }
    gates = {gate: "PASS" if not gate_errors[gate] else "HOLD" for gate in REQUIRED_GATES}
    blockers = []
    for gate in REQUIRED_GATES:
        blockers.extend(gate_errors[gate])

    status = "PASS" if not blockers else "HOLD"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_truth": "GIT_COMMIT",
        "source_commit": source_commit,
        "gates": gates,
        "blocking_reasons": blockers,
        "completion_authority": "MISSION_SUFFICIENCY_PLUS_REALITY_EVIDENCE",
        "durable_truth": "R1_EVENT_STREAM",
        "plan_complete_is_test_sufficient": False,
        "workflow_complete_is_mission_complete": False,
    }


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rc7_release.final_qualification")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--engineering")
    parser.add_argument("--admin")
    parser.add_argument("--real-mission")
    parser.add_argument("--delivery")
    parser.add_argument("--output")
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args(argv)

    result = evaluate_final_qualification(
        source_commit=args.source_commit,
        engineering=_load_json(args.engineering),
        admin=_load_json(args.admin),
        real_mission=_load_json(args.real_mission),
        delivery=_load_json(args.delivery),
    )
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.require_pass and result["status"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
