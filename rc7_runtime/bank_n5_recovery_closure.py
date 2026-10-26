"""BANK/N8-aware N5 current-attempt selection.

Generic N5 correctly rejects duplicate per-Case finalizations. BANK recovery adds
one narrowly-governed exception: multiple historical finalizations for the same
Case may coexist only when durable N8 retry receipts prove a complete predecessor
-> successor chain. The chain tip is the current finalization; history remains
immutable and unapproved duplicates still fail closed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from . import bank_autonomous_preparation_closure as base
from .bank_n8_recovery import BankN8RecoveryCoordinator, BankN8RecoveryError, _file_payload
from .case_runtime import PREPARED_ATTEMPT_KIND


class BankN5RecoveryAwarePreparationClosureCoordinator(
    base.BankAutonomousPreparationClosureCoordinator
):
    """Keep generic N5 strict while admitting only proven N8 successor history."""

    @staticmethod
    def _n8_direct_edge(
        control,
        *,
        execution_task_id: str,
        tc_id: str,
        successor_attempt_id: str,
    ) -> Tuple[str, str]:
        prepared_rows = [
            row for row in control.truth.query("rc7_evidence", mission_id=control.mission_id)
            if row.get("kind") == PREPARED_ATTEMPT_KIND
            and execution_task_id in set(str(x) for x in row.get("subject_refs") or [])
            and successor_attempt_id in set(str(x) for x in row.get("subject_refs") or [])
        ]
        if len(prepared_rows) != 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_SUCCESSOR_PREPARED_NOT_UNIQUE:%s:%d"
                % (successor_attempt_id, len(prepared_rows))
            )
        prepared_row = prepared_rows[0]
        if prepared_row.get("source_ref") != "runtime://bank-n8/direct-retry-successor":
            return "", ""

        auth_rows = []
        for ref in prepared_row.get("subject_refs") or []:
            rows = control.truth.query("rc7_evidence", evidence_id=str(ref))
            if len(rows) == 1 and rows[0].get("kind") == BankN8RecoveryCoordinator.DIRECT_RECEIPT_TYPE:
                auth_rows.append(rows[0])
        if len(auth_rows) != 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_AUTHORIZATION_NOT_UNIQUE:%s:%d"
                % (successor_attempt_id, len(auth_rows))
            )
        try:
            auth = _file_payload(auth_rows[0], "BANK_N5_N8_DIRECT_RECEIPT")
        except BankN8RecoveryError as exc:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_AUTHORIZATION_INVALID:%s" % exc
            ) from exc
        predecessor = str(auth.get("source_attempt_id") or "")
        successor = str(auth.get("successor_attempt_id") or "")
        if (
            auth.get("source_task_id") != execution_task_id
            or successor != successor_attempt_id
            or not predecessor
            or predecessor == successor
            or auth.get("business_action_executed") is not False
        ):
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_AUTHORIZATION_IDENTITY_MISMATCH:%s" % successor_attempt_id
            )
        gap_id = str(auth.get("gap_id") or "")
        gaps = control.truth.query("rc7_gap", gap_id=gap_id)
        if len(gaps) != 1 or tc_id not in set(str(x) for x in gaps[0].get("subject_refs") or []):
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_AUTHORIZATION_CASE_MISMATCH:%s" % successor_attempt_id
            )
        return predecessor, successor

    def _select_current_finalization(
        self,
        control,
        *,
        execution_task_id: str,
        tc_id: str,
        candidates,
    ):
        if len(candidates) == 1:
            return candidates[0]
        by_attempt = {}
        for candidate in candidates:
            attempt_id = str(candidate[2].get("attempt_id") or "")
            if not attempt_id:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_FINALIZATION_ATTEMPT_REQUIRED:%s" % tc_id
                )
            if attempt_id in by_attempt:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_FINALIZATION_DUPLICATE_ATTEMPT:%s:%s" % (tc_id, attempt_id)
                )
            by_attempt[attempt_id] = candidate

        edges: Dict[str, str] = {}
        reverse: Dict[str, str] = {}
        for attempt_id in sorted(by_attempt):
            predecessor, successor = self._n8_direct_edge(
                control,
                execution_task_id=execution_task_id,
                tc_id=tc_id,
                successor_attempt_id=attempt_id,
            )
            if not predecessor:
                continue
            if predecessor not in by_attempt or successor not in by_attempt:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_RECOVERY_CHAIN_OUTSIDE_CURRENT_RUN:%s:%s:%s"
                    % (tc_id, predecessor, successor)
                )
            if predecessor in edges and edges[predecessor] != successor:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_RECOVERY_CHAIN_BRANCH_FORBIDDEN:%s:%s" % (tc_id, predecessor)
                )
            if successor in reverse and reverse[successor] != predecessor:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_RECOVERY_CHAIN_MERGE_FORBIDDEN:%s:%s" % (tc_id, successor)
                )
            edges[predecessor] = successor
            reverse[successor] = predecessor

        # N attempts require exactly N-1 proven successor edges. This rejects
        # arbitrary duplicate history, orphan attempts, missing authorizations,
        # and disconnected retry chains.
        if len(edges) != len(by_attempt) - 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_FINALIZATION_DUPLICATE_TC_WITHOUT_COMPLETE_N8_CHAIN:%s" % tc_id
            )
        roots = sorted(set(by_attempt) - set(reverse))
        tips = sorted(set(by_attempt) - set(edges))
        if len(roots) != 1 or len(tips) != 1:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_CHAIN_NOT_LINEAR:%s" % tc_id
            )
        visited = set()
        current = roots[0]
        while current in edges:
            if current in visited:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_RECOVERY_CHAIN_CYCLE:%s" % tc_id
                )
            visited.add(current)
            current = edges[current]
        visited.add(current)
        if visited != set(by_attempt) or current != tips[0]:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_RECOVERY_CHAIN_INCOMPLETE:%s" % tc_id
            )
        return by_attempt[current]

    def _aggregate_if_complete(
        self,
        control,
        *,
        run_id: str,
        execution_task_id: str,
        batch,
        accepted_cases: Sequence[Mapping[str, Any]],
    ) -> Tuple[bool, str]:
        expected = {
            self.service.parser.parse(dict(case)).tc_id: base._sha(dict(case))
            for case in accepted_cases
        }
        grouped = {}
        for row in control.truth.query("rc7_artifact", mission_id=control.mission_id):
            if row.get("artifact_type_name") != self.service.FINALIZATION_TYPE:
                continue
            payload, artifact_row = self._artifact_payload(
                control,
                str(row["artifact_id"]),
                self.service.FINALIZATION_TYPE,
            )
            if (
                payload.get("run_id") != run_id
                or payload.get("target_id") != self.target_id
                or payload.get("batch_plan_artifact_id") != batch.artifact_id
            ):
                continue
            tc_id = str(payload.get("tc_id") or "")
            if tc_id not in expected:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_FINALIZATION_UNKNOWN_TC:%s" % tc_id
                )
            if payload.get("case_hash") != expected[tc_id]:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_FINALIZATION_CASE_DRIFT:%s" % tc_id
                )
            evidence_refs = [
                str(x) for x in artifact_row.get("evidence_refs") or [] if str(x)
            ]
            if len(evidence_refs) != 1:
                raise base.BankAutonomousPreparationClosureError(
                    "BANK_N5_FINALIZATION_EVIDENCE_NOT_UNIQUE:%s" % tc_id
                )
            grouped.setdefault(tc_id, []).append(
                (str(artifact_row["artifact_id"]), evidence_refs[0], payload)
            )

        finals = {
            tc_id: self._select_current_finalization(
                control,
                execution_task_id=execution_task_id,
                tc_id=tc_id,
                candidates=candidates,
            )
            for tc_id, candidates in grouped.items()
        }
        if set(finals) != set(expected):
            return False, ""

        aggregate_payload = {
            "mission_id": control.mission_id,
            "release_id": control.release_id,
            "run_id": run_id,
            "target_id": self.target_id,
            "batch_plan_artifact_id": batch.artifact_id,
            "case_denominator": sorted(expected),
            "case_hashes": {key: expected[key] for key in sorted(expected)},
            "case_finalization_artifact_ids": [finals[key][0] for key in sorted(finals)],
            "case_finalization_evidence_ids": [finals[key][1] for key in sorted(finals)],
            "current_attempt_ids": {
                key: str(finals[key][2].get("attempt_id") or "") for key in sorted(finals)
            },
            "recovery_successor_aware": True,
            "status": "PREPARATION_DENOMINATOR_COMPLETE",
            "execution_proof": False,
        }
        aggregate_artifact_id, aggregate_evidence_id, aggregate_digest = self.service._persist_artifact(
            control,
            artifact_type=self.AGGREGATE_TYPE,
            producer_task_id=execution_task_id,
            payload=aggregate_payload,
            parent_refs=[batch.artifact_id] + [finals[key][0] for key in sorted(finals)],
            evidence_kind="PREPARATION_BATCH_FINALIZATION_RECORD",
            subject_refs=[run_id, self.target_id] + sorted(finals),
            relative=Path("n5") / control.mission_id / run_id / "batch-finalization.json",
        )
        evaluation_id = base._stable_id(
            "EVAL-N5-BATCH", control.mission_id, run_id, batch.plan_hash, aggregate_digest
        )
        evaluation_evidence = tuple(dict.fromkeys(
            [batch.evidence_id, aggregate_evidence_id]
            + [finals[key][1] for key in sorted(finals)]
        ))
        evaluation = base.Evaluation(
            evaluation_id=evaluation_id,
            mission_id=control.mission_id,
            node="TEST_DATA_PREPARATION",
            artifact_refs=[aggregate_artifact_id],
            result=base.EvaluationResult.PASS,
            evaluator_ref="rc7-runtime-preparation-aggregate-authority",
            dimensions={
                "gate_status": "PREPARATION_DENOMINATOR_COMPLETE",
                "target_id": self.target_id,
                "case_denominator": sorted(expected),
                "current_attempt_ids": aggregate_payload["current_attempt_ids"],
                "recovery_successor_aware": True,
                "prepared_case_count": len(finals),
                "required_case_count": len(expected),
                "batch_plan_is_execution_proof": False,
            },
            gap_refs=[],
            evidence_refs=list(evaluation_evidence),
        )
        if not control.truth.query("rc7_evaluation", evaluation_id=evaluation_id):
            base.append_entity(control.truth, evaluation, release_id=control.release_id)
        task_id = base._stable_id(
            "TASK-N5-BATCH", control.mission_id, run_id, batch.plan_hash, aggregate_digest
        )
        if not control.truth.query("rc7_task", task_id=task_id):
            base.append_entity(
                control.truth,
                base.Task(
                    task_id=task_id,
                    mission_id=control.mission_id,
                    node="TEST_DATA_PREPARATION",
                    task_type="RUNTIME",
                    objective="close preparation only after the accepted Case denominator is current and prepared",
                    state=base.TaskStatus.PASS,
                    input_artifact_refs=[batch.artifact_id] + [finals[key][0] for key in sorted(finals)],
                    acceptance_criteria=[
                        "every accepted Case has current per-case finalization",
                        "recovery history is admitted only through a complete durable N8 successor chain",
                        "all current finalizations bind the same run, target, and batch plan",
                        "batch planning is not execution proof",
                    ],
                    lease_owner="rc7-runtime-preparation-aggregate",
                    output_artifact_refs=[aggregate_artifact_id],
                    evaluation_id=evaluation_id,
                ),
                release_id=control.release_id,
            )
        adoption = base.WaveCNodeAdoptionControl(
            control.truth,
            release_id=control.release_id,
            evidence_root=str(self.evidence_root),
        )
        input_version = "%s|%s|%s|%s" % (
            self.target_id,
            batch.plan_hash,
            aggregate_digest,
            ",".join(sorted(expected)),
        )
        delta_hash = "sha256:" + hashlib.sha256(
            (input_version + "|" + aggregate_evidence_id).encode("utf-8")
        ).hexdigest()
        iteration = adoption.node_control.latest_iteration(
            mission_id=control.mission_id, run_id=run_id, node_id="N5"
        )
        if iteration is None:
            iteration = adoption.node_control.start_iteration(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N5",
                input_version=input_version,
                delta_hash=delta_hash,
            )
        elif iteration.input_version != input_version or iteration.delta_hash != delta_hash:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_CURRENT_RUN_SOURCE_CHANGED_REQUIRES_REPAIR"
            )
        delivery = adoption.node_control.latest_delivery(
            mission_id=control.mission_id, run_id=run_id, node_id="N5"
        )
        all_artifacts = [batch.artifact_id, aggregate_artifact_id] + [
            finals[key][0] for key in sorted(finals)
        ]
        all_evidence = list(evaluation_evidence) + [
            finals[key][1] for key in sorted(finals)
        ]
        if delivery is None:
            delivery = adoption.publish_ready_from_evaluated_task(
                iteration=iteration,
                source_task_id=task_id,
                source_evaluation_id=evaluation_id,
                artifact_refs=list(dict.fromkeys(all_artifacts)),
                evidence_refs=list(dict.fromkeys(all_evidence)),
                member_ids=["rc7-runtime-preparation-aggregate"],
                coverage_summary={
                    "required_cases": len(expected),
                    "prepared_cases": len(finals),
                    "coverage": "100%",
                },
                reviewer_result={
                    "result": "PASS",
                    "runtime_owned": True,
                    "evaluator_ref": evaluation.evaluator_ref,
                },
                sufficiency_result={
                    "result": "PASS",
                    "current_prepared_attempts": True,
                    "recovery_successor_chain_verified": True,
                    "reservations_verified": True,
                    "freshness_verified": True,
                    "accepted_case_denominator_complete": True,
                    "batch_plan_is_execution_proof": False,
                },
            )
        elif delivery.iteration_count != iteration.iteration_count:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_STALE_DELIVERY_FORBIDDEN"
            )
        try:
            decision = adoption.director_accept(
                mission_id=control.mission_id,
                run_id=run_id,
                node_id="N5",
                director_ref=self.director_ref,
            )
        except base.AutonomousNodeAdoptionError as exc:
            raise base.BankAutonomousPreparationClosureError(
                "BANK_N5_DIRECTOR_GATE_FAILED:%s" % exc
            ) from exc
        return True, decision.evaluation_id
