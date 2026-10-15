"""Formal-execution guard for RC7 Mission Evidence snapshots.

The base R1 snapshot builder derives denominators and counters from durable truth.
This production builder additionally proves that every conclusive Execution used
as Mission verification is backed by runtime-owned execution evidence.  A model
or generic worker NODE_OUTPUT_PROOF can never certify a Test Case as verified.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from rc6_runtime.truth import TruthRuntime

from .mission_evidence_builder import (
    MissionEvidenceBuildError,
    R1MissionEvidenceSnapshotBuilder,
)


class R1FormalMissionEvidenceSnapshotBuilder(R1MissionEvidenceSnapshotBuilder):
    FORMAL_EXECUTION_KIND = "RUNTIME_EXECUTION_RECORD"
    FORMAL_EXECUTION_SOURCE = "runtime://formal-execution"

    def _execution_truth(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        by_case, basis = super()._execution_truth(truth, mission_id=mission_id)
        for item in basis:
            evaluation_id = str(item["evaluation_id"])
            attempt_id = str(item["attempt_id"])
            tc_id = str(item["tc_id"])
            artifact_id = str(item["artifact_refs"][0])

            evaluations = truth.query("rc7_evaluation", evaluation_id=evaluation_id)
            if len(evaluations) != 1 or evaluations[0].get("mission_id") != mission_id:
                raise MissionEvidenceBuildError(
                    "MISSION_EXECUTION_EVALUATION_NOT_DURABLE:%s" % evaluation_id
                )
            artifact_rows = truth.query("rc7_artifact", artifact_id=artifact_id)
            if len(artifact_rows) != 1 or artifact_rows[0].get("mission_id") != mission_id:
                raise MissionEvidenceBuildError(
                    "MISSION_EXECUTION_ARTIFACT_NOT_DURABLE:%s" % artifact_id
                )
            _, payload = self._file_artifact(
                truth,
                mission_id,
                artifact_id,
                "EXECUTION_CONCLUSION",
            )
            record = payload.get("record")
            if not isinstance(record, dict):
                raise MissionEvidenceBuildError("MISSION_EXECUTION_RECORD_REQUIRED")

            evidence_ids = []
            for source in (
                artifact_rows[0].get("evidence_refs", []),
                evaluations[0].get("evidence_refs", []),
                record.get("evidence_refs", []),
            ):
                if not isinstance(source, list):
                    raise MissionEvidenceBuildError(
                        "MISSION_EXECUTION_EVIDENCE_REFS_INVALID:%s" % artifact_id
                    )
                for value in source:
                    if not isinstance(value, str) or not value:
                        raise MissionEvidenceBuildError(
                            "MISSION_EXECUTION_EVIDENCE_REF_INVALID:%s" % artifact_id
                        )
                    if value not in evidence_ids:
                        evidence_ids.append(value)
            if not evidence_ids:
                raise MissionEvidenceBuildError(
                    "MISSION_EXECUTION_DURABLE_EVIDENCE_REQUIRED:%s" % artifact_id
                )

            rows = []
            for evidence_id in evidence_ids:
                matches = truth.query("rc7_evidence", evidence_id=evidence_id)
                if len(matches) != 1 or matches[0].get("mission_id") != mission_id:
                    raise MissionEvidenceBuildError(
                        "MISSION_EXECUTION_EVIDENCE_NOT_DURABLE:%s" % evidence_id
                    )
                rows.append(matches[0])

            formal = [
                row
                for row in rows
                if row.get("kind") == self.FORMAL_EXECUTION_KIND
                and row.get("source_ref") == self.FORMAL_EXECUTION_SOURCE
                and attempt_id in set(row.get("subject_refs", []))
                and tc_id in set(row.get("subject_refs", []))
            ]
            if not formal:
                raise MissionEvidenceBuildError(
                    "MISSION_FORMAL_RUNTIME_EXECUTION_PROOF_REQUIRED:%s:%s"
                    % (attempt_id, tc_id)
                )
            item["formal_execution_evidence_ids"] = sorted(
                str(row["evidence_id"]) for row in formal
            )
        return by_case, basis
