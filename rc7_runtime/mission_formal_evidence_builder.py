"""Formal-execution guard for RC7 Mission Evidence snapshots.

The base R1 snapshot builder derives denominators and counters from durable truth.
This production builder additionally proves that every Execution considered by
Mission verification is backed by runtime-owned execution evidence. Verification
uses only the latest ordinary formal execution for a Case and that latest result
must be PASS. Defect-reproduction work remains auditable execution evidence but
never contributes to Mission coverage numerators.

A matching evidence id/subject label is not sufficient.  The formal execution
record must be a content-addressed file whose SHA256 matches R1 and whose core
ExecutionRecord fields are identical to the EXECUTION_CONCLUSION being counted.
This prevents evidence splicing from inflating Mission coverage.

"Latest" is defined by the first durable R1 append sequence of the immutable
Evaluation, never wall-clock timestamps, lexical ids, or projection iteration
order. This keeps fix-verification ordering deterministic across fast executions,
process restarts, and replay.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime.truth import TruthRuntime

from .mission_evidence_builder import (
    MissionEvidenceBuildError,
    R1MissionEvidenceSnapshotBuilder,
)


class R1FormalMissionEvidenceSnapshotBuilder(R1MissionEvidenceSnapshotBuilder):
    FORMAL_EXECUTION_KIND = "RUNTIME_EXECUTION_RECORD"
    FORMAL_EXECUTION_SOURCE = "runtime://formal-execution"
    NON_VERIFICATION_PURPOSES = {"DEFECT_REPRODUCTION"}
    _BOUND_RECORD_FIELDS = (
        "attempt_id",
        "tc_id",
        "case_version",
        "target_id",
        "layer",
        "status",
        "integrity_passed",
        "actual_result",
        "assertion_ref",
        "assertion_passed",
    )

    @staticmethod
    def _evaluation_first_sequences(
        truth: TruthRuntime,
        *,
        mission_id: str,
    ) -> Dict[str, int]:
        sequences: Dict[str, int] = {}
        for raw in truth.store.iter_raw():
            if raw.get("event_type") != "RC7_EVALUATION_UPSERTED":
                continue
            payload = raw.get("payload")
            seq = raw.get("seq")
            if not isinstance(payload, dict) or not isinstance(seq, int):
                continue
            if payload.get("mission_id") != mission_id:
                continue
            evaluation_id = payload.get("evaluation_id")
            if not isinstance(evaluation_id, str) or not evaluation_id:
                continue
            current = sequences.get(evaluation_id)
            if current is None or seq < current:
                sequences[evaluation_id] = seq
        return sequences

    @classmethod
    def _bound_formal_execution_record(
        cls,
        row: Mapping[str, Any],
        *,
        attempt_id: str,
        tc_id: str,
        conclusion_record: Mapping[str, Any],
    ) -> Dict[str, Any]:
        evidence_id = str(row.get("evidence_id") or "")
        if row.get("kind") != cls.FORMAL_EXECUTION_KIND or row.get("source_ref") != cls.FORMAL_EXECUTION_SOURCE:
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_IDENTITY_INVALID:%s" % evidence_id
            )
        subjects = set(row.get("subject_refs", []))
        if attempt_id not in subjects or tc_id not in subjects:
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_SUBJECT_MISMATCH:%s" % evidence_id
            )
        content_ref = row.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref.startswith("file://"):
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_FILE_REQUIRED:%s" % evidence_id
            )
        path = Path(content_ref[len("file://"):])
        if not path.is_file():
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_FILE_MISSING:%s" % evidence_id
            )
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if row.get("content_hash") != "sha256:" + digest:
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_HASH_MISMATCH:%s" % evidence_id
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_JSON_INVALID:%s" % evidence_id
            ) from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("record"), dict):
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_RECORD_REQUIRED:%s" % evidence_id
            )
        formal_record = payload["record"]
        mismatched = [
            field
            for field in cls._BOUND_RECORD_FIELDS
            if formal_record.get(field) != conclusion_record.get(field)
        ]
        if mismatched:
            raise MissionEvidenceBuildError(
                "MISSION_FORMAL_RUNTIME_EXECUTION_RECORD_MISMATCH:%s:%s"
                % (evidence_id, ",".join(mismatched))
            )
        return formal_record

    def _execution_truth(
        self,
        truth: TruthRuntime,
        *,
        mission_id: str,
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        _, basis = super()._execution_truth(truth, mission_id=mission_id)
        evaluation_sequences = self._evaluation_first_sequences(
            truth,
            mission_id=mission_id,
        )
        latest_ordinary_by_case: Dict[str, Tuple[int, Dict[str, Any]]] = {}

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
            evaluation = evaluations[0]
            evaluation_seq = evaluation_sequences.get(evaluation_id)
            if evaluation_seq is None:
                raise MissionEvidenceBuildError(
                    "MISSION_EXECUTION_EVALUATION_SEQUENCE_REQUIRED:%s" % evaluation_id
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
                evaluation.get("evidence_refs", []),
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
            if len(formal) != 1:
                raise MissionEvidenceBuildError(
                    "MISSION_FORMAL_RUNTIME_EXECUTION_PROOF_NOT_UNIQUE:%s:%s:%d"
                    % (attempt_id, tc_id, len(formal))
                )
            self._bound_formal_execution_record(
                formal[0],
                attempt_id=attempt_id,
                tc_id=tc_id,
                conclusion_record=record,
            )
            item["formal_execution_evidence_ids"] = [str(formal[0]["evidence_id"])]
            item["formal_execution_content_hash"] = formal[0].get("content_hash")

            dimensions = evaluation.get("dimensions")
            if not isinstance(dimensions, dict):
                raise MissionEvidenceBuildError(
                    "MISSION_EXECUTION_EVALUATION_DIMENSIONS_REQUIRED:%s" % evaluation_id
                )
            purpose = dimensions.get("purpose")
            item["purpose"] = purpose
            item["evaluation_r1_seq"] = evaluation_seq
            if purpose in self.NON_VERIFICATION_PURPOSES:
                continue

            current = latest_ordinary_by_case.get(tc_id)
            if current is None or evaluation_seq > current[0]:
                latest_ordinary_by_case[tc_id] = (evaluation_seq, item)

        verified_by_case = {
            tc_id: item
            for tc_id, (_, item) in latest_ordinary_by_case.items()
            if item.get("conclusive") is True and item.get("test_result") == "PASS"
        }
        return verified_by_case, basis
