"""RC7.2 N4 aggregate delivery + deterministic NodeGate.

Per-Requirement/SST Test Design PASS is necessary but never sufficient to close
N4.  This service replays the complete canonical Requirement x SST denominator,
re-validates promoted candidate hashes/lineage, verifies designer raw anchors,
independent fresh review proof, semantic closure, Case/Oracle evidence and open
Gap truth, then admits one N4 NodeDelivery.

Only the aggregate PASS NodeGate may release N5.  A complete reviewed set with
any failed criterion becomes NEEDS_REVISION.  A scope that has not completed
review is not deliverable at all.  This service makes no Field/BANK_FINAL claim.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .models import ContractError, TaskStatus
from .rc72_domain import (
    AutonomousMissionNode,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
)
from .rc72_state_machine import RC72StateMachine


_NODE = AutonomousMissionNode.N4_TEST_DESIGN
_NEXT_NODE = AutonomousMissionNode.N5_TEST_DATA
_STAGE = "TEST_DESIGN"
_PRODUCER = "rc72-runtime-n4-delivery"
_GATE_WORKER = "rc72-runtime-n4-gate"
_GATE_SESSION = "runtime://rc72/n4-gate/v1"
_CLOSED_GAP_STATES = {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}
_CRITERIA = (
    "N4_CANONICAL_SCOPE_SET_COMPLETE",
    "N4_SOURCE_COMMIT_LINEAGE",
    "N4_PARENT_N2_N3_PASS_LINEAGE",
    "N4_ALL_DESIGN_TASKS_PASS",
    "N4_ALL_DESIGN_EVALUATIONS_PASS",
    "N4_CANONICAL_ARTIFACTS_BOUND",
    "N4_DESIGNER_RAW_EVIDENCE_ANCHORED",
    "N4_REVIEWER_INDEPENDENT",
    "N4_FRESH_REVIEW_SESSION",
    "N4_REVIEW_RUNTIME_PROOF",
    "N4_REQUIRED_OBLIGATIONS_COMPLETE",
    "N4_REQUIRED_OBLIGATIONS_COVERED",
    "N4_CASE_CONTRACT_COMPLETE",
    "N4_ORACLE_EVIDENCE_DURABLE",
    "N4_SEMANTIC_SUFFICIENCY_PASS",
    "N4_NO_CANDIDATE_UNKNOWNS",
    "N4_NO_CANDIDATE_GAPS",
    "N4_NO_UNRESOLVED_DESIGN_GAPS",
)


class N4CompletionError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N4CompletionError("RC72_N4_COMPLETION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _uniq(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _nonempty_string_list(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    )


class N4DeliveryGateService:
    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _active_pass_gate(
        self, *, mission_id: str, node_type: AutonomousMissionNode
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=node_type.value
        )
        if node.get("state") != MissionNodeState.PASS.value:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_PARENT_NOT_PASS:%s" % node_type.value
            )
        version = node.get("active_delivery_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_PARENT_DELIVERY_REQUIRED:%s" % node_type.value
            )
        deliveries = [
            row
            for row in self.truth.query(
                "rc72_node_delivery", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("version") == version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_PARENT_DELIVERY_NOT_UNIQUE:%s" % node_type.value
            )
        gates = [
            row
            for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("delivery_id") == deliveries[0].get("delivery_id")
            and row.get("gate_id") in list(node.get("gate_refs") or [])
            and row.get("decision") == NodeGateDecision.PASS.value
        ]
        if len(gates) != 1 or list(gates[0].get("failed") or []):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_PARENT_PASS_GATE_NOT_UNIQUE:%s" % node_type.value
            )
        return deliveries[0], gates[0]

    def _canonical_scopes(
        self, *, batch: Mapping[str, Any]
    ) -> Tuple[Set[Tuple[str, str]], str, str, str, str]:
        mission_id = str(batch["mission_id"])
        n2_delivery, n2_gate = self._active_pass_gate(
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N2_REQUIREMENT,
        )
        n3_delivery, n3_gate = self._active_pass_gate(
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        )
        canonical_requirements = set(_strings(batch.get("requirement_ids")))
        scopes: Set[Tuple[str, str]] = set()
        observed_requirements: Set[str] = set()
        for artifact_id in list(n2_delivery.get("artifact_refs") or []):
            artifact = self._one("rc7_artifact", artifact_id=str(artifact_id))
            if (
                artifact.get("mission_id") != mission_id
                or artifact.get("artifact_type_name") != "REQUIREMENT_ANALYSIS_OUTPUT"
                or artifact.get("state") != "VALID"
            ):
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_N2_ARTIFACT_INVALID:%s" % artifact_id
                )
            payload = dict(
                self.reader.load(
                    self.truth,
                    str(artifact_id),
                    expected_mission_id=mission_id,
                ).semantic_payload
            )
            requirement_id = _required(payload.get("requirement_id"), "requirement_id")
            sst_ids = _strings(payload.get("sst_ids"))
            if not sst_ids:
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_CANONICAL_SST_SET_EMPTY:%s" % requirement_id
                )
            if requirement_id in observed_requirements:
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_CANONICAL_REQUIREMENT_DUPLICATE:%s"
                    % requirement_id
                )
            observed_requirements.add(requirement_id)
            for sst_id in sst_ids:
                scopes.add((requirement_id, sst_id))
        if not scopes or observed_requirements != canonical_requirements:
            raise N4CompletionError("RC72_N4_COMPLETION_CANONICAL_SCOPE_SET_INVALID")
        return (
            scopes,
            str(n2_delivery["delivery_id"]),
            str(n2_gate["gate_id"]),
            str(n3_delivery["delivery_id"]),
            str(n3_gate["gate_id"]),
        )

    def _context(
        self, release_batch_id: str
    ) -> Tuple[
        Dict[str, Any],
        Dict[str, Any],
        Dict[str, Any],
        List[Dict[str, Any]],
        Set[Tuple[str, str]],
        Tuple[str, str, str, str],
    ]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N4CompletionError("RC72_N4_COMPLETION_MISSION_LINEAGE_MISMATCH")
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        next_node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if node.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N4CompletionError("RC72_N4_COMPLETION_NODE_SCOPE_MISMATCH")
        if node.get("state") not in {
            MissionNodeState.RUNNING.value,
            MissionNodeState.REVIEW_PENDING.value,
            MissionNodeState.PASS.value,
            MissionNodeState.NEEDS_REVISION.value,
        }:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_NODE_STATE_INVALID:%s" % node.get("state")
            )
        if (
            node.get("state") != MissionNodeState.PASS.value
            and next_node.get("state") != MissionNodeState.NOT_STARTED.value
        ):
            raise N4CompletionError("RC72_N4_COMPLETION_N5_PREMATURELY_RELEASED")
        canonical_scopes, n2_delivery_id, n2_gate_id, n3_delivery_id, n3_gate_id = (
            self._canonical_scopes(batch=batch)
        )
        dispatches = [
            row
            for row in self.truth.query(
                "rc72_n4_test_design_dispatch", release_batch_id=release_batch_id
            )
            if row.get("mission_id") == mission_id
        ]
        if not dispatches:
            raise N4CompletionError("RC72_N4_COMPLETION_DESIGN_DISPATCH_REQUIRED")
        dispatches = sorted(
            dispatches,
            key=lambda row: (str(row.get("requirement_id")), str(row.get("sst_id"))),
        )
        identities = {
            (str(row.get("requirement_id")), str(row.get("sst_id")))
            for row in dispatches
        }
        if len(identities) != len(dispatches):
            raise N4CompletionError("RC72_N4_COMPLETION_SCOPE_SET_DUPLICATE")
        if any(row.get("source_commit") != self.source_commit for row in dispatches):
            raise N4CompletionError("RC72_N4_COMPLETION_SOURCE_COMMIT_MISMATCH")
        parent_ids = (n2_delivery_id, n2_gate_id, n3_delivery_id, n3_gate_id)
        return batch, node, next_node, dispatches, canonical_scopes, parent_ids

    def _evidence_rows(
        self, mission_id: str, evidence_ids: Sequence[str]
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for evidence_id in _uniq(evidence_ids):
            row = self._one("rc7_evidence", evidence_id=evidence_id)
            if row.get("mission_id") != mission_id:
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id
                )
            rows.append(row)
        return rows

    @staticmethod
    def _reviewer_id(evaluation: Mapping[str, Any]) -> str:
        value = str(evaluation.get("evaluator_ref") or "")
        marker = "+deterministic-test-design-gate"
        if not value.startswith("dsh:") or marker not in value:
            return ""
        return value[len("dsh:"):].split("+", 1)[0]

    @staticmethod
    def _durable_aliases(evidence_rows: Sequence[Mapping[str, Any]]) -> Set[str]:
        aliases: Set[str] = set()
        for row in evidence_rows:
            for field in ("evidence_id", "source_ref", "content_ref"):
                value = row.get(field)
                if isinstance(value, str) and value:
                    aliases.add(value)
        return aliases

    @staticmethod
    def _candidate_contract(
        semantic: Mapping[str, Any], durable_aliases: Set[str]
    ) -> Dict[str, bool]:
        obligations = list(semantic.get("obligations") or [])
        cases = list(semantic.get("cases") or [])
        obligation_ids: Set[str] = set()
        required_ids: Set[str] = set()
        obligation_scope_complete = True
        obligation_evidence_durable = True
        for item in obligations:
            if not isinstance(item, Mapping):
                obligation_scope_complete = False
                continue
            obligation_id = str(item.get("obligation_id") or "")
            if not obligation_id or obligation_id in obligation_ids:
                obligation_scope_complete = False
                continue
            obligation_ids.add(obligation_id)
            if item.get("required", True) is True:
                required_ids.add(obligation_id)
            refs = _strings(item.get("evidence_refs"))
            if not refs or not all(ref in durable_aliases for ref in refs):
                obligation_evidence_durable = False

        covered_ids: Set[str] = set()
        case_contract_complete = bool(cases)
        oracle_evidence_durable = bool(cases)
        for case in cases:
            if not isinstance(case, Mapping):
                case_contract_complete = False
                oracle_evidence_durable = False
                continue
            for name in (
                "tc_id",
                "release_batch_id",
                "requirement_id",
                "sst_id",
                "obligation_id",
                "layer",
            ):
                if not isinstance(case.get(name), str) or not str(case.get(name)).strip():
                    case_contract_complete = False
            for name in (
                "preconditions",
                "data_requirements",
                "steps",
                "expected_results",
                "evidence_requirements",
                "code_trace",
            ):
                if not _nonempty_string_list(case.get(name)):
                    case_contract_complete = False
            obligation_id = str(case.get("obligation_id") or "")
            if obligation_id not in obligation_ids:
                case_contract_complete = False
            links = case.get("coverage_links")
            if not isinstance(links, list) or not links:
                case_contract_complete = False
                oracle_evidence_durable = False
            else:
                for link in links:
                    if not isinstance(link, Mapping):
                        case_contract_complete = False
                        oracle_evidence_durable = False
                        continue
                    subject_id = str(link.get("subject_id") or "")
                    evidence_ref = str(link.get("evidence_ref") or "")
                    if subject_id in obligation_ids:
                        covered_ids.add(subject_id)
                    else:
                        case_contract_complete = False
                    if evidence_ref not in durable_aliases:
                        oracle_evidence_durable = False
            oracle = case.get("oracle")
            checks = oracle.get("checks") if isinstance(oracle, Mapping) else None
            if not isinstance(checks, list) or not checks:
                case_contract_complete = False
                oracle_evidence_durable = False
            else:
                for check in checks:
                    if not isinstance(check, Mapping):
                        case_contract_complete = False
                        oracle_evidence_durable = False
                        continue
                    if not isinstance(check.get("type"), str) or not str(check.get("type")).strip():
                        case_contract_complete = False
                    evidence_ref = str(check.get("evidence_ref") or "")
                    if evidence_ref not in durable_aliases:
                        oracle_evidence_durable = False
        return {
            "obligations_present": bool(obligations and obligation_ids),
            "obligation_scope_complete": obligation_scope_complete,
            "obligation_evidence_durable": obligation_evidence_durable,
            "required_covered": bool(required_ids) and required_ids.issubset(covered_ids),
            "case_contract_complete": case_contract_complete,
            "oracle_evidence_durable": oracle_evidence_durable,
        }

    def _scope_record(
        self,
        *,
        batch: Mapping[str, Any],
        dispatch: Mapping[str, Any],
        parent_ids: Tuple[str, str, str, str],
    ) -> Dict[str, Any]:
        mission_id = str(batch["mission_id"])
        release_batch_id = str(batch["release_batch_id"])
        requirement_id = _required(dispatch.get("requirement_id"), "requirement_id")
        sst_id = _required(dispatch.get("sst_id"), "sst_id")
        scope = "%s/%s" % (requirement_id, sst_id)
        task_id = _required(dispatch.get("workitem_id"), "workitem_id")
        task = self._one("rc7_task", task_id=task_id)
        if task.get("mission_id") != mission_id or task.get("node") != _STAGE:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_TASK_LINEAGE_MISMATCH:%s" % scope
            )
        if task.get("state") not in {TaskStatus.PASS.value, TaskStatus.REPAIR_REQUIRED.value}:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_REVIEW_INCOMPLETE:%s:%s"
                % (scope, str(task.get("state") or "UNKNOWN"))
            )
        artifact_refs = list(task.get("output_artifact_refs") or [])
        if len(artifact_refs) != 1:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_ARTIFACT_NOT_UNIQUE:%s" % scope
            )
        artifact_id = str(artifact_refs[0])
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("mission_id") != mission_id
            or artifact.get("producer_task_id") != task_id
            or artifact.get("artifact_type_name") != "TEST_DESIGN_CANDIDATE"
            or artifact.get("state") != "VALID"
            or not str(artifact.get("content_hash") or "").startswith("sha256:")
        ):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_ARTIFACT_LINEAGE_INVALID:%s" % scope
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=task_id,
        )
        semantic = dict(durable.semantic_payload)
        if (
            semantic.get("candidate_kind") != "TEST_DESIGN_CANDIDATE"
            or semantic.get("release_batch_id") != release_batch_id
            or semantic.get("requirement_id") != requirement_id
            or semantic.get("sst_id") != sst_id
        ):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_CANDIDATE_LINEAGE_INVALID:%s" % scope
            )
        for obligation in list(semantic.get("obligations") or []):
            if not isinstance(obligation, Mapping):
                continue
            if (
                obligation.get("requirement_id") != requirement_id
                or obligation.get("sst_id") != sst_id
            ):
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_OBLIGATION_SCOPE_MISMATCH:%s" % scope
                )
        for case in list(semantic.get("cases") or []):
            if not isinstance(case, Mapping):
                continue
            if (
                case.get("release_batch_id") != release_batch_id
                or case.get("requirement_id") != requirement_id
                or case.get("sst_id") != sst_id
            ):
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_CASE_SCOPE_MISMATCH:%s" % scope
                )

        assignment = self._one(
            "rc72_n4_test_design_assignment",
            release_batch_id=release_batch_id,
            requirement_id=requirement_id,
            sst_id=sst_id,
        )
        designer_id = _required(task.get("lease_owner"), "designer_worker_id")
        if (
            assignment.get("workitem_id") != task_id
            or assignment.get("dispatch_id") != dispatch.get("dispatch_id")
            or assignment.get("worker_instance_id") != designer_id
        ):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_ASSIGNMENT_LINEAGE_INVALID:%s" % scope
            )
        anchor = self._one(
            "rc72_n4_test_design_evidence_anchor",
            release_batch_id=release_batch_id,
            requirement_id=requirement_id,
            sst_id=sst_id,
        )
        if (
            anchor.get("workitem_id") != task_id
            or anchor.get("assignment_id") != assignment.get("assignment_id")
            or anchor.get("dispatch_id") != dispatch.get("dispatch_id")
            or anchor.get("worker_instance_id") != designer_id
            or anchor.get("source_commit") != self.source_commit
            or not str(anchor.get("raw_output_sha256") or "").startswith("sha256:")
        ):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_DESIGNER_ANCHOR_INVALID:%s" % scope
            )
        designer_session = _required(anchor.get("dsh_session_id"), "designer_session_id")
        runtime_lineage = durable.envelope.get("runtime_lineage")
        if not isinstance(runtime_lineage, Mapping) or (
            runtime_lineage.get("evidence_anchor_id") != anchor.get("anchor_id")
            or runtime_lineage.get("raw_output_sha256") != anchor.get("raw_output_sha256")
            or runtime_lineage.get("dsh_session_id") != designer_session
            or runtime_lineage.get("source_commit") != self.source_commit
        ):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_CANDIDATE_ANCHOR_MISMATCH:%s" % scope
            )

        evaluation_id = _required(task.get("evaluation_id"), "evaluation_id")
        evaluation = self._one("rc7_evaluation", evaluation_id=evaluation_id)
        expected_result = (
            "PASS" if task.get("state") == TaskStatus.PASS.value else "REPAIR_REQUIRED"
        )
        if (
            evaluation.get("mission_id") != mission_id
            or evaluation.get("node") != _STAGE
            or evaluation.get("result") != expected_result
            or artifact_id not in list(evaluation.get("artifact_refs") or [])
        ):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_EVALUATION_LINEAGE_INVALID:%s" % scope
            )
        dimensions = evaluation.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise N4CompletionError(
                "RC72_N4_COMPLETION_EVALUATION_DIMENSIONS_REQUIRED:%s" % scope
            )

        artifact_evidence = self._evidence_rows(
            mission_id, list(artifact.get("evidence_refs") or [])
        )
        evaluation_evidence = self._evidence_rows(
            mission_id, list(evaluation.get("evidence_refs") or [])
        )
        all_evidence = artifact_evidence + evaluation_evidence
        aliases = self._durable_aliases(artifact_evidence)
        contract = self._candidate_contract(semantic, aliases)

        reviewer_id = self._reviewer_id(evaluation)
        reviewer_rows = [
            row
            for row in evaluation_evidence
            if row.get("kind") == "INDEPENDENT_TEST_DESIGN_REVIEW_PROOF"
            and row.get("source_ref") == "dsh://worker/%s" % reviewer_id
            and task_id in list(row.get("subject_refs") or [])
            and artifact_id in list(row.get("subject_refs") or [])
        ] if reviewer_id else []
        reviewer_sessions = _uniq(
            str(row.get("content_ref"))[len("dsh://session/"):]
            for row in reviewer_rows
            if str(row.get("content_ref") or "").startswith("dsh://session/")
        )
        reviewer_session = reviewer_sessions[0] if len(reviewer_sessions) == 1 else ""
        reviewer_tool_proof = any(
            isinstance(row.get("content_ref"), str)
            and bool(str(row.get("content_ref")))
            and not str(row.get("content_ref")).startswith("dsh://session/")
            for row in reviewer_rows
        )

        metrics = dimensions.get("metrics")
        semantic_pass = bool(
            task.get("state") == TaskStatus.PASS.value
            and evaluation.get("result") == "PASS"
            and dimensions.get("independent_review") == "PASS"
            and isinstance(metrics, Mapping)
            and float(metrics.get("semantic_coverage") or 0.0) >= 1.0
            and list(dimensions.get("uncovered_obligation_ids") or []) == []
            and list(dimensions.get("critical_high_gap_ids") or []) == []
            and list(dimensions.get("oracle_gap_case_ids") or []) == []
        )

        gap_ids = _uniq(
            _strings(task.get("gap_refs")) + _strings(evaluation.get("gap_refs"))
        )
        active_gap_ids: List[str] = []
        for gap_id in gap_ids:
            gap = self._one("rc7_gap", gap_id=gap_id)
            if gap.get("mission_id") != mission_id:
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_GAP_MISSION_MISMATCH:%s" % gap_id
                )
            if str(gap.get("state") or "") not in _CLOSED_GAP_STATES:
                active_gap_ids.append(gap_id)

        expected_parent = {
            "source_n2_delivery_id": parent_ids[0],
            "source_n2_gate_id": parent_ids[1],
            "source_n3_delivery_id": parent_ids[2],
            "source_n3_gate_id": parent_ids[3],
        }
        parent_lineage_ok = all(
            dispatch.get(field) == value for field, value in expected_parent.items()
        )
        evidence_ids = _uniq(
            str(row["evidence_id"])
            for row in all_evidence
            if isinstance(row.get("evidence_id"), str)
        )
        return {
            "requirement_id": requirement_id,
            "sst_id": sst_id,
            "dispatch_id": str(dispatch["dispatch_id"]),
            "task_id": task_id,
            "task_state": str(task["state"]),
            "artifact_id": artifact_id,
            "artifact_hash": str(artifact.get("content_hash") or ""),
            "evaluation_id": evaluation_id,
            "evaluation_result": str(evaluation.get("result") or ""),
            "parent_lineage_ok": parent_lineage_ok,
            "source_commit_ok": dispatch.get("source_commit") == self.source_commit,
            "anchor_id": str(anchor.get("anchor_id") or ""),
            "raw_output_sha256": str(anchor.get("raw_output_sha256") or ""),
            "designer_worker_id": designer_id,
            "designer_session_id": designer_session,
            "reviewer_worker_id": reviewer_id,
            "reviewer_session_id": reviewer_session,
            "reviewer_independent": bool(reviewer_id and reviewer_id != designer_id),
            "fresh_review_session": bool(
                reviewer_session and reviewer_session != designer_session
            ),
            "review_runtime_proven": bool(reviewer_rows and reviewer_session and reviewer_tool_proof),
            "obligations_present": contract["obligations_present"],
            "obligation_scope_complete": contract["obligation_scope_complete"],
            "obligation_evidence_durable": contract["obligation_evidence_durable"],
            "required_covered": contract["required_covered"],
            "case_contract_complete": contract["case_contract_complete"],
            "oracle_evidence_durable": contract["oracle_evidence_durable"],
            "semantic_pass": semantic_pass,
            "unknowns_empty": list(semantic.get("candidate_unknowns") or []) == [],
            "candidate_gaps_empty": list(semantic.get("candidate_gaps") or []) == [],
            "active_gap_ids": active_gap_ids,
            "evidence_ids": evidence_ids,
        }

    def _records(
        self, release_batch_id: str
    ) -> Tuple[
        Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], Set[Tuple[str, str]]
    ]:
        batch, node, next_node, dispatches, canonical_scopes, parent_ids = self._context(
            release_batch_id
        )
        records = [
            self._scope_record(batch=batch, dispatch=row, parent_ids=parent_ids)
            for row in dispatches
        ]
        identities = {(row["requirement_id"], row["sst_id"]) for row in records}
        if len(identities) != len(records):
            raise N4CompletionError("RC72_N4_COMPLETION_SCOPE_SET_NOT_UNIQUE")
        return batch, node, next_node, records, canonical_scopes

    @staticmethod
    def _record_signature(records: Sequence[Mapping[str, Any]]) -> str:
        return "|".join(
            "%s:%s:%s:%s:%s"
            % (
                row["requirement_id"],
                row["sst_id"],
                row["artifact_id"],
                row["artifact_hash"],
                row["evaluation_id"],
            )
            for row in records
        )

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, _next_node, records, _canonical_scopes = self._records(
            release_batch_id
        )
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        signature = self._record_signature(records)
        delivery_id = _stable_id(
            "N4DEL", mission_id, release_batch_id, self.source_commit, signature
        )
        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N4CompletionError("RC72_N4_COMPLETION_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=node_id
                )["state"],
                "known_gap_ids": list(existing[0].get("known_gaps") or []),
            }
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_DELIVERY_REQUIRES_RUNNING_NODE:%s"
                % str(node.get("state") or "UNKNOWN")
            )
        previous = self.truth.query("rc72_node_delivery", mission_node_id=node_id)
        version = max([int(row.get("version") or 0) for row in previous] + [0]) + 1
        passed_count = sum(
            1 for row in records if row["task_state"] == TaskStatus.PASS.value
        )
        evidence = _uniq(
            evidence_id for row in records for evidence_id in row["evidence_ids"]
        )
        gaps = _uniq(gap_id for row in records for gap_id in row["active_gap_ids"])
        delivery = NodeDelivery(
            delivery_id=delivery_id,
            mission_id=mission_id,
            mission_node_id=node_id,
            node_type=_NODE,
            version=version,
            producer_ref=_PRODUCER,
            input_refs=_uniq(
                ["n4-dispatch://%s" % row["dispatch_id"] for row in records]
                + ["n4-anchor://%s" % row["anchor_id"] for row in records]
                + ["evaluation://%s" % row["evaluation_id"] for row in records]
            ),
            artifact_refs=[row["artifact_id"] for row in records],
            evidence_refs=evidence,
            known_gaps=gaps,
            created_by_workitems=[row["task_id"] for row in records],
            sufficiency_score=float(passed_count) / float(len(records)),
        )
        RC72StateMachine(self.truth, release_id=release_id).submit_delivery(delivery)
        return {
            "status": "DELIVERY_ADMITTED",
            "delivery_id": delivery_id,
            "delivery_version": version,
            "node_state": MissionNodeState.REVIEW_PENDING.value,
            "scope_count": len(records),
            "passed_scope_count": passed_count,
            "known_gap_ids": gaps,
        }

    def _criterion_results(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        canonical_scopes: Set[Tuple[str, str]],
    ) -> Dict[str, bool]:
        actual_scopes = {
            (str(row["requirement_id"]), str(row["sst_id"])) for row in records
        }
        return {
            "N4_CANONICAL_SCOPE_SET_COMPLETE": bool(
                records and actual_scopes == canonical_scopes
            ),
            "N4_SOURCE_COMMIT_LINEAGE": all(row["source_commit_ok"] for row in records),
            "N4_PARENT_N2_N3_PASS_LINEAGE": all(row["parent_lineage_ok"] for row in records),
            "N4_ALL_DESIGN_TASKS_PASS": all(
                row["task_state"] == TaskStatus.PASS.value for row in records
            ),
            "N4_ALL_DESIGN_EVALUATIONS_PASS": all(
                row["evaluation_result"] == "PASS" for row in records
            ),
            "N4_CANONICAL_ARTIFACTS_BOUND": all(
                bool(row["artifact_id"] and row["artifact_hash"])
                for row in records
            ),
            "N4_DESIGNER_RAW_EVIDENCE_ANCHORED": all(
                bool(row["anchor_id"] and row["raw_output_sha256"])
                for row in records
            ),
            "N4_REVIEWER_INDEPENDENT": all(
                row["reviewer_independent"] for row in records
            ),
            "N4_FRESH_REVIEW_SESSION": all(
                row["fresh_review_session"] for row in records
            ),
            "N4_REVIEW_RUNTIME_PROOF": all(
                row["review_runtime_proven"] for row in records
            ),
            "N4_REQUIRED_OBLIGATIONS_COMPLETE": all(
                row["obligations_present"]
                and row["obligation_scope_complete"]
                and row["obligation_evidence_durable"]
                for row in records
            ),
            "N4_REQUIRED_OBLIGATIONS_COVERED": all(
                row["required_covered"] for row in records
            ),
            "N4_CASE_CONTRACT_COMPLETE": all(
                row["case_contract_complete"] for row in records
            ),
            "N4_ORACLE_EVIDENCE_DURABLE": all(
                row["oracle_evidence_durable"] for row in records
            ),
            "N4_SEMANTIC_SUFFICIENCY_PASS": all(
                row["semantic_pass"] for row in records
            ),
            "N4_NO_CANDIDATE_UNKNOWNS": all(
                row["unknowns_empty"] for row in records
            ),
            "N4_NO_CANDIDATE_GAPS": all(
                row["candidate_gaps_empty"] for row in records
            ),
            "N4_NO_UNRESOLVED_DESIGN_GAPS": all(
                not row["active_gap_ids"] for row in records
            ),
        }

    def apply_gate(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, next_node, records, canonical_scopes = self._records(
            release_batch_id
        )
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        active_version = node.get("active_delivery_version")
        if isinstance(active_version, bool) or not isinstance(active_version, int):
            raise N4CompletionError("RC72_N4_COMPLETION_ACTIVE_DELIVERY_REQUIRED")
        deliveries = [
            row
            for row in self.truth.query("rc72_node_delivery", mission_node_id=node_id)
            if row.get("version") == active_version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_ACTIVE_DELIVERY_NOT_UNIQUE:%d" % len(deliveries)
            )
        delivery = deliveries[0]
        if (
            list(delivery.get("artifact_refs") or [])
            != [row["artifact_id"] for row in records]
            or list(delivery.get("created_by_workitems") or [])
            != [row["task_id"] for row in records]
        ):
            raise N4CompletionError("RC72_N4_COMPLETION_DELIVERY_CURRENT_TRUTH_MISMATCH")

        criterion = self._criterion_results(
            records=records, canonical_scopes=canonical_scopes
        )
        passed = [name for name in _CRITERIA if criterion[name]]
        failed = [name for name in _CRITERIA if not criterion[name]]
        decision = (
            NodeGateDecision.PASS if not failed else NodeGateDecision.NEEDS_REVISION
        )
        gate_id = _stable_id(
            "N4GATE",
            str(delivery["delivery_id"]),
            self.source_commit,
            decision.value,
            ",".join(failed),
        )
        existing = self.truth.query("rc72_node_gate", gate_id=gate_id)
        if existing:
            if len(existing) != 1:
                raise N4CompletionError("RC72_N4_COMPLETION_GATE_NOT_UNIQUE")
            current_node = self._one("rc72_mission_node", mission_node_id=node_id)
            current_next = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if decision == NodeGateDecision.PASS:
                if current_node.get("state") != MissionNodeState.PASS.value:
                    raise N4CompletionError(
                        "RC72_N4_COMPLETION_EXISTING_PASS_GATE_NODE_NOT_PASS"
                    )
                if current_next.get("state") == MissionNodeState.NOT_STARTED.value:
                    RC72StateMachine(self.truth, release_id=release_id).forward(
                        _NODE, _NEXT_NODE, source_gate_id=gate_id
                    )
                    current_next = self._one(
                        "rc72_mission_node",
                        mission_id=mission_id,
                        node_type=_NEXT_NODE.value,
                    )
            return {
                "status": "RESUMED",
                "gate_id": gate_id,
                "decision": decision.value,
                "passed": passed,
                "failed": failed,
                "n4_state": current_node["state"],
                "n5_state": current_next["state"],
            }
        if node.get("state") != MissionNodeState.REVIEW_PENDING.value:
            raise N4CompletionError(
                "RC72_N4_COMPLETION_GATE_REQUIRES_REVIEW_PENDING:%s"
                % str(node.get("state") or "UNKNOWN")
            )
        gate = NodeGate(
            gate_id=gate_id,
            mission_id=mission_id,
            mission_node_id=node_id,
            node_type=_NODE,
            delivery_id=str(delivery["delivery_id"]),
            decision=decision,
            reviewer_worker_id=_GATE_WORKER,
            reviewer_session_id=_GATE_SESSION,
            criteria=list(_CRITERIA),
            passed=passed,
            failed=failed,
            evidence_refs=_uniq(
                evidence_id for row in records for evidence_id in row["evidence_ids"]
            ),
            return_node=_NODE if decision == NodeGateDecision.NEEDS_REVISION else None,
            reason=(
                "all canonical Requirement/SST design scopes passed independent fresh review and deterministic sufficiency"
                if decision == NodeGateDecision.PASS
                else "N4 deterministic criteria failed: %s" % ",".join(failed)
            ),
        )
        runtime = RC72StateMachine(self.truth, release_id=release_id)
        runtime.apply_gate(gate)
        n5_state = next_node["state"]
        if decision == NodeGateDecision.PASS:
            if next_node.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N4CompletionError(
                    "RC72_N4_COMPLETION_N5_PREMATURE_STATE:%s"
                    % next_node.get("state")
                )
            runtime.forward(_NODE, _NEXT_NODE, source_gate_id=gate_id)
            n5_state = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )["state"]
        else:
            current_next = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if current_next.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N4CompletionError("RC72_N4_COMPLETION_REVISION_CANNOT_RELEASE_N5")
            n5_state = current_next["state"]
        return {
            "status": "GATE_APPLIED",
            "gate_id": gate_id,
            "decision": decision.value,
            "passed": passed,
            "failed": failed,
            "n4_state": (
                MissionNodeState.PASS.value
                if decision == NodeGateDecision.PASS
                else MissionNodeState.NEEDS_REVISION.value
            ),
            "n5_state": n5_state,
            "known_gap_ids": list(delivery.get("known_gaps") or []),
        }

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        delivery = self.admit_delivery(release_batch_id=release_batch_id)
        gate = self.apply_gate(release_batch_id=release_batch_id)
        return {"delivery": delivery, "gate": gate}


__all__ = ["N4CompletionError", "N4DeliveryGateService"]
