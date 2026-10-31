"""RC7.2 N4 parent-truth admission boundary.

N4 Test Design must not start from a designer-authored denominator.  It may
only derive its mandatory TestObligation inventory from the active PASS N2 and
N3 NodeDelivery/NodeGate pair for the same ReleaseBatch.

The inherited RC7 parent inventory predates RC7.2 and recognizes
REQUIREMENT_MODEL / CODE_IMPACT_MODEL.  RC7.2 deliberately persists reviewed
candidates as REQUIREMENT_ANALYSIS_OUTPUT / CODE_ANALYSIS_CANDIDATE.  Without
an explicit compatibility contract the inherited inventory silently skips both
new artifact types and can return an empty denominator.

This module closes that boundary and provides a stable parent snapshot for the
next N4 dispatch slice.  It does not generate Cases, does not PASS N4 and makes
no field/BANK_FINAL claim.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadError, CandidatePayloadReader
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .test_obligation_inventory import (
    MandatoryObligationSource,
    ParentDerivedTestObligationInventory,
    TestObligationInventoryError,
)


_REQUIREMENT_ARTIFACT_TYPES = {
    "REQUIREMENT_MODEL",
    "REQUIREMENT_ANALYSIS_OUTPUT",
}
_CODE_ARTIFACT_TYPES = {
    "CODE_IMPACT_MODEL",
    "CODE_ANALYSIS_CANDIDATE",
}
_RC72_REQUIREMENT_TYPE = "REQUIREMENT_ANALYSIS_OUTPUT"
_RC72_CODE_TYPE = "CODE_ANALYSIS_CANDIDATE"
_INSTALLED = False


class N4ParentTruthError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N4ParentTruthError("RC72_N4_PARENT_%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _derive_rc72_parent_sources(
    self: ParentDerivedTestObligationInventory,
    truth: TruthRuntime,
    *,
    mission_id: str,
    parent_artifact_refs: Sequence[str],
) -> Tuple[MandatoryObligationSource, ...]:
    sources: List[MandatoryObligationSource] = []
    seen = set()
    for artifact_id in parent_artifact_refs:
        rows = truth.query("rc7_artifact", artifact_id=artifact_id)
        if not rows:
            continue
        if len(rows) != 1:
            raise TestObligationInventoryError(
                "TEST_DESIGN_PARENT_ARTIFACT_NOT_UNIQUE:%s" % artifact_id
            )
        row = rows[0]
        if row.get("mission_id") != mission_id:
            raise TestObligationInventoryError(
                "TEST_DESIGN_PARENT_MISSION_MISMATCH:%s" % artifact_id
            )
        artifact_type = str(row.get("artifact_type_name") or "")
        if artifact_type not in _REQUIREMENT_ARTIFACT_TYPES | _CODE_ARTIFACT_TYPES:
            continue
        if row.get("state") != "VALID":
            raise TestObligationInventoryError(
                "TEST_DESIGN_PARENT_ARTIFACT_NOT_VALID:%s:%s"
                % (artifact_id, str(row.get("state") or "UNKNOWN"))
            )
        try:
            candidate = self.reader.load(
                truth,
                artifact_id,
                expected_mission_id=mission_id,
            )
        except CandidatePayloadError as exc:
            raise TestObligationInventoryError(
                "TEST_DESIGN_PARENT_CANDIDATE_INVALID:%s:%s" % (artifact_id, exc)
            ) from exc
        payload = candidate.semantic_payload
        if artifact_type in _REQUIREMENT_ARTIFACT_TYPES:
            pairs = self._requirement_sources(payload, artifact_id)
        else:
            pairs = self._code_sources(payload, artifact_id)
        for item in pairs:
            identity = (item.kind, item.source_id, item.parent_artifact_id)
            if identity in seen:
                continue
            seen.add(identity)
            sources.append(item)
    return tuple(sources)


def install_rc72_n4_parent_inventory_contract() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    ParentDerivedTestObligationInventory.derive = _derive_rc72_parent_sources
    _INSTALLED = True


class N4ParentTruthService:
    """Resolve exact PASS N2/N3 delivery truth into an N4 parent snapshot."""

    def __init__(self, truth: TruthRuntime) -> None:
        install_rc72_n4_parent_inventory_contract()
        self.truth = truth
        self.reader = CandidatePayloadReader()
        self.inventory = ParentDerivedTestObligationInventory()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _pass_delivery(
        self,
        *,
        mission_id: str,
        node_type: AutonomousMissionNode,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=node_type.value
        )
        if node.get("state") != MissionNodeState.PASS.value:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_NODE_NOT_PASS:%s:%s"
                % (node_type.value, str(node.get("state") or "UNKNOWN"))
            )
        version = node.get("active_delivery_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ACTIVE_DELIVERY_REQUIRED:%s" % node_type.value
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
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ACTIVE_DELIVERY_NOT_UNIQUE:%s:%d"
                % (node_type.value, len(deliveries))
            )
        delivery = deliveries[0]
        gates = [
            row
            for row in self.truth.query(
                "rc72_node_gate", mission_node_id=str(node["mission_node_id"])
            )
            if row.get("delivery_id") == delivery.get("delivery_id")
            and row.get("gate_id") in list(node.get("gate_refs") or [])
            and row.get("decision") == "PASS"
        ]
        if len(gates) != 1:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_PASS_GATE_NOT_UNIQUE:%s:%d"
                % (node_type.value, len(gates))
            )
        gate = gates[0]
        if list(gate.get("failed") or []):
            raise N4ParentTruthError(
                "RC72_N4_PARENT_PASS_GATE_HAS_FAILED_CRITERIA:%s" % node_type.value
            )
        if not list(delivery.get("artifact_refs") or []):
            raise N4ParentTruthError(
                "RC72_N4_PARENT_DELIVERY_ARTIFACTS_REQUIRED:%s" % node_type.value
            )
        return node, delivery, gate

    def _artifact(
        self,
        *,
        mission_id: str,
        artifact_id: str,
        expected_type: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        row = self._one("rc7_artifact", artifact_id=artifact_id)
        if row.get("mission_id") != mission_id:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ARTIFACT_MISSION_MISMATCH:%s" % artifact_id
            )
        if row.get("artifact_type_name") != expected_type:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ARTIFACT_TYPE_MISMATCH:%s:%s"
                % (artifact_id, str(row.get("artifact_type_name") or "UNKNOWN"))
            )
        if row.get("state") != "VALID":
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ARTIFACT_NOT_VALID:%s:%s"
                % (artifact_id, str(row.get("state") or "UNKNOWN"))
            )
        if not str(row.get("content_hash") or "").startswith("sha256:"):
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ARTIFACT_HASH_REQUIRED:%s" % artifact_id
            )
        try:
            candidate = self.reader.load(
                self.truth,
                artifact_id,
                expected_mission_id=mission_id,
            )
        except CandidatePayloadError as exc:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_ARTIFACT_PAYLOAD_INVALID:%s:%s"
                % (artifact_id, exc)
            ) from exc
        return row, dict(candidate.semantic_payload)

    def resolve(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        n4 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N4_TEST_DESIGN.value,
        )
        if n4.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N4ParentTruthError("RC72_N4_PARENT_SCOPE_MISMATCH")
        if n4.get("state") not in {
            MissionNodeState.READY.value,
            MissionNodeState.RUNNING.value,
        }:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_N4_NOT_ADMITTED:%s"
                % str(n4.get("state") or "UNKNOWN")
            )

        _n2_node, n2_delivery, n2_gate = self._pass_delivery(
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N2_REQUIREMENT,
        )
        _n3_node, n3_delivery, n3_gate = self._pass_delivery(
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        )

        n2_refs = _strings(n2_delivery.get("artifact_refs"))
        n3_refs = _strings(n3_delivery.get("artifact_refs"))
        if len(n2_refs) != len(set(n2_refs)) or len(n3_refs) != len(set(n3_refs)):
            raise N4ParentTruthError("RC72_N4_PARENT_ARTIFACT_REFS_DUPLICATE")

        requirement_sst_map: Dict[str, List[str]] = {}
        artifact_hashes: Dict[str, str] = {}
        for artifact_id in n2_refs:
            row, payload = self._artifact(
                mission_id=mission_id,
                artifact_id=artifact_id,
                expected_type=_RC72_REQUIREMENT_TYPE,
            )
            requirement_id = _required(payload.get("requirement_id"), "requirement_id")
            sst_ids = _strings(payload.get("sst_ids"))
            if not sst_ids:
                raise N4ParentTruthError(
                    "RC72_N4_PARENT_SST_LINEAGE_REQUIRED:%s" % requirement_id
                )
            if requirement_id in requirement_sst_map:
                raise N4ParentTruthError(
                    "RC72_N4_PARENT_REQUIREMENT_DUPLICATE:%s" % requirement_id
                )
            requirement_sst_map[requirement_id] = sst_ids
            artifact_hashes[artifact_id] = str(row["content_hash"])

        canonical_requirements = _strings(batch.get("requirement_ids"))
        if not canonical_requirements or set(requirement_sst_map) != set(canonical_requirements):
            raise N4ParentTruthError(
                "RC72_N4_PARENT_REQUIREMENT_SET_MISMATCH"
            )

        code_requirement_map: Dict[str, List[str]] = {}
        for artifact_id in n3_refs:
            row, payload = self._artifact(
                mission_id=mission_id,
                artifact_id=artifact_id,
                expected_type=_RC72_CODE_TYPE,
            )
            requirement_ids = _strings(payload.get("requirement_ids"))
            if not requirement_ids:
                raise N4ParentTruthError(
                    "RC72_N4_PARENT_CODE_REQUIREMENT_LINEAGE_REQUIRED:%s" % artifact_id
                )
            if not set(requirement_ids).issubset(set(canonical_requirements)):
                raise N4ParentTruthError(
                    "RC72_N4_PARENT_CODE_REQUIREMENT_OUT_OF_SCOPE:%s" % artifact_id
                )
            code_requirement_map[artifact_id] = requirement_ids
            artifact_hashes[artifact_id] = str(row["content_hash"])

        mapped_requirements = {
            requirement_id
            for values in code_requirement_map.values()
            for requirement_id in values
        }
        if mapped_requirements != set(canonical_requirements):
            raise N4ParentTruthError(
                "RC72_N4_PARENT_CODE_REQUIREMENT_SET_INCOMPLETE"
            )

        parent_refs = n2_refs + n3_refs
        try:
            sources = self.inventory.derive(
                self.truth,
                mission_id=mission_id,
                parent_artifact_refs=parent_refs,
            )
        except TestObligationInventoryError as exc:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_OBLIGATION_INVENTORY_INVALID:%s" % exc
            ) from exc
        requirement_sources = [
            item for item in sources if item.parent_artifact_id in set(n2_refs)
        ]
        code_sources = [
            item for item in sources if item.parent_artifact_id in set(n3_refs)
        ]
        if not requirement_sources:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_REQUIREMENT_OBLIGATION_DENOMINATOR_EMPTY"
            )
        if not code_sources:
            raise N4ParentTruthError(
                "RC72_N4_PARENT_CODE_OBLIGATION_DENOMINATOR_EMPTY"
            )

        signature_parts = [
            str(n2_gate["gate_id"]),
            str(n3_gate["gate_id"]),
        ] + [
            "%s=%s" % (artifact_id, artifact_hashes[artifact_id])
            for artifact_id in sorted(artifact_hashes)
        ]
        snapshot_id = _stable_id(
            "N4PARENT", mission_id, release_batch_id, *signature_parts
        )
        source_rows = [
            {
                "kind": item.kind,
                "source_id": item.source_id,
                "parent_artifact_id": item.parent_artifact_id,
            }
            for item in sources
        ]
        return {
            "snapshot_id": snapshot_id,
            "snapshot_version": 1,
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "n4_node_id": str(n4["mission_node_id"]),
            "n4_state": str(n4["state"]),
            "n2_delivery_id": str(n2_delivery["delivery_id"]),
            "n2_gate_id": str(n2_gate["gate_id"]),
            "n3_delivery_id": str(n3_delivery["delivery_id"]),
            "n3_gate_id": str(n3_gate["gate_id"]),
            "parent_artifact_refs": parent_refs,
            "artifact_hashes": artifact_hashes,
            "requirement_sst_map": requirement_sst_map,
            "code_requirement_map": code_requirement_map,
            "obligation_sources": source_rows,
            "obligation_source_total": len(source_rows),
            "requirement_source_total": len(requirement_sources),
            "code_source_total": len(code_sources),
            "lineage_ready": True,
            "cases_generated": False,
            "n4_pass": False,
        }


__all__ = [
    "N4ParentTruthError",
    "N4ParentTruthService",
    "install_rc72_n4_parent_inventory_contract",
]
