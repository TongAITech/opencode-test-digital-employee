"""RC7.2 N3 source revision independent review and recurrence loop.

A generation-2+ source-target revision is not accepted merely because a fresh
worker produced and promoted a new mapping candidate.  The latest revision must
pass the existing independent source-target reviewer.  A failed revision keeps
all ancestor mapping gaps open and immediately schedules the next governed
revision generation.  A later independent PASS is the only event allowed to
resolve the complete ancestor gap chain.

This service deliberately does not create or execute CODE_ANALYSIS work, does
not decide N3 NodeGate/PASS, does not release N4, and never claims field or
BANK_FINAL status.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import GapStatus, MissionStatus, TaskStatus
from .rc72_n3_source_target_review import (
    N3SourceTargetReviewResult,
    N3SourceTargetReviewService,
)
from .rc72_n3_source_target_revision import N3SourceTargetRevisionService
from .state_machine import transition_gap, transition_mission


_STAGE = "SOURCE_TARGET_DISCOVERY"
_GAP_CATEGORY = "SOURCE_TARGET_MAPPING_GAP"


class N3SourceTargetRevisionReviewLoopError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetRevisionReviewLoopError(
            "RC72_N3_SOURCE_REV_REVIEW_%s_REQUIRED" % name.upper()
        )
    return value.strip()


class N3SourceTargetRevisionReviewLoopService:
    """Independently review the latest N3 revision and continue until proven."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.control = ClosedLoopControlPlane(
            truth, self.release_id, self.mission_id
        )
        self.reviewer = N3SourceTargetReviewService(
            self.control,
            launcher,
            allowed_tools=allowed_tools,
        )
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _latest_revision(
        self, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        rows = [
            row
            for row in self.truth.query(
                "rc72_n3_source_target_revision",
                release_batch_id=release_batch_id,
            )
            if row.get("source_commit") == self.source_commit
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("application_id") == application_id
            and row.get("status") == "LEASED_FOR_HANDOFF"
        ]
        if not rows:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_REVISION_REQUIRED"
            )
        generation = max(int(row.get("revision_generation") or 0) for row in rows)
        exact = [
            row for row in rows
            if int(row.get("revision_generation") or 0) == generation
        ]
        if generation < 2 or len(exact) != 1:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_LATEST_REVISION_NOT_UNIQUE"
            )
        return exact[0]

    def _revision_chain(
        self, latest: Mapping[str, Any]
    ) -> Tuple[Dict[str, Any], ...]:
        chain: List[Dict[str, Any]] = [dict(latest)]
        seen = {str(latest["revision_id"])}
        current = dict(latest)
        while True:
            previous_workitem_id = _required(
                current.get("previous_workitem_id"), "previous_workitem_id"
            )
            rows = self.truth.query(
                "rc72_n3_source_target_revision",
                revision_workitem_id=previous_workitem_id,
            )
            if not rows:
                break
            if len(rows) != 1:
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_ANCESTOR_REVISION_NOT_UNIQUE"
                )
            previous = rows[0]
            revision_id = _required(previous.get("revision_id"), "revision_id")
            if revision_id in seen:
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_REVISION_CYCLE"
                )
            if (
                previous.get("mission_id") != self.mission_id
                or previous.get("release_id") != self.release_id
                or previous.get("release_batch_id") != latest.get("release_batch_id")
                or previous.get("application_id") != latest.get("application_id")
                or previous.get("source_commit") != self.source_commit
            ):
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_ANCESTOR_LINEAGE_MISMATCH"
                )
            if int(previous.get("revision_generation") or 0) >= int(
                current.get("revision_generation") or 0
            ):
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_GENERATION_ORDER_INVALID"
                )
            seen.add(revision_id)
            chain.append(previous)
            current = previous
        return tuple(chain)

    def _ancestor_gap_refs(
        self, latest: Mapping[str, Any]
    ) -> Tuple[str, ...]:
        refs: List[str] = []
        for revision in self._revision_chain(latest):
            for gap_id in list(revision.get("gap_refs") or []):
                value = _required(gap_id, "gap_id")
                if value not in refs:
                    refs.append(value)
        if not refs:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_ANCESTOR_GAPS_REQUIRED"
            )
        for gap_id in refs:
            gap = self._one("rc7_gap", gap_id=gap_id)
            if (
                gap.get("mission_id") != self.mission_id
                or gap.get("source_node") != _STAGE
                or gap.get("target_node") != _STAGE
                or gap.get("category") != _GAP_CATEGORY
            ):
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_ANCESTOR_GAP_INVALID:%s"
                    % gap_id
                )
        return tuple(refs)

    def _context(
        self, release_batch_id: str, application_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str, Tuple[str, ...]]:
        batch = self._one(
            "rc72_release_batch", release_batch_id=release_batch_id
        )
        if (
            batch.get("mission_id") != self.mission_id
            or batch.get("release_id") != self.release_id
            or application_id not in list(batch.get("application_ids") or [])
        ):
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_RELEASE_BATCH_LINEAGE_MISMATCH"
            )
        revision = self._latest_revision(release_batch_id, application_id)
        task = self._one(
            "rc7_task", task_id=str(revision["revision_workitem_id"])
        )
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != _STAGE
            or task.get("lease_owner")
            != revision.get("revision_worker_instance_id")
            or task.get("state")
            not in {
                TaskStatus.OUTPUT_PRODUCED.value,
                TaskStatus.PASS.value,
                TaskStatus.REPAIR_REQUIRED.value,
            }
        ):
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_LATEST_REVISION_NOT_REVIEWABLE:%s"
                % str(task.get("state") or "UNKNOWN")
            )
        artifact_refs = list(task.get("output_artifact_refs") or [])
        if len(artifact_refs) != 1:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_OUTPUT_ARTIFACT_NOT_UNIQUE"
            )
        artifact_id = _required(artifact_refs[0], "artifact_id")
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("mission_id") != self.mission_id
            or artifact.get("producer_task_id") != task.get("task_id")
            or artifact.get("artifact_type_name")
            != "SOURCE_TARGET_MAPPING_CANDIDATE"
            or artifact.get("state") != "VALID"
            or str(revision["previous_artifact_id"])
            not in list(artifact.get("parent_refs") or [])
        ):
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_ARTIFACT_LINEAGE_INVALID"
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        if durable.semantic_payload.get("application_id") != application_id:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_APPLICATION_MISMATCH"
            )
        return revision, task, artifact_id, self._ancestor_gap_refs(revision)

    def _persist_gap(self, gap) -> None:
        self.control._persist_gap(gap)

    def _resolve_ancestor_gaps(
        self, gap_refs: Sequence[str], evaluation_id: str
    ) -> None:
        for gap_id in gap_refs:
            gap = self.control._gap(str(gap_id))
            if gap.state == GapStatus.RESOLVED:
                if gap.resolution_evaluation_id != evaluation_id:
                    raise N3SourceTargetRevisionReviewLoopError(
                        "RC72_N3_SOURCE_REV_REVIEW_GAP_RESOLUTION_CONFLICT:%s"
                        % gap_id
                    )
                continue
            if gap.state == GapStatus.OPEN:
                transition_gap(gap, GapStatus.PLANNED)
                self._persist_gap(gap)
            if gap.state == GapStatus.PLANNED:
                transition_gap(gap, GapStatus.REPAIRING)
                self._persist_gap(gap)
            if gap.state == GapStatus.REPAIRING:
                transition_gap(gap, GapStatus.EVIDENCE_PENDING)
                self._persist_gap(gap)
            if gap.state != GapStatus.EVIDENCE_PENDING:
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_GAP_NOT_RESOLVABLE:%s:%s"
                    % (gap_id, gap.state.value)
                )
            transition_gap(
                gap,
                GapStatus.RESOLVED,
                resolution_evaluation_id=evaluation_id,
            )
            self._persist_gap(gap)

        mission = self.control._mission()
        if (
            mission.state == MissionStatus.REPAIRING
            and not self.control._open_gap_rows()
        ):
            transition_mission(mission, MissionStatus.RUNNING)
            self.control._persist_mission(mission)
        self.control._sync_mission(self.control._mission())

    def _validate_failed_review_gaps(
        self,
        review: N3SourceTargetReviewResult,
        ancestor_gap_refs: Sequence[str],
    ) -> Tuple[str, ...]:
        gap_ids = tuple(str(item) for item in review.gap_ids)
        if not gap_ids:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_FAILED_REVIEW_GAPS_REQUIRED"
            )
        if set(gap_ids).intersection(set(ancestor_gap_refs)):
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_NEW_GAP_COLLIDES_WITH_ANCESTOR"
            )
        for gap_id in gap_ids:
            gap = self._one("rc7_gap", gap_id=gap_id)
            if (
                gap.get("mission_id") != self.mission_id
                or gap.get("source_node") != _STAGE
                or gap.get("target_node") != _STAGE
                or gap.get("category") != _GAP_CATEGORY
                or gap.get("state") != GapStatus.OPEN.value
            ):
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_NEW_GAP_INVALID:%s" % gap_id
                )
        return gap_ids

    def close_latest_revision(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        application_id = _required(application_id, "application_id")
        revision, task_before, artifact_id, ancestor_gap_refs = self._context(
            release_batch_id, application_id
        )
        terminal_before = task_before.get("state") in {
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }

        review = self.reviewer.review_and_apply(
            task_id=str(revision["revision_workitem_id"]),
            artifact_id=artifact_id,
        )
        evaluation = self._one(
            "rc7_evaluation", evaluation_id=review.evaluation_id
        )
        if (
            evaluation.get("mission_id") != self.mission_id
            or evaluation.get("node") != _STAGE
            or artifact_id not in list(evaluation.get("artifact_refs") or [])
            or evaluation.get("result") != review.evaluation_result
        ):
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_EVALUATION_LINEAGE_INVALID"
            )

        if review.evaluation_result == "PASS":
            if review.gap_ids:
                raise N3SourceTargetRevisionReviewLoopError(
                    "RC72_N3_SOURCE_REV_REVIEW_PASS_WITH_GAPS_FORBIDDEN"
                )
            self._resolve_ancestor_gaps(
                ancestor_gap_refs, review.evaluation_id
            )
            return {
                "status": "RESUMED" if terminal_before else "CLOSED",
                "release_batch_id": release_batch_id,
                "application_id": application_id,
                "revision_id": str(revision["revision_id"]),
                "revision_generation": int(revision["revision_generation"]),
                "revision_workitem_id": str(revision["revision_workitem_id"]),
                "revision_artifact_id": artifact_id,
                "evaluation_id": review.evaluation_id,
                "evaluation_result": review.evaluation_result,
                "reviewer_worker_id": review.reviewer_worker_id,
                "reviewer_session_id": review.reviewer_session_id,
                "ancestor_gap_refs": list(ancestor_gap_refs),
                "resolved_gap_refs": list(ancestor_gap_refs),
                "next_revision": None,
                "task_state": TaskStatus.PASS.value,
            }

        if review.evaluation_result != "REPAIR_REQUIRED":
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_RESULT_UNSUPPORTED:%s"
                % review.evaluation_result
            )
        new_gap_refs = self._validate_failed_review_gaps(
            review, ancestor_gap_refs
        )
        planned = N3SourceTargetRevisionService(
            self.truth, source_commit=self.source_commit
        ).plan_and_assign(release_batch_id=release_batch_id)
        candidates = [
            row for row in list(planned.get("revisions") or [])
            if row.get("application_id") == application_id
            and row.get("trigger_evaluation_id") == review.evaluation_id
        ]
        if len(candidates) != 1:
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_NEXT_REVISION_NOT_UNIQUE:%d"
                % len(candidates)
            )
        next_revision = candidates[0]
        if (
            int(next_revision.get("revision_generation") or 0)
            != int(revision["revision_generation"]) + 1
            or next_revision.get("previous_workitem_id")
            != revision.get("revision_workitem_id")
            or next_revision.get("previous_artifact_id") != artifact_id
            or set(next_revision.get("gap_refs") or []) != set(new_gap_refs)
        ):
            raise N3SourceTargetRevisionReviewLoopError(
                "RC72_N3_SOURCE_REV_REVIEW_NEXT_REVISION_LINEAGE_INVALID"
            )
        self.control._sync_mission(self.control._mission())
        return {
            "status": "REVISION_SCHEDULED",
            "release_batch_id": release_batch_id,
            "application_id": application_id,
            "revision_id": str(revision["revision_id"]),
            "revision_generation": int(revision["revision_generation"]),
            "revision_workitem_id": str(revision["revision_workitem_id"]),
            "revision_artifact_id": artifact_id,
            "evaluation_id": review.evaluation_id,
            "evaluation_result": review.evaluation_result,
            "reviewer_worker_id": review.reviewer_worker_id,
            "reviewer_session_id": review.reviewer_session_id,
            "ancestor_gap_refs": list(ancestor_gap_refs),
            "resolved_gap_refs": [],
            "new_gap_refs": list(new_gap_refs),
            "next_revision": dict(next_revision),
            "task_state": TaskStatus.STALE.value,
        }
