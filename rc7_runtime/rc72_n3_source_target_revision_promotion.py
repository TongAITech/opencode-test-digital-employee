"""RC7.2 N3 revision raw anchor and candidate promotion.

Generation-2+ source-target revisions must cross the same evidence boundary as
the initial discovery worker.  This adapter selects the latest governed
revision receipt, hash-anchors the exact revision DSH JSONL bytes, and promotes
only that revision candidate to OUTPUT_PRODUCED.

It deliberately stops before independent re-review, gap closure, CODE_ANALYSIS
fan-out, N3 PASS, N4 release, field_verified or BANK_FINAL.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from .models import TaskStatus
from .rc72_n3_source_target_anchor import (
    N3SourceTargetEvidenceAnchorError,
    N3SourceTargetEvidenceAnchorService,
    install_rc72_n3_source_target_anchor_overlay,
)
from .rc72_n3_source_target_promotion import (
    N3SourceTargetCandidatePromotionService,
    N3SourceTargetPromotionError,
)
from .rc72_n3_source_target_revision import (
    install_rc72_n3_source_target_revision_overlay,
)
from .rc72_n3_source_target_revision_handoff import (
    install_rc72_n3_source_target_revision_handoff_overlay,
)


class N3SourceTargetRevisionPromotionError(RuntimeError):
    pass


def _latest_revision(
    truth,
    *,
    source_commit: str,
    release_batch_id: str,
    application_id: str,
) -> Dict[str, Any]:
    rows = [
        row
        for row in truth.query(
            "rc72_n3_source_target_revision",
            release_batch_id=release_batch_id,
        )
        if row.get("source_commit") == source_commit
        and row.get("application_id") == application_id
        and row.get("status") == "LEASED_FOR_HANDOFF"
    ]
    if not rows:
        raise N3SourceTargetRevisionPromotionError(
            "RC72_N3_SOURCE_REV_PROMOTION_REVISION_REQUIRED"
        )
    highest = max(int(row.get("revision_generation") or 0) for row in rows)
    exact = [
        row for row in rows
        if int(row.get("revision_generation") or 0) == highest
    ]
    if highest < 2 or len(exact) != 1:
        raise N3SourceTargetRevisionPromotionError(
            "RC72_N3_SOURCE_REV_PROMOTION_LATEST_REVISION_NOT_UNIQUE"
        )
    return exact[0]


def _revision_link(truth, revision: Mapping[str, Any]) -> Dict[str, Any]:
    rows = truth.query(
        "rc72_n3_source_target_revision_attempt_link",
        revision_id=str(revision["revision_id"]),
    )
    exact = [
        row for row in rows
        if row.get("status") == "REVISION_DSH_SESSION_OBSERVED"
        and row.get("revision_generation") == revision.get("revision_generation")
        and row.get("revision_workitem_id") == revision.get("revision_workitem_id")
        and row.get("revision_worker_instance_id")
        == revision.get("revision_worker_instance_id")
    ]
    if len(exact) != 1:
        raise N3SourceTargetRevisionPromotionError(
            "RC72_N3_SOURCE_REV_PROMOTION_REVISION_LINK_NOT_UNIQUE:%d"
            % len(exact)
        )
    return exact[0]


class N3SourceTargetRevisionEvidenceAnchorService(
    N3SourceTargetEvidenceAnchorService
):
    """Hash-anchor only the latest governed N3 source revision Attempt."""

    def __init__(self, truth, *, source_commit: str, state_root: str) -> None:
        install_rc72_n3_source_target_revision_handoff_overlay()
        install_rc72_n3_source_target_anchor_overlay()
        super().__init__(
            truth,
            source_commit=source_commit,
            state_root=state_root,
        )
        install_rc72_n3_source_target_revision_handoff_overlay()
        install_rc72_n3_source_target_anchor_overlay()

    def _revision_context(
        self, release_batch_id: str, application_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        revision = _latest_revision(
            self.truth,
            source_commit=self.source_commit,
            release_batch_id=release_batch_id,
            application_id=application_id,
        )
        link = _revision_link(self.truth, revision)
        attempts = self.truth.query(
            "rc72_n3_source_target_attempt",
            attempt_id=str(link["attempt_id"]),
        )
        if len(attempts) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_ATTEMPT_NOT_UNIQUE:%d"
                % len(attempts)
            )
        attempt = attempts[0]
        expected = {
            "mission_id": revision.get("mission_id"),
            "release_id": revision.get("release_id"),
            "release_batch_id": revision.get("release_batch_id"),
            "source_commit": self.source_commit,
            "mission_node_id": revision.get("mission_node_id"),
            "application_id": application_id,
            "assignment_id": revision.get("revision_id"),
            "workitem_id": revision.get("revision_workitem_id"),
            "worker_instance_id": revision.get("revision_worker_instance_id"),
            "dsh_session_id": link.get("dsh_session_id"),
        }
        for key, value in expected.items():
            if attempt.get(key) != value:
                raise N3SourceTargetRevisionPromotionError(
                    "RC72_N3_SOURCE_REV_PROMOTION_ATTEMPT_LINEAGE_MISMATCH:%s"
                    % key
                )
        if (
            link.get("trigger_evaluation_id")
            != revision.get("trigger_evaluation_id")
            or link.get("previous_workitem_id")
            != revision.get("previous_workitem_id")
            or link.get("previous_artifact_id")
            != revision.get("previous_artifact_id")
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_LINK_LINEAGE_MISMATCH"
            )
        return revision, link, attempt

    def _attempt(
        self, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        _revision, _link, attempt = self._revision_context(
            release_batch_id, application_id
        )
        return attempt

    def anchor(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        revision, link, attempt = self._revision_context(
            release_batch_id, application_id
        )
        try:
            row = super().anchor(
                release_batch_id=release_batch_id,
                application_id=application_id,
            )
        except N3SourceTargetEvidenceAnchorError as exc:
            raise N3SourceTargetRevisionPromotionError(str(exc)) from exc
        if (
            row.get("attempt_id") != attempt.get("attempt_id")
            or row.get("assignment_id") != revision.get("revision_id")
            or row.get("workitem_id") != revision.get("revision_workitem_id")
            or row.get("dsh_session_id") != link.get("dsh_session_id")
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_ANCHOR_LINEAGE_MISMATCH"
            )
        out = dict(row)
        out.update({
            "revision_id": str(revision["revision_id"]),
            "revision_generation": int(revision["revision_generation"]),
            "trigger_evaluation_id": str(revision["trigger_evaluation_id"]),
            "previous_artifact_id": str(revision["previous_artifact_id"]),
        })
        return out


class N3SourceTargetRevisionCandidatePromotionService(
    N3SourceTargetCandidatePromotionService
):
    """Promote only the latest hash-bound revision mapping candidate."""

    def __init__(
        self,
        truth,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n3_source_target_revision_overlay()
        install_rc72_n3_source_target_revision_handoff_overlay()
        install_rc72_n3_source_target_anchor_overlay()
        super().__init__(
            truth,
            release_id=release_id,
            mission_id=mission_id,
            source_commit=source_commit,
            state_root=state_root,
        )

    def _latest_revision(
        self, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        return _latest_revision(
            self.truth,
            source_commit=self.source_commit,
            release_batch_id=release_batch_id,
            application_id=application_id,
        )

    def _anchor(
        self, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        revision = self._latest_revision(release_batch_id, application_id)
        link = _revision_link(self.truth, revision)
        rows = self.truth.query(
            "rc72_n3_dsh_evidence_anchor",
            attempt_id=str(link["attempt_id"]),
        )
        exact = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("application_id") == application_id
            and row.get("release_batch_id") == release_batch_id
            and row.get("assignment_id") == revision.get("revision_id")
            and row.get("workitem_id") == revision.get("revision_workitem_id")
            and row.get("worker_instance_id")
            == revision.get("revision_worker_instance_id")
            and row.get("dsh_session_id") == link.get("dsh_session_id")
        ]
        if len(exact) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_EXACT_REVISION_ANCHOR_REQUIRED:%d"
                % len(exact)
            )
        return exact[0]

    def _validate_lineage(
        self,
        *,
        release_batch_id: str,
        application_id: str,
        anchor: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        revision = self._latest_revision(release_batch_id, application_id)
        link = _revision_link(self.truth, revision)
        attempt_rows = self.truth.query(
            "rc72_n3_source_target_attempt",
            attempt_id=str(anchor["attempt_id"]),
        )
        if len(attempt_rows) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_ATTEMPT_NOT_UNIQUE:%d"
                % len(attempt_rows)
            )
        attempt = attempt_rows[0]
        dispatch_rows = self.truth.query(
            "rc72_n3_source_target_dispatch",
            dispatch_id=str(link["root_dispatch_id"]),
        )
        if len(dispatch_rows) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_ROOT_DISPATCH_NOT_UNIQUE:%d"
                % len(dispatch_rows)
            )
        dispatch = dispatch_rows[0]
        task_rows = self.truth.query(
            "rc7_task",
            task_id=str(revision["revision_workitem_id"]),
        )
        if len(task_rows) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_REVISION_TASK_NOT_UNIQUE:%d"
                % len(task_rows)
            )
        task = task_rows[0]

        expected_attempt = {
            "mission_id": self.mission_id,
            "release_id": self.release_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "mission_node_id": revision.get("mission_node_id"),
            "application_id": application_id,
            "assignment_id": revision.get("revision_id"),
            "dispatch_id": link.get("root_dispatch_id"),
            "workitem_id": revision.get("revision_workitem_id"),
            "worker_instance_id": revision.get("revision_worker_instance_id"),
            "dsh_session_id": link.get("dsh_session_id"),
        }
        for key, value in expected_attempt.items():
            if attempt.get(key) != value or anchor.get(key) != value:
                raise N3SourceTargetRevisionPromotionError(
                    "RC72_N3_SOURCE_REV_PROMOTION_LINEAGE_MISMATCH:%s" % key
                )
        if (
            dispatch.get("mission_id") != self.mission_id
            or dispatch.get("release_batch_id") != release_batch_id
            or dispatch.get("application_id") != application_id
            or dispatch.get("source_commit") != self.source_commit
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_ROOT_DISPATCH_LINEAGE_MISMATCH"
            )
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != "SOURCE_TARGET_DISCOVERY"
            or task.get("lease_owner")
            != revision.get("revision_worker_instance_id")
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_REVISION_TASK_LINEAGE_MISMATCH"
            )
        if task.get("state") not in {
            TaskStatus.LEASED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_REVISION_TASK_STATE_INVALID:%s"
                % str(task.get("state") or "UNKNOWN")
            )
        if str(revision["previous_artifact_id"]) not in list(
            task.get("input_artifact_refs") or []
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_PREVIOUS_ARTIFACT_INPUT_REQUIRED"
            )
        trigger_rows = self.truth.query(
            "rc7_evaluation",
            evaluation_id=str(revision["trigger_evaluation_id"]),
        )
        if len(trigger_rows) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_TRIGGER_EVALUATION_NOT_UNIQUE"
            )
        trigger = trigger_rows[0]
        if (
            trigger.get("result") != "REPAIR_REQUIRED"
            or str(revision["previous_artifact_id"])
            not in list(trigger.get("artifact_refs") or [])
            or set(revision.get("gap_refs") or [])
            != set(trigger.get("gap_refs") or [])
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_TRIGGER_EVALUATION_INVALID"
            )
        return attempt, revision, dispatch, task

    def promote(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        revision = self._latest_revision(release_batch_id, application_id)
        try:
            result = super().promote(
                release_batch_id=release_batch_id,
                application_id=application_id,
            )
        except N3SourceTargetPromotionError as exc:
            raise N3SourceTargetRevisionPromotionError(str(exc)) from exc
        if result.get("task_id") != revision.get("revision_workitem_id"):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_OUTPUT_TASK_MISMATCH"
            )
        artifact_rows = self.truth.query(
            "rc7_artifact",
            artifact_id=str(result["artifact_id"]),
        )
        if len(artifact_rows) != 1:
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_ARTIFACT_NOT_UNIQUE"
            )
        artifact = artifact_rows[0]
        if str(revision["previous_artifact_id"]) not in list(
            artifact.get("parent_refs") or []
        ):
            raise N3SourceTargetRevisionPromotionError(
                "RC72_N3_SOURCE_REV_PROMOTION_PREVIOUS_ARTIFACT_PARENT_REQUIRED"
            )
        out = dict(result)
        out.update({
            "revision_id": str(revision["revision_id"]),
            "revision_generation": int(revision["revision_generation"]),
            "trigger_evaluation_id": str(revision["trigger_evaluation_id"]),
            "previous_workitem_id": str(revision["previous_workitem_id"]),
            "previous_artifact_id": str(revision["previous_artifact_id"]),
        })
        return out
