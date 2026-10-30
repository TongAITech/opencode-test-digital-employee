"""Revision-aware RC7.2 N2 aggregate completion.

The base N2 aggregate service is correct for generation 1. After a failed Gate,
an affected Requirement's original WorkItem is deliberately STALE and a fresh
revision WorkItem becomes the active source of truth. This service keeps the
canonical ReleaseBatch Requirement order from the original dispatch set while
selecting the latest governed revision receipt per Requirement when present.

Unrevised Requirements retain their accepted generation-1 candidate. Revised
Requirements must independently reach PASS/REPAIR_REQUIRED through the normal
Requirement reviewer before they can enter Delivery v2+. Only the inherited
deterministic Gate may release N3.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping

from .models import TaskStatus
from .rc72_domain import AutonomousMissionNode, MissionNodeState, NodeDelivery
from .rc72_n2_completion import N2CompletionError, N2DeliveryGateService
from .rc72_state_machine import RC72StateMachine


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _uniq(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


class N2RevisionAwareDeliveryGateService(N2DeliveryGateService):
    """Aggregate the latest independently reviewed candidate for every Requirement."""

    def _latest_revision(self, dispatch: Mapping[str, Any]) -> Dict[str, Any]:
        requirement_id = str(dispatch["requirement_id"])
        release_batch_id = str(dispatch["release_batch_id"])
        rows = [
            row for row in self.truth.query(
                "rc72_n2_revision_receipt", release_batch_id=release_batch_id
            )
            if row.get("source_commit") == self.source_commit
            and row.get("requirement_id") == requirement_id
        ]
        if not rows:
            return {}
        highest = max(int(row.get("revision_generation") or 0) for row in rows)
        latest = [
            row for row in rows
            if int(row.get("revision_generation") or 0) == highest
        ]
        if len(latest) != 1 or highest < 2:
            raise N2CompletionError(
                "RC72_N2_LATEST_REVISION_NOT_UNIQUE:%s" % requirement_id
            )
        row = latest[0]
        node = self._one(
            "rc72_mission_node", mission_node_id=str(row["mission_node_id"])
        )
        if (
            row.get("failed_gate_id") not in list(node.get("gate_refs") or [])
            or row.get("failed_delivery_id") not in list(node.get("delivery_refs") or [])
        ):
            raise N2CompletionError(
                "RC72_N2_LATEST_REVISION_FAILED_CYCLE_LINEAGE_INVALID:%s"
                % requirement_id
            )
        return row

    def _requirement_record(
        self,
        *,
        mission_id: str,
        dispatch: Mapping[str, Any],
    ) -> Dict[str, Any]:
        revision = self._latest_revision(dispatch)
        if not revision:
            record = super()._requirement_record(
                mission_id=mission_id, dispatch=dispatch
            )
            record.update({"revision_id": "", "revision_generation": 1})
            return record

        proxy = dict(dispatch)
        proxy["workitem_id"] = str(revision["revision_workitem_id"])
        proxy["source_commit"] = str(revision["source_commit"])
        record = super()._requirement_record(
            mission_id=mission_id, dispatch=proxy
        )
        record.update({
            "dispatch_id": str(dispatch["dispatch_id"]),
            "revision_id": str(revision["revision_id"]),
            "revision_generation": int(revision["revision_generation"]),
        })
        return record

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = str(release_batch_id or "").strip()
        if not release_batch_id:
            raise N2CompletionError("RC72_N2_COMPLETION_RELEASE_BATCH_ID_REQUIRED")
        batch, node, _next_node, records = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        signature = self._record_signature(records)
        delivery_id = _stable_id(
            "N2DEL", mission_id, release_batch_id, self.source_commit, signature
        )

        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N2CompletionError("RC72_N2_COMPLETION_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "delivery_version": int(existing[0]["version"]),
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=node_id
                )["state"],
                "known_gap_ids": list(existing[0].get("known_gaps") or []),
            }

        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N2CompletionError(
                "RC72_N2_COMPLETION_DELIVERY_REQUIRES_RUNNING_NODE:%s"
                % str(node.get("state") or "UNKNOWN")
            )
        previous = self.truth.query("rc72_node_delivery", mission_node_id=node_id)
        version = (
            max(int(row.get("version") or 0) for row in previous) + 1
            if previous else 1
        )
        workitems = [row["task_id"] for row in records]
        artifacts = [row["artifact_id"] for row in records]
        evidence = _uniq(
            evidence_id for row in records for evidence_id in row["evidence_ids"]
        )
        known_gaps = _uniq(
            gap_id for row in records for gap_id in row["active_gap_ids"]
        )
        input_refs = _uniq(
            [
                "n1-delivery://%s" % records[0]["source_n1_delivery_id"],
                "n1-gate://%s" % records[0]["source_n1_gate_id"],
            ]
            + ["n2-dispatch://%s" % row["dispatch_id"] for row in records]
            + [
                "n2-revision://%s" % row["revision_id"]
                for row in records if row.get("revision_id")
            ]
            + ["evaluation://%s" % row["evaluation_id"] for row in records]
        )
        passed_count = sum(
            1 for row in records if row["task_state"] == TaskStatus.PASS.value
        )
        delivery = NodeDelivery(
            delivery_id=delivery_id,
            mission_id=mission_id,
            mission_node_id=node_id,
            node_type=AutonomousMissionNode.N2_REQUIREMENT,
            version=version,
            producer_ref="rc72-runtime-n2-revision-aware-aggregator",
            input_refs=input_refs,
            artifact_refs=artifacts,
            evidence_refs=evidence,
            known_gaps=known_gaps,
            created_by_workitems=workitems,
            sufficiency_score=float(passed_count) / float(len(records)),
        )
        RC72StateMachine(self.truth, release_id=release_id).submit_delivery(delivery)
        return {
            "status": "DELIVERY_ADMITTED",
            "delivery_id": delivery_id,
            "delivery_version": version,
            "node_state": MissionNodeState.REVIEW_PENDING.value,
            "requirement_count": len(records),
            "passed_requirement_count": passed_count,
            "known_gap_ids": known_gaps,
            "revision_generations": {
                row["requirement_id"]: int(row.get("revision_generation") or 1)
                for row in records
            },
        }
