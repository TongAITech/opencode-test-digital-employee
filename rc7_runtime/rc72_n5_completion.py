"""RC7.2 N5 aggregate data delivery + deterministic NodeGate.

N5 closes only when the complete canonical DataRequirement denominator from the
N4-derived inventory has exactly one current verified binding per requirement.
Each binding must still point to a verified canonical DataResource and canonical
verification evidence. Runtime DataLease ownership is deliberately excluded:
leases require a concrete WorkItem/Attempt/Worker and therefore belong to N6+
execution readiness, not N5 data verification.

A pending discovery/finalization or REPAIR_REQUIRED verifier result is not a
partial delivery. N5 remains RUNNING and N6 remains locked until the repair loop
produces verified bindings for the full denominator. Only the aggregate PASS
NodeGate may release N6. No Field/BANK_FINAL claim is made here.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_domain import (
    AutonomousMissionNode,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
)
from .rc72_n5_data_resolution import N5DataResolutionError, N5DataResolutionService
from .rc72_state_machine import RC72StateMachine


_NODE = AutonomousMissionNode.N5_TEST_DATA
_NEXT_NODE = AutonomousMissionNode.N6_EXECUTABLE_READINESS
_PRODUCER = "rc72-runtime-n5-delivery"
_GATE_WORKER = "rc72-runtime-n5-gate"
_GATE_SESSION = "runtime://rc72/n5-gate/v1"
_CRITERIA = (
    "N5_CANONICAL_DATA_REQUIREMENT_SET_COMPLETE",
    "N5_SOURCE_COMMIT_LINEAGE",
    "N5_PARENT_N4_PASS_LINEAGE",
    "N5_ALL_REQUIREMENTS_REUSE_VERIFIED",
    "N5_EXACT_VERIFIED_BINDING",
    "N5_VERIFIED_DATA_RESOURCE",
    "N5_VERIFICATION_EVIDENCE_CANONICAL",
    "N5_PRECONDITION_SCOPE_BOUND",
    "N5_RESERVATION_MODE_CONSISTENT",
    "N5_NO_AMBIGUOUS_BINDINGS",
    "N5_NO_PREMATURE_DATA_LEASE_DEPENDENCY",
)


class N5CompletionError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5CompletionError("RC72_N5_COMPLETION_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _uniq(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class N5DeliveryGateService:
    """Admit the full verified-data denominator and release N6 only by PASS Gate."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        source_commit: str,
    ) -> None:
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.resolution = N5DataResolutionService(
            truth,
            release_id=self.release_id,
            source_commit=self.source_commit,
        )

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _parent_n4(
        self,
        *,
        mission_id: str,
        snapshot: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        node = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N4_TEST_DESIGN.value,
        )
        if node.get("state") != MissionNodeState.PASS.value:
            raise N5CompletionError("RC72_N5_COMPLETION_PARENT_N4_NOT_PASS")
        version = node.get("active_delivery_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise N5CompletionError("RC72_N5_COMPLETION_PARENT_N4_DELIVERY_REQUIRED")
        deliveries = [
            row
            for row in self.truth.query(
                "rc72_node_delivery", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("version") == version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
            and row.get("delivery_id") == snapshot.get("source_n4_delivery_id")
        ]
        if len(deliveries) != 1:
            raise N5CompletionError("RC72_N5_COMPLETION_PARENT_N4_DELIVERY_NOT_UNIQUE")
        gates = [
            row
            for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("delivery_id") == deliveries[0].get("delivery_id")
            and row.get("gate_id") in list(node.get("gate_refs") or [])
            and row.get("gate_id") == snapshot.get("source_n4_gate_id")
            and row.get("decision") == NodeGateDecision.PASS.value
            and list(row.get("failed") or []) == []
        ]
        if len(gates) != 1:
            raise N5CompletionError("RC72_N5_COMPLETION_PARENT_N4_PASS_GATE_NOT_UNIQUE")
        return deliveries[0], gates[0]

    def _context(self, release_batch_id: str):
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        if batch.get("release_id") != self.release_id:
            raise N5CompletionError("RC72_N5_COMPLETION_RELEASE_MISMATCH")
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != self.release_id:
            raise N5CompletionError("RC72_N5_COMPLETION_MISSION_LINEAGE_MISMATCH")
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        next_node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if node.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N5CompletionError("RC72_N5_COMPLETION_NODE_SCOPE_MISMATCH")
        if node.get("state") not in {
            MissionNodeState.RUNNING.value,
            MissionNodeState.REVIEW_PENDING.value,
            MissionNodeState.PASS.value,
            MissionNodeState.NEEDS_REVISION.value,
        }:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_NODE_STATE_INVALID:%s" % node.get("state")
            )
        if (
            node.get("state") != MissionNodeState.PASS.value
            and next_node.get("state") != MissionNodeState.NOT_STARTED.value
        ):
            raise N5CompletionError("RC72_N5_COMPLETION_N6_PREMATURELY_RELEASED")
        snapshots = self.truth.query(
            "rc72_n5_data_inventory_snapshot", release_batch_id=release_batch_id
        )
        if len(snapshots) != 1:
            raise N5CompletionError("RC72_N5_COMPLETION_INVENTORY_SNAPSHOT_REQUIRED")
        snapshot = snapshots[0]
        if (
            snapshot.get("release_id") != self.release_id
            or snapshot.get("mission_id") != mission_id
            or snapshot.get("source_commit") != self.source_commit
            or snapshot.get("mission_node_id") != node.get("mission_node_id")
            or snapshot.get("status") != "MATERIALIZED"
        ):
            raise N5CompletionError("RC72_N5_COMPLETION_INVENTORY_LINEAGE_MISMATCH")
        parent_delivery, parent_gate = self._parent_n4(
            mission_id=mission_id,
            snapshot=snapshot,
        )
        expected_ids = _strings(snapshot.get("data_requirement_ids"))
        if not expected_ids or len(expected_ids) != len(set(expected_ids)):
            raise N5CompletionError("RC72_N5_COMPLETION_DENOMINATOR_INVALID")
        requirements = self.truth.query(
            "rc72_n5_data_requirement", release_batch_id=release_batch_id
        )
        requirement_ids = [str(row.get("data_requirement_id") or "") for row in requirements]
        if set(requirement_ids) != set(expected_ids) or len(requirements) != len(expected_ids):
            raise N5CompletionError("RC72_N5_COMPLETION_DENOMINATOR_MISMATCH")
        if int(snapshot.get("data_requirement_count") or 0) != len(expected_ids):
            raise N5CompletionError("RC72_N5_COMPLETION_DENOMINATOR_COUNT_MISMATCH")
        return (
            batch,
            node,
            next_node,
            snapshot,
            sorted(requirements, key=lambda row: str(row["data_requirement_id"])),
            parent_delivery,
            parent_gate,
        )

    def _canonical_evidence(
        self,
        *,
        mission_id: str,
        data_requirement_id: str,
        evidence_ids: Sequence[str],
    ) -> Tuple[List[str], bool]:
        refs = _uniq(evidence_ids)
        if not refs or len(refs) != len(list(evidence_ids)):
            return refs, False
        ok = True
        for evidence_id in refs:
            rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                ok = False
                continue
            evidence = rows[0]
            if (
                evidence.get("mission_id") != mission_id
                or not str(evidence.get("source_ref") or "").strip()
                or not str(evidence.get("content_ref") or "").strip()
                or data_requirement_id not in list(evidence.get("subject_refs") or [])
            ):
                ok = False
        return refs, ok

    def _record(
        self,
        *,
        requirement: Mapping[str, Any],
        plan: Mapping[str, Any],
        mission_id: str,
    ) -> Dict[str, Any]:
        data_requirement_id = str(requirement["data_requirement_id"])
        source_ok = bool(
            requirement.get("source_commit") == self.source_commit
            and plan.get("source_commit") == self.source_commit
            and requirement.get("release_id") == self.release_id
            and plan.get("release_id") == self.release_id
            and requirement.get("mission_id") == mission_id
            and plan.get("mission_id") == mission_id
            and requirement.get("release_batch_id") == plan.get("release_batch_id")
            and requirement.get("source_case_sha256") == plan.get("source_case_sha256")
        )
        if plan.get("data_requirement_id") != data_requirement_id:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_PLAN_REQUIREMENT_MISMATCH:%s" % data_requirement_id
            )
        if plan.get("status") != "REUSE_VERIFIED":
            finalizations = [
                row
                for row in self.truth.query(
                    "rc72_n5_data_verification_result",
                    data_requirement_id=data_requirement_id,
                )
                if row.get("source_commit") == self.source_commit
            ]
            if any(row.get("decision") == "REPAIR_REQUIRED" for row in finalizations):
                raise N5CompletionError(
                    "RC72_N5_COMPLETION_REPAIR_REQUIRED:%s" % data_requirement_id
                )
            raise N5CompletionError(
                "RC72_N5_COMPLETION_FINALIZATION_INCOMPLETE:%s" % data_requirement_id
            )
        binding_id = _required(plan.get("binding_id"), "binding_id")
        data_ref = _required(plan.get("data_ref"), "data_ref")
        verified_bindings = [
            row
            for row in self.truth.query(
                "rc72_n5_data_binding", data_requirement_id=data_requirement_id
            )
            if row.get("status") == "VERIFIED"
        ]
        if len(verified_bindings) != 1:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_AMBIGUOUS_VERIFIED_BINDINGS:%s:%d"
                % (data_requirement_id, len(verified_bindings))
            )
        binding = verified_bindings[0]
        exact_binding = bool(
            binding.get("binding_id") == binding_id
            and binding.get("data_ref") == data_ref
            and binding.get("release_id") == self.release_id
            and binding.get("mission_id") == mission_id
            and binding.get("release_batch_id") == requirement.get("release_batch_id")
            and binding.get("source_commit") == self.source_commit
            and binding.get("source_case_sha256") == requirement.get("source_case_sha256")
            and binding.get("status") == "VERIFIED"
            and not binding.get('verification_blocked_by_anchor')
        )
        resources = self.truth.query("rc72_data_resource", data_ref=data_ref)
        if len(resources) != 1:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_DATA_RESOURCE_NOT_UNIQUE:%s:%d"
                % (data_ref, len(resources))
            )
        resource = resources[0]
        resource_verified = bool(
            resource.get("release_id") == self.release_id
            and resource.get("verified") is True
            and resource.get("metadata_ref") == binding.get("resource_metadata_ref")
        )
        expected_mode = (
            "EXCLUSIVE_WRITE" if resource.get("mutable") is True else "SHARED_READ"
        )
        reservation_consistent = binding.get("reservation_mode") == expected_mode
        evidence_ids, evidence_canonical = self._canonical_evidence(
            mission_id=mission_id,
            data_requirement_id=data_requirement_id,
            evidence_ids=list(binding.get("verification_evidence_refs") or []),
        )
        preconditions = _strings(binding.get("precondition_refs"))
        precondition_bound = bool(
            preconditions and len(preconditions) == len(set(preconditions))
        )
        finalizations = [
            row
            for row in self.truth.query(
                "rc72_n5_data_verification_result",
                data_requirement_id=data_requirement_id,
            )
            if row.get("source_commit") == self.source_commit
            and row.get("decision") == "VERIFIED_CANDIDATE"
            and row.get("binding_id") == binding_id
        ]
        workitem_ids = _uniq(
            str(row.get("workitem_id") or "") for row in finalizations
        )
        return {
            "data_requirement_id": data_requirement_id,
            "plan_id": str(plan["plan_id"]),
            "binding_id": binding_id,
            "binding_revision": int(binding.get("artifact_version", 1)),
            "verification_evidence_refs": list(binding.get("verification_evidence_refs") or []),
            "data_ref": data_ref,
            "source_commit_ok": source_ok,
            "plan_reuse_verified": True,
            "exact_binding": exact_binding,
            "resource_verified": resource_verified,
            "evidence_ids": evidence_ids,
            "evidence_canonical": evidence_canonical,
            "precondition_bound": precondition_bound,
            "reservation_consistent": reservation_consistent,
            "workitem_ids": workitem_ids,
        }

    def _records(self, release_batch_id: str):
        (
            batch,
            node,
            next_node,
            snapshot,
            requirements,
            parent_delivery,
            parent_gate,
        ) = self._context(release_batch_id)
        mission_id = str(batch["mission_id"])
        plans = self.truth.query(
            "rc72_n5_data_resolution_plan", release_batch_id=release_batch_id
        )
        by_requirement: Dict[str, List[Dict[str, Any]]] = {}
        for plan in plans:
            by_requirement.setdefault(str(plan.get("data_requirement_id") or ""), []).append(plan)
        records: List[Dict[str, Any]] = []
        for requirement in requirements:
            data_requirement_id = str(requirement["data_requirement_id"])
            current = by_requirement.get(data_requirement_id, [])
            if len(current) != 1:
                raise N5CompletionError(
                    "RC72_N5_COMPLETION_PLAN_NOT_UNIQUE:%s:%d"
                    % (data_requirement_id, len(current))
                )
            records.append(
                self._record(
                    requirement=requirement,
                    plan=current[0],
                    mission_id=mission_id,
                )
            )
        if set(by_requirement.keys()) != {str(row["data_requirement_id"]) for row in requirements}:
            raise N5CompletionError("RC72_N5_COMPLETION_PLAN_DENOMINATOR_MISMATCH")
        return (
            batch,
            node,
            next_node,
            snapshot,
            records,
            parent_delivery,
            parent_gate,
        )

    @staticmethod
    def _record_signature(records: Sequence[Mapping[str, Any]]) -> str:
        return "|".join(
            "%s:%s:%s:%s"
            % (
                row["data_requirement_id"],
                row["plan_id"],
                row["binding_id"],
                row["data_ref"],
            ) + (":verification-revision=%s:%s" % (row['binding_revision'],
                     ",".join(row['verification_evidence_refs'])) if row.get('binding_revision', 1) > 1 else "")
            for row in records
        )

    def _refresh_resolution_if_running(self, release_batch_id: str) -> None:
        node = self._one(
            "rc72_mission_node",
            scope_ref="release-batch://%s" % release_batch_id,
            node_type=_NODE.value,
        )
        if node.get("state") != MissionNodeState.RUNNING.value:
            return
        try:
            self.resolution.resolve_all(release_batch_id=release_batch_id)
        except N5DataResolutionError as exc:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_RESOLUTION_INVALID:%s" % exc
            ) from exc

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        self._refresh_resolution_if_running(release_batch_id)
        (
            batch,
            node,
            _next_node,
            snapshot,
            records,
            parent_delivery,
            parent_gate,
        ) = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        node_id = str(node["mission_node_id"])
        signature = self._record_signature(records)
        delivery_id = _stable_id(
            "N5DEL", mission_id, release_batch_id, self.source_commit, signature
        )
        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N5CompletionError("RC72_N5_COMPLETION_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "node_state": self._one(
                    "rc72_mission_node", mission_node_id=node_id
                )["state"],
                "data_requirement_count": len(records),
            }
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_DELIVERY_REQUIRES_RUNNING_NODE:%s"
                % str(node.get("state") or "UNKNOWN")
            )
        previous = self.truth.query("rc72_node_delivery", mission_node_id=node_id)
        version = max([int(row.get("version") or 0) for row in previous] + [0]) + 1
        evidence_ids = _uniq(
            evidence_id for row in records for evidence_id in row["evidence_ids"]
        )
        workitem_ids = _uniq(
            workitem_id for row in records for workitem_id in row["workitem_ids"]
        )
        delivery = NodeDelivery(
            delivery_id=delivery_id,
            mission_id=mission_id,
            mission_node_id=node_id,
            node_type=_NODE,
            version=version,
            producer_ref=_PRODUCER,
            input_refs=_uniq(
                ["n5-inventory://%s" % str(snapshot["snapshot_id"])]
                + ["n4-delivery://%s" % str(parent_delivery["delivery_id"])]
                + ["n4-gate://%s" % str(parent_gate["gate_id"])]
                + ["n5-plan://%s" % row["plan_id"] for row in records]
                + ["data-ref://%s" % row["data_ref"] for row in records]
            ),
            artifact_refs=[row["binding_id"] for row in records],
            evidence_refs=evidence_ids,
            known_gaps=[],
            created_by_workitems=workitem_ids,
            sufficiency_score=1.0,
        )
        RC72StateMachine(self.truth, release_id=self.release_id).submit_delivery(delivery)
        return {
            "status": "DELIVERY_ADMITTED",
            "delivery_id": delivery_id,
            "delivery_version": version,
            "node_state": MissionNodeState.REVIEW_PENDING.value,
            "data_requirement_count": len(records),
            "verified_binding_count": len(records),
        }

    def _criterion_results(
        self,
        *,
        records: Sequence[Mapping[str, Any]],
        snapshot: Mapping[str, Any],
        parent_delivery: Mapping[str, Any],
        parent_gate: Mapping[str, Any],
    ) -> Dict[str, bool]:
        expected_ids = set(_strings(snapshot.get("data_requirement_ids")))
        actual_ids = {str(row["data_requirement_id"]) for row in records}
        return {
            "N5_CANONICAL_DATA_REQUIREMENT_SET_COMPLETE": bool(
                records and actual_ids == expected_ids and len(records) == len(expected_ids)
            ),
            "N5_SOURCE_COMMIT_LINEAGE": all(
                bool(row["source_commit_ok"]) for row in records
            ),
            "N5_PARENT_N4_PASS_LINEAGE": bool(
                parent_delivery.get("delivery_id") == snapshot.get("source_n4_delivery_id")
                and parent_gate.get("gate_id") == snapshot.get("source_n4_gate_id")
                and parent_gate.get("decision") == NodeGateDecision.PASS.value
            ),
            "N5_ALL_REQUIREMENTS_REUSE_VERIFIED": all(
                bool(row["plan_reuse_verified"]) for row in records
            ),
            "N5_EXACT_VERIFIED_BINDING": all(
                bool(row["exact_binding"]) for row in records
            ),
            "N5_VERIFIED_DATA_RESOURCE": all(
                bool(row["resource_verified"]) for row in records
            ),
            "N5_VERIFICATION_EVIDENCE_CANONICAL": all(
                bool(row["evidence_canonical"]) for row in records
            ),
            "N5_PRECONDITION_SCOPE_BOUND": all(
                bool(row["precondition_bound"]) for row in records
            ),
            "N5_RESERVATION_MODE_CONSISTENT": all(
                bool(row["reservation_consistent"]) for row in records
            ),
            "N5_NO_AMBIGUOUS_BINDINGS": all(
                bool(row["binding_id"]) for row in records
            ),
            # N5 proves future reservation mode, but cannot own a lease without a
            # concrete N6+/execution Attempt. Therefore PASS is independent of
            # rc72_data_lease presence and never creates one here.
            "N5_NO_PREMATURE_DATA_LEASE_DEPENDENCY": True,
        }

    def apply_gate(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        (
            batch,
            node,
            next_node,
            snapshot,
            records,
            parent_delivery,
            parent_gate,
        ) = self._records(release_batch_id)
        mission_id = str(batch["mission_id"])
        node_id = str(node["mission_node_id"])
        active_version = node.get("active_delivery_version")
        if isinstance(active_version, bool) or not isinstance(active_version, int):
            raise N5CompletionError("RC72_N5_COMPLETION_ACTIVE_DELIVERY_REQUIRED")
        deliveries = [
            row
            for row in self.truth.query("rc72_node_delivery", mission_node_id=node_id)
            if row.get("version") == active_version
            and row.get("delivery_id") in list(node.get("delivery_refs") or [])
        ]
        if len(deliveries) != 1:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_ACTIVE_DELIVERY_NOT_UNIQUE:%d" % len(deliveries)
            )
        delivery = deliveries[0]
        if list(delivery.get("artifact_refs") or []) != [row["binding_id"] for row in records]:
            raise N5CompletionError("RC72_N5_COMPLETION_DELIVERY_CURRENT_TRUTH_MISMATCH")
        expected_evidence = _uniq(evidence_id for row in records for evidence_id in row['evidence_ids'])
        if list(delivery.get('evidence_refs') or []) != expected_evidence:
            raise N5CompletionError('RC72_N5_COMPLETION_DELIVERY_VERIFICATION_REVISION_STALE')
        criterion = self._criterion_results(
            records=records,
            snapshot=snapshot,
            parent_delivery=parent_delivery,
            parent_gate=parent_gate,
        )
        passed = [name for name in _CRITERIA if criterion[name]]
        failed = [name for name in _CRITERIA if not criterion[name]]
        decision = (
            NodeGateDecision.PASS if not failed else NodeGateDecision.NEEDS_REVISION
        )
        gate_id = _stable_id(
            "N5GATE",
            str(delivery["delivery_id"]),
            self.source_commit,
            decision.value,
            ",".join(failed),
        )
        existing = self.truth.query("rc72_node_gate", gate_id=gate_id)
        if existing:
            if len(existing) != 1:
                raise N5CompletionError("RC72_N5_COMPLETION_GATE_NOT_UNIQUE")
            current_node = self._one("rc72_mission_node", mission_node_id=node_id)
            current_next = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if decision == NodeGateDecision.PASS:
                if current_node.get("state") != MissionNodeState.PASS.value:
                    raise N5CompletionError(
                        "RC72_N5_COMPLETION_EXISTING_PASS_GATE_NODE_NOT_PASS"
                    )
                if current_next.get("state") == MissionNodeState.NOT_STARTED.value:
                    RC72StateMachine(self.truth, release_id=self.release_id).forward(
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
                "n5_state": current_node["state"],
                "n6_state": current_next["state"],
            }
        if node.get("state") != MissionNodeState.REVIEW_PENDING.value:
            raise N5CompletionError(
                "RC72_N5_COMPLETION_GATE_REQUIRES_REVIEW_PENDING:%s"
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
                "all canonical N5 DataRequirements have exact verified evidence-backed bindings; reservation is deferred to a concrete consumer Attempt"
                if decision == NodeGateDecision.PASS
                else "N5 deterministic criteria failed: %s" % ",".join(failed)
            ),
        )
        runtime = RC72StateMachine(self.truth, release_id=self.release_id)
        runtime.apply_gate(gate)
        n6_state = next_node["state"]
        if decision == NodeGateDecision.PASS:
            if next_node.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N5CompletionError(
                    "RC72_N5_COMPLETION_N6_PREMATURE_STATE:%s" % next_node.get("state")
                )
            runtime.forward(_NODE, _NEXT_NODE, source_gate_id=gate_id)
            n6_state = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )["state"]
        else:
            current_next = self._one(
                "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
            )
            if current_next.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N5CompletionError("RC72_N5_COMPLETION_REVISION_CANNOT_RELEASE_N6")
            n6_state = current_next["state"]
        return {
            "status": "GATE_APPLIED",
            "gate_id": gate_id,
            "decision": decision.value,
            "passed": passed,
            "failed": failed,
            "n5_state": (
                MissionNodeState.PASS.value
                if decision == NodeGateDecision.PASS
                else MissionNodeState.NEEDS_REVISION.value
            ),
            "n6_state": n6_state,
        }

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        delivery = self.admit_delivery(release_batch_id=release_batch_id)
        gate = self.apply_gate(release_batch_id=release_batch_id)
        return {"delivery": delivery, "gate": gate}


__all__ = ["N5CompletionError", "N5DeliveryGateService"]
