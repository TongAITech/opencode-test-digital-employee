"""Node-level adoption gate for N1-N4 autonomous-loop migration.

Existing producer/evaluator Tasks remain durable sub-task truth.  A producer
Task PASS is therefore *not* final node PASS.  This adapter requires a current
NodeIteration, a persisted PASS evaluation owned by the expected specialist
node, an immutable NodeDeliveryPackage and a separate Director decision before
node-level PASS may exist in R1.

This allows RC7.1 to preserve mature requirement/code/test-design evaluators
while enforcing RC-AUTONOMOUS-TEST-LOOP@1.0.0 without a flag-day rewrite.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .autonomous_contract import NodeDeliveryPackage, NodeLoopState, require_node
from .autonomous_events import AutonomousEvent
from .autonomous_node_control import (
    AutonomousNodeControl,
    AutonomousNodeControlError,
    NodeDeliveryReceipt,
    NodeIterationSnapshot,
)
from .models import Evaluation, EvaluationResult, EventRecord
from .truth_overlay import append_entity


class AutonomousNodeAdoptionError(RuntimeError):
    pass


_NODE_SOURCE = {
    "N1": "REALITY_RECON",
    "N2": "REQUIREMENT_ANALYSIS",
    "N3": "CODE_ANALYSIS",
    "N4": "TEST_DESIGN",
}


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AutonomousNodeAdoptionError(code)
    return text


@dataclass(frozen=True)
class DirectorNodeDecision:
    mission_id: str
    run_id: str
    node_id: str
    iteration_count: int
    accepted: bool
    evaluation_id: str
    event_id: str
    terminal_event_id: str = ""
    reason: str = ""


class AutonomousNodeAdoptionControl:
    """Bridge existing N1-N4 evaluated sub-tasks into node-level authority."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        evidence_root: str,
    ) -> None:
        self.truth = truth
        self.release_id = _required(release_id, "RELEASE_ID_REQUIRED")
        self.node_control = AutonomousNodeControl(
            truth,
            release_id=self.release_id,
            evidence_root=evidence_root,
        )

    @staticmethod
    def source_node(node_id: str) -> str:
        node_id = require_node(node_id).value
        source = _NODE_SOURCE.get(node_id)
        if source is None:
            raise AutonomousNodeAdoptionError("N1_N4_ADOPTION_NODE_REQUIRED:%s" % node_id)
        return source

    def publish_ready_from_evaluated_task(
        self,
        *,
        iteration: NodeIterationSnapshot,
        source_task_id: str,
        source_evaluation_id: str,
        artifact_refs: Sequence[str],
        evidence_refs: Sequence[str],
        team_id: str = "",
        assignment_ids: Sequence[str] = (),
        member_ids: Sequence[str] = (),
        coverage_summary: Optional[Mapping[str, object]] = None,
        risk_summary: Optional[Mapping[str, object]] = None,
        reviewer_result: Optional[Mapping[str, object]] = None,
        sufficiency_result: Optional[Mapping[str, object]] = None,
    ) -> NodeDeliveryReceipt:
        expected_source = self.source_node(iteration.node_id)
        source_task_id = _required(source_task_id, "SOURCE_TASK_ID_REQUIRED")
        source_evaluation_id = _required(source_evaluation_id, "SOURCE_EVALUATION_ID_REQUIRED")

        tasks = self.truth.query("rc7_task", task_id=source_task_id)
        if len(tasks) != 1:
            raise AutonomousNodeAdoptionError("SOURCE_TASK_NOT_UNIQUE")
        task = tasks[0]
        if task.get("mission_id") != iteration.mission_id:
            raise AutonomousNodeAdoptionError("SOURCE_TASK_MISSION_MISMATCH")
        if task.get("node") != expected_source:
            raise AutonomousNodeAdoptionError("SOURCE_TASK_NODE_MISMATCH:%s" % task.get("node"))
        if task.get("state") != "PASS":
            raise AutonomousNodeAdoptionError("SOURCE_SUBTASK_PASS_REQUIRED")
        if task.get("evaluation_id") != source_evaluation_id:
            raise AutonomousNodeAdoptionError("SOURCE_TASK_EVALUATION_MISMATCH")

        evaluations = self.truth.query("rc7_evaluation", evaluation_id=source_evaluation_id)
        if len(evaluations) != 1:
            raise AutonomousNodeAdoptionError("SOURCE_EVALUATION_NOT_UNIQUE")
        evaluation = evaluations[0]
        if evaluation.get("mission_id") != iteration.mission_id:
            raise AutonomousNodeAdoptionError("SOURCE_EVALUATION_MISSION_MISMATCH")
        if evaluation.get("node") != expected_source:
            raise AutonomousNodeAdoptionError("SOURCE_EVALUATION_NODE_MISMATCH")
        if evaluation.get("result") != "PASS":
            raise AutonomousNodeAdoptionError("SOURCE_SUFFICIENCY_PASS_REQUIRED")
        if list(evaluation.get("gap_refs") or []):
            raise AutonomousNodeAdoptionError("SOURCE_PASS_CANNOT_HAVE_OPEN_GAP_REFS")

        declared_artifacts = tuple(dict.fromkeys(str(value) for value in artifact_refs if str(value)))
        declared_evidence = tuple(dict.fromkeys(str(value) for value in evidence_refs if str(value)))
        if not declared_artifacts:
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_ARTIFACT_REQUIRED")
        if not declared_evidence:
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_EVIDENCE_REQUIRED")
        if not set(evaluation.get("artifact_refs") or []).issubset(set(declared_artifacts)):
            raise AutonomousNodeAdoptionError("SOURCE_EVALUATION_ARTIFACT_NOT_IN_DELIVERY")
        if not set(evaluation.get("evidence_refs") or []).issubset(set(declared_evidence)):
            raise AutonomousNodeAdoptionError("SOURCE_EVALUATION_EVIDENCE_NOT_IN_DELIVERY")

        package = NodeDeliveryPackage(
            mission_id=iteration.mission_id,
            run_id=iteration.run_id,
            node_id=iteration.node_id,
            input_version=iteration.input_version,
            iteration_count=iteration.iteration_count,
            artifact_refs=declared_artifacts,
            evidence_refs=declared_evidence,
            unresolved_gap_ids=(),
            blocked_item_ids=(),
            terminal_status=NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value,
            r1_refs=(iteration.start_event_id, source_task_id, source_evaluation_id),
            team_id=str(team_id or ""),
            assignment_ids=tuple(dict.fromkeys(str(value) for value in assignment_ids if str(value))),
            member_ids=tuple(dict.fromkeys(str(value) for value in member_ids if str(value))),
            coverage_summary=dict(coverage_summary or {}),
            risk_summary=dict(risk_summary or {}),
            reviewer_result=dict(reviewer_result or {
                "source_evaluator_ref": evaluation.get("evaluator_ref"),
                "source_evaluation_id": source_evaluation_id,
                "result": "PASS",
            }),
            sufficiency_result=dict(sufficiency_result or {
                "source_evaluation_id": source_evaluation_id,
                "result": "PASS",
                "dimensions": evaluation.get("dimensions") or {},
            }),
        )
        return self.node_control.ready_for_director_review(
            iteration,
            package,
            producer_task_id=source_task_id,
        )

    def director_accept(
        self,
        *,
        mission_id: str,
        run_id: str,
        node_id: str,
        director_ref: str,
    ) -> DirectorNodeDecision:
        mission_id = _required(mission_id, "MISSION_ID_REQUIRED")
        run_id = _required(run_id, "RUN_ID_REQUIRED")
        node_id = require_node(node_id).value
        self.source_node(node_id)
        director_ref = _required(director_ref, "DIRECTOR_REF_REQUIRED")

        iteration = self.node_control.latest_iteration(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
        )
        delivery = self.node_control.latest_delivery(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
        )
        if iteration is None or delivery is None:
            raise AutonomousNodeAdoptionError("CURRENT_NODE_DELIVERY_REQUIRED")
        if delivery.iteration_count != iteration.iteration_count:
            raise AutonomousNodeAdoptionError("STALE_NODE_DELIVERY_FORBIDDEN")
        package = self._load_delivery_package(delivery)
        if package.get("terminal_status") != NodeLoopState.READY_FOR_DIRECTOR_REVIEW.value:
            raise AutonomousNodeAdoptionError("NODE_NOT_READY_FOR_DIRECTOR_REVIEW")
        if list(package.get("unresolved_gap_ids") or []):
            raise AutonomousNodeAdoptionError("DIRECTOR_CANNOT_ACCEPT_UNRESOLVED_NODE_GAPS")
        if list(package.get("blocked_item_ids") or []):
            raise AutonomousNodeAdoptionError("DIRECTOR_CANNOT_ACCEPT_BLOCKED_NODE")
        members = {str(value) for value in package.get("member_ids") or [] if str(value)}
        if director_ref in members:
            raise AutonomousNodeAdoptionError("DIRECTOR_SPECIALIST_SELF_APPROVAL_FORBIDDEN")

        source_task_id, source_evaluation_id = self._source_refs(package)
        task = self._one("rc7_task", "task_id", source_task_id, "SOURCE_TASK_NOT_UNIQUE")
        source_evaluation = self._one(
            "rc7_evaluation",
            "evaluation_id",
            source_evaluation_id,
            "SOURCE_EVALUATION_NOT_UNIQUE",
        )
        if task.get("state") != "PASS" or source_evaluation.get("result") != "PASS":
            raise AutonomousNodeAdoptionError("SOURCE_SUBTASK_OR_SUFFICIENCY_NOT_PASS")
        if task.get("lease_owner") and task.get("lease_owner") == director_ref:
            raise AutonomousNodeAdoptionError("DIRECTOR_SPECIALIST_SELF_APPROVAL_FORBIDDEN")
        if source_evaluation.get("evaluator_ref") == director_ref:
            raise AutonomousNodeAdoptionError("DIRECTOR_CANNOT_REUSE_SOURCE_EVALUATOR_IDENTITY")

        evaluation_id = _stable_id(
            "EVAL-NODE-DIRECTOR",
            mission_id,
            run_id,
            node_id,
            iteration.iteration_count,
            delivery.package_sha256,
            director_ref,
            "PASS",
        )
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=mission_id,
            node="AUTONOMOUS_NODE_GATE",
            artifact_refs=[delivery.package_artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref=director_ref,
            dimensions={
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "input_version": iteration.input_version,
                "package_sha256": delivery.package_sha256,
                "source_task_id": source_task_id,
                "source_evaluation_id": source_evaluation_id,
                "decision": "ACCEPT",
            },
            gap_refs=[],
            evidence_refs=[delivery.package_evidence_id],
        )
        if not self.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            append_entity(
                self.truth,
                evaluation,
                release_id=self.release_id,
                artifact_version=iteration.iteration_count,
            )

        event_id = _stable_id("EVT-DIRECTOR-ACCEPT", evaluation_id, delivery.ready_event_id)
        accepted = EventRecord(
            event_id=event_id,
            mission_id=mission_id,
            event_type=AutonomousEvent.DIRECTOR_NODE_ACCEPTED.value,
            subject_type=AutonomousNodeControl.SUBJECT_TYPE,
            subject_id=AutonomousNodeControl._subject_id(run_id, node_id),
            refs=[delivery.ready_event_id, delivery.package_artifact_id, evaluation_id],
            data={
                "run_id": run_id,
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "director_ref": director_ref,
                "evaluation_id": evaluation_id,
                "state": NodeLoopState.PASS.value,
            },
        )
        if not self.truth.query("rc7_control_event", event_id=event_id):
            append_entity(
                self.truth,
                accepted,
                release_id=self.release_id,
                artifact_version=iteration.iteration_count,
            )

        terminal_event_id = _stable_id("EVT-NODE-TERMINAL", event_id, node_id)
        terminal = EventRecord(
            event_id=terminal_event_id,
            mission_id=mission_id,
            event_type=AutonomousEvent.NODE_TERMINAL.value,
            subject_type=AutonomousNodeControl.SUBJECT_TYPE,
            subject_id=AutonomousNodeControl._subject_id(run_id, node_id),
            refs=[event_id, evaluation_id],
            data={
                "run_id": run_id,
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "state": NodeLoopState.PASS.value,
                "evaluation_id": evaluation_id,
            },
        )
        if not self.truth.query("rc7_control_event", event_id=terminal_event_id):
            append_entity(
                self.truth,
                terminal,
                release_id=self.release_id,
                artifact_version=iteration.iteration_count,
            )
        return DirectorNodeDecision(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
            iteration_count=iteration.iteration_count,
            accepted=True,
            evaluation_id=evaluation_id,
            event_id=event_id,
            terminal_event_id=terminal_event_id,
        )

    def director_reject(
        self,
        *,
        mission_id: str,
        run_id: str,
        node_id: str,
        director_ref: str,
        reason: str,
        evidence_refs: Sequence[str],
    ) -> DirectorNodeDecision:
        mission_id = _required(mission_id, "MISSION_ID_REQUIRED")
        run_id = _required(run_id, "RUN_ID_REQUIRED")
        node_id = require_node(node_id).value
        self.source_node(node_id)
        director_ref = _required(director_ref, "DIRECTOR_REF_REQUIRED")
        reason = _required(reason, "DIRECTOR_REJECTION_REASON_REQUIRED")
        evidence = tuple(dict.fromkeys(_required(value, "DIRECTOR_REJECTION_EVIDENCE_REQUIRED") for value in evidence_refs))
        if not evidence:
            raise AutonomousNodeAdoptionError("DIRECTOR_REJECTION_EVIDENCE_REQUIRED")

        iteration = self.node_control.latest_iteration(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
        )
        delivery = self.node_control.latest_delivery(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
        )
        if iteration is None or delivery is None or delivery.iteration_count != iteration.iteration_count:
            raise AutonomousNodeAdoptionError("CURRENT_NODE_DELIVERY_REQUIRED")
        package = self._load_delivery_package(delivery)
        members = {str(value) for value in package.get("member_ids") or [] if str(value)}
        if director_ref in members:
            raise AutonomousNodeAdoptionError("DIRECTOR_SPECIALIST_SELF_APPROVAL_FORBIDDEN")

        evaluation_id = _stable_id(
            "EVAL-NODE-DIRECTOR",
            mission_id,
            run_id,
            node_id,
            iteration.iteration_count,
            delivery.package_sha256,
            director_ref,
            "REJECT",
            reason,
        )
        evaluation = Evaluation(
            evaluation_id=evaluation_id,
            mission_id=mission_id,
            node="AUTONOMOUS_NODE_GATE",
            artifact_refs=[delivery.package_artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=director_ref,
            dimensions={
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "package_sha256": delivery.package_sha256,
                "decision": "REJECT",
                "reason": reason,
            },
            gap_refs=[],
            evidence_refs=list(evidence),
        )
        append_entity(
            self.truth,
            evaluation,
            release_id=self.release_id,
            artifact_version=iteration.iteration_count,
        )
        event_id = _stable_id("EVT-DIRECTOR-REJECT", evaluation_id, delivery.ready_event_id)
        event = EventRecord(
            event_id=event_id,
            mission_id=mission_id,
            event_type=AutonomousEvent.DIRECTOR_NODE_REJECTED.value,
            subject_type=AutonomousNodeControl.SUBJECT_TYPE,
            subject_id=AutonomousNodeControl._subject_id(run_id, node_id),
            refs=[delivery.ready_event_id, evaluation_id] + list(evidence),
            data={
                "run_id": run_id,
                "node_id": node_id,
                "iteration_count": iteration.iteration_count,
                "director_ref": director_ref,
                "evaluation_id": evaluation_id,
                "reason": reason,
                "state": NodeLoopState.DIRECTOR_REJECTED.value,
            },
        )
        append_entity(
            self.truth,
            event,
            release_id=self.release_id,
            artifact_version=iteration.iteration_count,
        )
        return DirectorNodeDecision(
            mission_id=mission_id,
            run_id=run_id,
            node_id=node_id,
            iteration_count=iteration.iteration_count,
            accepted=False,
            evaluation_id=evaluation_id,
            event_id=event_id,
            reason=reason,
        )

    def _load_delivery_package(self, receipt: NodeDeliveryReceipt) -> Dict[str, Any]:
        rows = self.truth.query("rc7_artifact", artifact_id=receipt.package_artifact_id)
        if len(rows) != 1:
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_ARTIFACT_NOT_UNIQUE")
        row = rows[0]
        if row.get("state") != "VALID":
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_ARTIFACT_NOT_CURRENT")
        content_ref = str(row.get("content_ref") or "")
        if not content_ref.startswith("file://"):
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_FILE_REF_REQUIRED")
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_FILE_MISSING")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest or digest != receipt.package_sha256:
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_HASH_MISMATCH")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_PAYLOAD_INVALID") from exc
        if not isinstance(payload, dict):
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_PAYLOAD_INVALID")
        return payload

    @staticmethod
    def _source_refs(package: Mapping[str, Any]) -> Tuple[str, str]:
        refs = [str(value) for value in package.get("r1_refs") or [] if str(value)]
        task_refs = [value for value in refs if value.startswith("TASK-")]
        eval_refs = [value for value in refs if value.startswith("EVAL-")]
        if len(task_refs) != 1 or len(eval_refs) != 1:
            raise AutonomousNodeAdoptionError("NODE_DELIVERY_SOURCE_REFS_INVALID")
        return task_refs[0], eval_refs[0]

    def _one(self, entity_type: str, field: str, value: str, code: str) -> Mapping[str, Any]:
        rows = self.truth.query(entity_type, **{field: value})
        if len(rows) != 1:
            raise AutonomousNodeAdoptionError(code)
        return rows[0]
