"""Independent BANK N8 evaluator for non-direct owner repair candidates.

The DSH repair worker is a producer only.  It may perform the leased repair and
return evidence, but it cannot mark its own task PASS.  This evaluator binds the
candidate to the current durable N8 work order, resolves worker evidence aliases
back to canonical R1 Evidence ids, proves a real before/after delta, and only
then accepts the REPAIR task.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from .autonomous_recovery_orchestrator import N8RecoveryOrchestrator
from .candidate_payload import CandidatePayloadError, CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evaluation, EvaluationResult, Task, TaskStatus


class BankN8OwnerRepairEvaluationError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BankN8OwnerRepairEvaluationError(code)
    return text


def _verified_file_payload(row: Mapping[str, Any], code: str) -> Mapping[str, Any]:
    ref = str(row.get("content_ref") or "")
    if not ref.startswith("file://"):
        raise BankN8OwnerRepairEvaluationError(code + "_FILE_REQUIRED")
    path = Path(ref[len("file://"):]).expanduser().resolve()
    if not path.is_file():
        raise BankN8OwnerRepairEvaluationError(code + "_FILE_MISSING")
    body = path.read_bytes()
    expected = str(row.get("content_hash") or "")
    actual = "sha256:" + hashlib.sha256(body).hexdigest()
    if expected != actual:
        raise BankN8OwnerRepairEvaluationError(code + "_HASH_MISMATCH")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BankN8OwnerRepairEvaluationError(code + "_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise BankN8OwnerRepairEvaluationError(code + "_OBJECT_REQUIRED")
    return payload


class BankN8OwnerRepairEvaluator:
    """Deterministic independent gate for DSH-produced N8 owner repairs."""

    EVALUATOR_REF = "rc7-n8-owner-repair-independent-gate"

    def __init__(self) -> None:
        self.reader = CandidatePayloadReader()

    @staticmethod
    def _work_order(control: ClosedLoopControlPlane, task: Task) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
        matches = []
        for evidence in control.truth.query("rc7_evidence", mission_id=control.mission_id):
            if evidence.get("kind") != N8RecoveryOrchestrator.WORK_ORDER_TYPE:
                continue
            refs = set(str(x) for x in evidence.get("subject_refs") or [])
            if task.task_id not in refs:
                continue
            payload = _verified_file_payload(evidence, "N8_OWNER_REPAIR_WORK_ORDER")
            if payload.get("repair_task_id") != task.task_id:
                raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_TASK_BINDING_MISMATCH")
            matches.append((evidence, payload))
        if len(matches) != 1:
            raise BankN8OwnerRepairEvaluationError(
                "N8_OWNER_REPAIR_WORK_ORDER_NOT_UNIQUE:%d" % len(matches)
            )
        evidence, payload = matches[0]
        if payload.get("mission_id") != control.mission_id:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_WORK_ORDER_MISSION_MISMATCH")
        if payload.get("gap_id") not in task.gap_refs:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_GAP_BINDING_MISMATCH")
        plan = payload.get("plan")
        if not isinstance(plan, dict) or plan.get("target_node") != task.node:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_NODE_BINDING_MISMATCH")
        if plan.get("mode") not in {"REPREPARE_THEN_RETRY", "UPSTREAM_REPAIR_THEN_RETRY"}:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_NON_DIRECT_PLAN_REQUIRED")
        if plan.get("terminal") is not False or plan.get("retry_allowed") is not True:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_RETRYABLE_PLAN_REQUIRED")
        return evidence, payload

    @staticmethod
    def _candidate_evidence_aliases(
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
    ) -> Tuple[Dict[str, str], Tuple[str, ...]]:
        rows = control.truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(rows) != 1:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_CANDIDATE_ARTIFACT_NOT_UNIQUE")
        row = rows[0]
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_CANDIDATE_EVIDENCE_REQUIRED")
        aliases: Dict[str, str] = {}
        ambiguous = set()
        canonical = []
        for evidence_id in refs:
            if not isinstance(evidence_id, str) or not evidence_id:
                continue
            evidence_rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(evidence_rows) != 1:
                raise BankN8OwnerRepairEvaluationError(
                    "N8_OWNER_REPAIR_CANDIDATE_EVIDENCE_NOT_UNIQUE:%s" % evidence_id
                )
            evidence = evidence_rows[0]
            if evidence.get("mission_id") != control.mission_id:
                raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_CANDIDATE_EVIDENCE_MISSION_MISMATCH")
            canonical.append(evidence_id)
            for alias in (evidence_id, evidence.get("content_ref"), evidence.get("source_ref")):
                if not isinstance(alias, str) or not alias:
                    continue
                previous = aliases.get(alias)
                if previous is not None and previous != evidence_id:
                    ambiguous.add(alias)
                else:
                    aliases[alias] = evidence_id
        for alias in ambiguous:
            aliases.pop(alias, None)
        if not canonical:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_NO_CANONICAL_EVIDENCE")
        return aliases, tuple(dict.fromkeys(canonical))

    @staticmethod
    def _resolve_delta_refs(
        control: ClosedLoopControlPlane,
        *,
        aliases: Mapping[str, str],
        raw_refs: object,
    ) -> Tuple[str, ...]:
        if not isinstance(raw_refs, list) or not raw_refs:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_DELTA_EVIDENCE_REFS_REQUIRED")
        output = []
        for raw in raw_refs:
            alias = _required(raw, "N8_OWNER_REPAIR_DELTA_EVIDENCE_REF_REQUIRED")
            canonical = aliases.get(alias)
            if canonical is None:
                raise BankN8OwnerRepairEvaluationError(
                    "N8_OWNER_REPAIR_DELTA_EVIDENCE_NOT_DURABLE:%s" % alias
                )
            rows = control.truth.query("rc7_evidence", evidence_id=canonical)
            if len(rows) != 1:
                raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_DELTA_EVIDENCE_NOT_UNIQUE")
            if rows[0].get("kind") != "REPAIR_DELTA_EVIDENCE":
                raise BankN8OwnerRepairEvaluationError(
                    "N8_OWNER_REPAIR_DELTA_EVIDENCE_KIND_INVALID:%s" % canonical
                )
            output.append(canonical)
        return tuple(dict.fromkeys(output))

    def evaluate_and_apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
    ) -> Evaluation:
        task = control.scheduler.task(task_id)
        if task.task_type != "REPAIR" or task.node in {"EXECUTION", "HUMAN_GATE", "DEFECT"}:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_NON_DIRECT_TASK_REQUIRED")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_CANDIDATE_REQUIRED")
        if artifact_id not in task.output_artifact_refs:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_ARTIFACT_NOT_TASK_OUTPUT")

        work_order_evidence, work_order = self._work_order(control, task)
        try:
            candidate = self.reader.load(
                control.truth,
                artifact_id,
                expected_mission_id=control.mission_id,
                expected_task_id=task_id,
            )
        except CandidatePayloadError as exc:
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_CANDIDATE_INVALID:%s" % exc) from exc
        semantic = dict(candidate.semantic_payload)
        work_order_id = _required(
            semantic.get("repair_work_order_id"),
            "N8_OWNER_REPAIR_WORK_ORDER_ID_REQUIRED",
        )
        if work_order_id != work_order.get("work_order_id"):
            raise BankN8OwnerRepairEvaluationError("N8_OWNER_REPAIR_WORK_ORDER_ID_MISMATCH")
        before = _required(
            semantic.get("repair_before_fingerprint"),
            "N8_OWNER_REPAIR_BEFORE_FINGERPRINT_REQUIRED",
        )
        after = _required(
            semantic.get("repair_after_fingerprint"),
            "N8_OWNER_REPAIR_AFTER_FINGERPRINT_REQUIRED",
        )
        if before == after:
            raise BankN8OwnerRepairEvaluationError("SAME_FAILURE_SIGNATURE_NO_DELTA")

        aliases, _candidate_evidence = self._candidate_evidence_aliases(
            control,
            artifact_id=artifact_id,
        )
        delta_refs = self._resolve_delta_refs(
            control,
            aliases=aliases,
            raw_refs=semantic.get("repair_delta_evidence_refs"),
        )
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-N8-OWNER-REPAIR",
                control.mission_id,
                task_id,
                artifact_id,
                candidate.content_hash,
                after,
            ),
            mission_id=control.mission_id,
            node=task.node,
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=self.EVALUATOR_REF,
            dimensions={
                "repair_work_order_id": work_order_id,
                "repair_before_fingerprint": before,
                "repair_after_fingerprint": after,
                "repair_delta_refs": list(delta_refs),
                "n8_owner_repair_verified": True,
                "worker_self_acceptance_forbidden": True,
            },
            gap_refs=[],
            evidence_refs=list(dict.fromkeys(list(delta_refs) + [str(work_order_evidence["evidence_id"])])),
        )
        control.accept_evaluation(task_id, evaluation=evaluation)
        return evaluation
