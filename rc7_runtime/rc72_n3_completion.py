"""RC7.2 N3 aggregate delivery + deterministic NodeGate.

Per-target CODE_ANALYSIS PASS is necessary but never sufficient to complete N3.
This service replays canonical R1 truth for the complete dispatched target set,
re-validates candidate hashes and source lineage, binds real analyzer Git /
CodeGraph proof, proves an independent fresh reviewer session, and verifies the
real CodeSufficiencyV2 result before admitting a NodeDelivery.

Only an evidence-backed PASS NodeGate may release N4.  A complete reviewed set
with any failed criterion becomes NEEDS_REVISION.  An incomplete review set is
not deliverable at all.  This service never claims Q7, Field or BANK_FINAL.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .dsh_proof import code_tool_category
from .models import ContractError, TaskStatus
from .rc72_domain import (
    AutonomousMissionNode,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
)
from .rc72_state_machine import RC72StateMachine


_NODE = AutonomousMissionNode.N3_CODE_ANALYSIS
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN
_STAGE = "CODE_ANALYSIS"
_PRODUCER = "rc72-runtime-n3-delivery"
_GATE_WORKER = "rc72-runtime-n3-gate"
_GATE_SESSION = "runtime://rc72/n3-gate/v1"
_GATE_CONTRACT = "RC72_N3_REAL_CODE_GATE_EXTENSION_V2"
_CLOSED_GAP_STATES = {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}
_CRITERIA = (
    "N3_CANONICAL_TARGET_SET_COMPLETE",
    "N3_SOURCE_COMMIT_LINEAGE",
    "N3_SOURCE_MAPPING_LINEAGE_BOUND",
    "N3_ALL_CODE_TASKS_PASS",
    "N3_ALL_CODE_EVALUATIONS_PASS",
    "N3_CANONICAL_ARTIFACTS_BOUND",
    "N3_CANONICAL_REQUIREMENT_REVERSE_MAPPING",
    "N3_REPOSITORY_REVISION_EXACT",
    "N3_REAL_GIT_PROOF",
    "N3_REQUIRED_CODEGRAPH_PROOF",
    "N3_REVIEWER_INDEPENDENT",
    "N3_FRESH_REVIEW_SESSION",
    "N3_REVIEW_RUNTIME_PROOF",
    "N3_IMPACT_SUFFICIENCY_V2_PASS",
    "N3_NO_CANDIDATE_UNKNOWNS",
    "N3_NO_CANDIDATE_GAPS",
    "N3_NO_UNRESOLVED_ANALYSIS_GAPS",
)


class N3CompletionError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CompletionError("RC72_N3_COMPLETION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _uniq(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class N3DeliveryGateService:
    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _context(
        self, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        next_node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if node.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N3CompletionError("RC72_N3_COMPLETION_NODE_SCOPE_MISMATCH")
        if node.get("state") not in {
            MissionNodeState.RUNNING.value,
            MissionNodeState.REVIEW_PENDING.value,
            MissionNodeState.PASS.value,
            MissionNodeState.NEEDS_REVISION.value,
        }:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_NODE_STATE_INVALID:%s" % node.get("state")
            )
        if node.get("state") != MissionNodeState.PASS.value and next_node.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3CompletionError("RC72_N3_COMPLETION_N4_PREMATURELY_RELEASED")
        dispatches = [
            row
            for row in self.truth.query(
                "rc72_n3_code_analysis_dispatch", release_batch_id=release_batch_id
            )
            if row.get("mission_id") == mission_id
        ]
        if not dispatches:
            raise N3CompletionError("RC72_N3_COMPLETION_CODE_DISPATCH_REQUIRED")
        dispatches = sorted(
            dispatches,
            key=lambda row: (str(row.get("application_id")), str(row.get("target_id"))),
        )
        identities = [
            (str(row.get("application_id")), str(row.get("target_id")))
            for row in dispatches
        ]
        if len(identities) != len(set(identities)):
            raise N3CompletionError("RC72_N3_COMPLETION_TARGET_SET_DUPLICATE")
        if any(row.get("source_commit") != self.source_commit for row in dispatches):
            raise N3CompletionError("RC72_N3_COMPLETION_SOURCE_COMMIT_MISMATCH")
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N3CompletionError("RC72_N3_COMPLETION_MISSION_LINEAGE_MISMATCH")
        return batch, node, next_node, dispatches

    def _evidence_rows(self, mission_id: str, evidence_ids: Sequence[str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for evidence_id in _uniq(evidence_ids):
            row = self._one("rc7_evidence", evidence_id=evidence_id)
            if row.get("mission_id") != mission_id:
                raise N3CompletionError(
                    "RC72_N3_COMPLETION_EVIDENCE_MISSION_MISMATCH:%s" % evidence_id
                )
            rows.append(row)
        return rows

    @staticmethod
    def _reviewer_id(evaluation: Mapping[str, Any]) -> str:
        value = str(evaluation.get("evaluator_ref") or "")
        if not value.startswith("dsh:") or "+deterministic-code-gate" not in value:
            return ""
        return value[len("dsh:"):].split("+", 1)[0]

    def _review_event(
        self,
        *,
        mission_id: str,
        artifact_id: str,
        reviewer_id: str,
    ) -> Dict[str, Any]:
        rows = [
            row
            for row in self.truth.query("agent_runtime_event", mission_id=mission_id)
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("worker_instance_id") == reviewer_id
            and row.get("scope") == artifact_id
        ]
        if len(rows) != 1:
            return {}
        return rows[0]

    def _real_analyzer_tool_proof(
        self,
        *,
        mission_id: str,
        analyzer_id: str,
        task_id: str,
        artifact_id: str,
        target_id: str,
        evidence_rows: Sequence[Mapping[str, Any]],
        category: str,
    ) -> bool:
        expected_kind = "DSH_%s_TOOL_CALL_PROOF" % category.upper()
        proofs = [row for row in evidence_rows if row.get("kind") == expected_kind]
        if not proofs:
            return False
        for proof in proofs:
            subjects = list(proof.get("subject_refs") or [])
            if not all(value in subjects for value in (task_id, artifact_id, target_id)):
                continue
            source_ref = str(proof.get("source_ref") or "")
            if not source_ref.startswith("r1-event://"):
                continue
            event_id = source_ref[len("r1-event://"):]
            events = self.truth.query("agent_runtime_event", id=event_id)
            if len(events) != 1:
                continue
            event = events[0]
            if (
                event.get("mission_id") != mission_id
                or event.get("event_name") != "WORKER_TOOL_CALLED"
                or event.get("worker_instance_id") != analyzer_id
            ):
                continue
            tool_call = event.get("tool_call")
            if not isinstance(tool_call, Mapping):
                continue
            if code_tool_category(str(tool_call.get("tool_name") or "")) == category:
                return True
        return False

    def _target_record(
        self,
        *,
        batch: Mapping[str, Any],
        dispatch: Mapping[str, Any],
    ) -> Dict[str, Any]:
        mission_id = str(batch["mission_id"])
        task_id = _required(dispatch.get("workitem_id"), "workitem_id")
        target_id = _required(dispatch.get("target_id"), "target_id")
        application_id = _required(dispatch.get("application_id"), "application_id")
        task = self._one("rc7_task", task_id=task_id)
        if task.get("mission_id") != mission_id or task.get("node") != _STAGE:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_TASK_LINEAGE_MISMATCH:%s" % target_id
            )
        if task.get("state") not in {TaskStatus.PASS.value, TaskStatus.REPAIR_REQUIRED.value}:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_REVIEW_INCOMPLETE:%s:%s"
                % (target_id, str(task.get("state") or "UNKNOWN"))
            )
        artifact_refs = list(task.get("output_artifact_refs") or [])
        if len(artifact_refs) != 1:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_ARTIFACT_NOT_UNIQUE:%s" % target_id
            )
        artifact_id = str(artifact_refs[0])
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("mission_id") != mission_id
            or artifact.get("producer_task_id") != task_id
            or artifact.get("artifact_type_name") != "CODE_ANALYSIS_CANDIDATE"
            or artifact.get("state") != "VALID"
            or not str(artifact.get("content_hash") or "").startswith("sha256:")
        ):
            raise N3CompletionError(
                "RC72_N3_COMPLETION_ARTIFACT_LINEAGE_INVALID:%s" % target_id
            )
        if str(dispatch.get("source_mapping_artifact_id") or "") not in list(
            artifact.get("parent_refs") or []
        ):
            raise N3CompletionError(
                "RC72_N3_COMPLETION_SOURCE_MAPPING_PARENT_MISSING:%s" % target_id
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=task_id,
        )
        semantic = dict(durable.semantic_payload)
        if (
            semantic.get("candidate_kind") != "CODE_ANALYSIS_CANDIDATE"
            or semantic.get("gate_contract") != _GATE_CONTRACT
            or semantic.get("application_id") != application_id
            or semantic.get("target_id") != target_id
            or semantic.get("repository_ref") != dispatch.get("repository_ref")
            or semantic.get("source_revision") != dispatch.get("source_revision")
            or semantic.get("source_revisions")
            != {str(dispatch.get("repository_ref")): str(dispatch.get("source_revision"))}
        ):
            raise N3CompletionError(
                "RC72_N3_COMPLETION_CANDIDATE_LINEAGE_INVALID:%s" % target_id
            )

        assignment = self._one(
            "rc72_n3_code_analysis_assignment",
            release_batch_id=str(dispatch["release_batch_id"]),
            target_id=target_id,
        )
        analyzer_id = _required(task.get("lease_owner"), "analyzer_worker_id")
        if (
            assignment.get("workitem_id") != task_id
            or assignment.get("dispatch_id") != dispatch.get("dispatch_id")
            or assignment.get("worker_instance_id") != analyzer_id
        ):
            raise N3CompletionError(
                "RC72_N3_COMPLETION_ASSIGNMENT_LINEAGE_INVALID:%s" % target_id
            )
        anchor = self._one(
            "rc72_n3_code_analysis_evidence_anchor",
            release_batch_id=str(dispatch["release_batch_id"]),
            target_id=target_id,
        )
        if (
            anchor.get("workitem_id") != task_id
            or anchor.get("assignment_id") != assignment.get("assignment_id")
            or anchor.get("worker_instance_id") != analyzer_id
            or not str(anchor.get("raw_output_sha256") or "").startswith("sha256:")
        ):
            raise N3CompletionError(
                "RC72_N3_COMPLETION_ANALYZER_ANCHOR_INVALID:%s" % target_id
            )
        analyzer_session = _required(anchor.get("dsh_session_id"), "analyzer_session_id")

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
            raise N3CompletionError(
                "RC72_N3_COMPLETION_EVALUATION_LINEAGE_INVALID:%s" % target_id
            )
        dimensions = evaluation.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise N3CompletionError(
                "RC72_N3_COMPLETION_EVALUATION_DIMENSIONS_REQUIRED:%s" % target_id
            )

        artifact_evidence = self._evidence_rows(
            mission_id, list(artifact.get("evidence_refs") or [])
        )
        evaluation_evidence = self._evidence_rows(
            mission_id, list(evaluation.get("evidence_refs") or [])
        )
        all_evidence = artifact_evidence + evaluation_evidence
        reviewer_id = self._reviewer_id(evaluation)
        reviewer_event = self._review_event(
            mission_id=mission_id,
            artifact_id=artifact_id,
            reviewer_id=reviewer_id,
        ) if reviewer_id else {}
        reviewer_session = str(reviewer_event.get("dsh_session_id") or "")
        reviewer_tool_categories = {
            code_tool_category(str(call.get("tool_name") or ""))
            for call in list(reviewer_event.get("tool_calls") or [])
            if isinstance(call, Mapping)
        }
        reviewer_evidence_present = any(
            row.get("kind") == "INDEPENDENT_CODE_REVIEW_PROOF"
            and row.get("source_ref") == "dsh://worker/%s" % reviewer_id
            and task_id in list(row.get("subject_refs") or [])
            and artifact_id in list(row.get("subject_refs") or [])
            for row in evaluation_evidence
        )
        reviewer_runtime_proven = bool(
            reviewer_event
            and reviewer_event.get("result") == "PASS"
            and reviewer_session
            and list(reviewer_event.get("tool_calls") or [])
            and reviewer_evidence_present
        )

        codegraph_required = semantic.get("codegraph_required") is not False
        git_proven = self._real_analyzer_tool_proof(
            mission_id=mission_id,
            analyzer_id=analyzer_id,
            task_id=task_id,
            artifact_id=artifact_id,
            target_id=target_id,
            evidence_rows=evaluation_evidence,
            category="git",
        )
        codegraph_proven = self._real_analyzer_tool_proof(
            mission_id=mission_id,
            analyzer_id=analyzer_id,
            task_id=task_id,
            artifact_id=artifact_id,
            target_id=target_id,
            evidence_rows=evaluation_evidence,
            category="codegraph",
        )
        reviewer_tools_proven = "git" in reviewer_tool_categories and (
            (not codegraph_required) or "codegraph" in reviewer_tool_categories
        )

        impact_metrics = dimensions.get("metrics", {})
        impact_v2 = (
            impact_metrics.get("impact_sufficiency_v2", {})
            if isinstance(impact_metrics, Mapping)
            else {}
        )
        impact_pass = bool(
            dimensions.get("gate_status") == "SUFFICIENT"
            and dimensions.get("code_impact_sufficiency_v2_ready") is True
            and isinstance(impact_v2, Mapping)
            and impact_v2.get("status") == "SUFFICIENT"
            and impact_v2.get("unaccounted_dimensions") == []
            and impact_v2.get("uncovered_symbol_ids") == []
            and impact_v2.get("uncovered_files") == []
        )

        requirement_ids = _strings(semantic.get("requirement_ids"))
        reverse = semantic.get("reverse_requirement_mappings")
        reverse_requirement_ids = {
            str(item.get("requirement_id"))
            for item in reverse
            if isinstance(item, Mapping) and isinstance(item.get("requirement_id"), str)
        } if isinstance(reverse, list) else set()
        reverse_complete = bool(
            requirement_ids
            and set(requirement_ids) == reverse_requirement_ids
        )
        changed_symbols = semantic.get("changed_symbols")
        changed_symbol_ids = {
            str(item.get("id"))
            for item in changed_symbols
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        } if isinstance(changed_symbols, list) else set()
        explained = semantic.get("symbol_explanations")
        explained_ids = {
            str(item.get("symbol_id"))
            for item in explained
            if isinstance(item, Mapping) and isinstance(item.get("symbol_id"), str)
        } if isinstance(explained, list) else set()
        symbols_explained = bool(changed_symbol_ids and changed_symbol_ids == explained_ids)

        gap_ids = _uniq(
            _strings(task.get("gap_refs")) + _strings(evaluation.get("gap_refs"))
        )
        active_gap_ids: List[str] = []
        for gap_id in gap_ids:
            gap = self._one("rc7_gap", gap_id=gap_id)
            if gap.get("mission_id") != mission_id:
                raise N3CompletionError(
                    "RC72_N3_COMPLETION_GAP_MISSION_MISMATCH:%s" % gap_id
                )
            if str(gap.get("state") or "") not in _CLOSED_GAP_STATES:
                active_gap_ids.append(gap_id)

        evidence_ids = _uniq(
            str(row["evidence_id"]) for row in all_evidence
            if isinstance(row.get("evidence_id"), str)
        )
        return {
            "application_id": application_id,
            "target_id": target_id,
            "dispatch_id": str(dispatch["dispatch_id"]),
            "task_id": task_id,
            "task_state": str(task["state"]),
            "artifact_id": artifact_id,
            "artifact_hash": str(artifact.get("content_hash") or ""),
            "evaluation_id": evaluation_id,
            "evaluation_result": str(evaluation.get("result") or ""),
            "repository_ref": str(dispatch.get("repository_ref") or ""),
            "source_revision": str(dispatch.get("source_revision") or ""),
            "source_mapping_artifact_id": str(dispatch.get("source_mapping_artifact_id") or ""),
            "source_mapping_evaluation_id": str(dispatch.get("source_mapping_evaluation_id") or ""),
            "source_commit_ok": dispatch.get("source_commit") == self.source_commit,
            "requirement_ids": requirement_ids,
            "reverse_complete": reverse_complete,
            "symbols_explained": symbols_explained,
            "unknowns_empty": semantic.get("candidate_unknowns") == [],
            "candidate_gaps_empty": semantic.get("candidate_gaps") == [],
            "codegraph_required": codegraph_required,
            "git_proven": git_proven,
            "codegraph_proven": codegraph_proven,
            "analyzer_worker_id": analyzer_id,
            "analyzer_session_id": analyzer_session,
            "reviewer_worker_id": reviewer_id,
            "reviewer_session_id": reviewer_session,
            "reviewer_independent": bool(reviewer_id and reviewer_id != analyzer_id),
            "fresh_review_session": bool(reviewer_session and reviewer_session != analyzer_session),
            "review_runtime_proven": reviewer_runtime_proven and reviewer_tools_proven,
            "impact_pass": impact_pass,
            "active_gap_ids": active_gap_ids,
            "evidence_ids": evidence_ids,
            "anchor_id": str(anchor.get("anchor_id") or ""),
            "raw_output_sha256": str(anchor.get("raw_output_sha256") or ""),
        }

    def _records(
        self, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
        batch, node, next_node, dispatches = self._context(release_batch_id)
        records = [
            self._target_record(batch=batch, dispatch=dispatch)
            for dispatch in dispatches
        ]
        if len(records) != len(dispatches):
            raise N3CompletionError("RC72_N3_COMPLETION_TARGET_SET_INCOMPLETE")
        identities = [(row["application_id"], row["target_id"]) for row in records]
        if len(identities) != len(set(identities)):
            raise N3CompletionError("RC72_N3_COMPLETION_TARGET_SET_NOT_UNIQUE")
        return batch, node, next_node, records

    @staticmethod
    def _record_signature(records: Sequence[Mapping[str, Any]]) -> str:
        return "|".join(
            "%s:%s:%s:%s:%s"
            % (
                row["application_id"],
                row["target_id"],
                row["artifact_id"],
                row["artifact_hash"],
                row["evaluation_id"],
            )
            for row in records
        )

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, _next_node, records = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        signature = self._record_signature(records)
        delivery_id = _stable_id(
            "N3DEL", mission_id, release_batch_id, self.source_commit, signature
        )
        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N3CompletionError("RC72_N3_COMPLETION_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=node_id
                )["state"],
                "known_gap_ids": list(existing[0].get("known_gaps") or []),
            }
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_DELIVERY_REQUIRES_RUNNING_NODE:%s"
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
                ["n3-dispatch://%s" % row["dispatch_id"] for row in records]
                + ["n3-anchor://%s" % row["anchor_id"] for row in records]
                + ["evaluation://%s" % row["evaluation_id"] for row in records]
                + ["source-mapping://%s" % row["source_mapping_artifact_id"] for row in records]
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
            "target_count": len(records),
            "passed_target_count": passed_count,
            "known_gap_ids": gaps,
        }

    def _criterion_results(
        self,
        *,
        batch: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]],
    ) -> Dict[str, bool]:
        canonical_requirements = _strings(batch.get("requirement_ids"))
        mapped_requirements = _uniq(
            requirement_id
            for row in records
            for requirement_id in row["requirement_ids"]
        )
        target_ids = [(row["application_id"], row["target_id"]) for row in records]
        return {
            "N3_CANONICAL_TARGET_SET_COMPLETE": bool(records and len(target_ids) == len(set(target_ids))),
            "N3_SOURCE_COMMIT_LINEAGE": all(row["source_commit_ok"] for row in records),
            "N3_SOURCE_MAPPING_LINEAGE_BOUND": all(
                bool(row["source_mapping_artifact_id"] and row["source_mapping_evaluation_id"])
                for row in records
            ),
            "N3_ALL_CODE_TASKS_PASS": all(
                row["task_state"] == TaskStatus.PASS.value for row in records
            ),
            "N3_ALL_CODE_EVALUATIONS_PASS": all(
                row["evaluation_result"] == "PASS" for row in records
            ),
            "N3_CANONICAL_ARTIFACTS_BOUND": all(
                bool(row["artifact_id"] and row["artifact_hash"] and row["raw_output_sha256"])
                for row in records
            ),
            "N3_CANONICAL_REQUIREMENT_REVERSE_MAPPING": (
                set(mapped_requirements) == set(canonical_requirements)
                and all(row["reverse_complete"] for row in records)
            ),
            "N3_REPOSITORY_REVISION_EXACT": all(
                bool(row["repository_ref"] and row["source_revision"]) for row in records
            ),
            "N3_REAL_GIT_PROOF": all(row["git_proven"] for row in records),
            "N3_REQUIRED_CODEGRAPH_PROOF": all(
                (not row["codegraph_required"]) or row["codegraph_proven"]
                for row in records
            ),
            "N3_REVIEWER_INDEPENDENT": all(
                row["reviewer_independent"] for row in records
            ),
            "N3_FRESH_REVIEW_SESSION": all(
                row["fresh_review_session"] for row in records
            ),
            "N3_REVIEW_RUNTIME_PROOF": all(
                row["review_runtime_proven"] for row in records
            ),
            "N3_IMPACT_SUFFICIENCY_V2_PASS": all(
                row["impact_pass"] and row["symbols_explained"] for row in records
            ),
            "N3_NO_CANDIDATE_UNKNOWNS": all(row["unknowns_empty"] for row in records),
            "N3_NO_CANDIDATE_GAPS": all(row["candidate_gaps_empty"] for row in records),
            "N3_NO_UNRESOLVED_ANALYSIS_GAPS": all(not row["active_gap_ids"] for row in records),
        }

    def apply_gate(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, next_node, records = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        active_version = node.get("active_delivery_version")
        if isinstance(active_version, bool) or not isinstance(active_version, int):
            raise N3CompletionError("RC72_N3_COMPLETION_ACTIVE_DELIVERY_REQUIRED")
        deliveries = [
            row
            for row in self.truth.query("rc72_node_delivery", mission_node_id=node_id)
            if row.get("version") == active_version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_ACTIVE_DELIVERY_NOT_UNIQUE:%d" % len(deliveries)
            )
        delivery = deliveries[0]
        if (
            list(delivery.get("artifact_refs") or []) != [row["artifact_id"] for row in records]
            or list(delivery.get("created_by_workitems") or []) != [row["task_id"] for row in records]
        ):
            raise N3CompletionError("RC72_N3_COMPLETION_DELIVERY_CURRENT_TRUTH_MISMATCH")

        criterion = self._criterion_results(batch=batch, records=records)
        passed = [name for name in _CRITERIA if criterion[name]]
        failed = [name for name in _CRITERIA if not criterion[name]]
        decision = NodeGateDecision.PASS if not failed else NodeGateDecision.NEEDS_REVISION
        gate_id = _stable_id(
            "N3GATE",
            str(delivery["delivery_id"]),
            self.source_commit,
            decision.value,
            ",".join(failed),
        )
        existing = self.truth.query("rc72_node_gate", gate_id=gate_id)
        if existing:
            if len(existing) != 1:
                raise N3CompletionError("RC72_N3_COMPLETION_GATE_NOT_UNIQUE")
            current_node = self._one("rc72_mission_node", mission_node_id=node_id)
            current_next = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if decision == NodeGateDecision.PASS:
                if current_node.get("state") != MissionNodeState.PASS.value:
                    raise N3CompletionError("RC72_N3_COMPLETION_EXISTING_PASS_GATE_NODE_NOT_PASS")
                if current_next.get("state") == MissionNodeState.NOT_STARTED.value:
                    RC72StateMachine(self.truth, release_id=release_id).forward(
                        _NODE, _NEXT_NODE, source_gate_id=gate_id
                    )
                    current_next = self._one(
                        "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
                    )
            return {
                "status": "RESUMED",
                "gate_id": gate_id,
                "decision": decision.value,
                "passed": passed,
                "failed": failed,
                "n3_state": current_node["state"],
                "n4_state": current_next["state"],
            }
        if node.get("state") != MissionNodeState.REVIEW_PENDING.value:
            raise N3CompletionError(
                "RC72_N3_COMPLETION_GATE_REQUIRES_REVIEW_PENDING:%s"
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
                "all canonical code targets passed independent fresh review and deterministic impact sufficiency"
                if decision == NodeGateDecision.PASS
                else "N3 deterministic criteria failed: %s" % ",".join(failed)
            ),
        )
        runtime = RC72StateMachine(self.truth, release_id=release_id)
        runtime.apply_gate(gate)
        n4_state = next_node["state"]
        if decision == NodeGateDecision.PASS:
            if next_node.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N3CompletionError(
                    "RC72_N3_COMPLETION_N4_PREMATURE_STATE:%s" % next_node.get("state")
                )
            runtime.forward(_NODE, _NEXT_NODE, source_gate_id=gate_id)
            n4_state = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )["state"]
        else:
            current_next = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if current_next.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N3CompletionError("RC72_N3_COMPLETION_REVISION_CANNOT_RELEASE_N4")
            n4_state = current_next["state"]
        return {
            "status": "GATE_APPLIED",
            "gate_id": gate_id,
            "decision": decision.value,
            "passed": passed,
            "failed": failed,
            "n3_state": (
                MissionNodeState.PASS.value
                if decision == NodeGateDecision.PASS
                else MissionNodeState.NEEDS_REVISION.value
            ),
            "n4_state": n4_state,
            "known_gap_ids": list(delivery.get("known_gaps") or []),
        }

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        delivery = self.admit_delivery(release_batch_id=release_batch_id)
        gate = self.apply_gate(release_batch_id=release_batch_id)
        return {"delivery": delivery, "gate": gate}


__all__ = ["N3CompletionError", "N3DeliveryGateService"]
