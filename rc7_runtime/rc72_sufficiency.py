"""Deterministic, evidence-backed N2-N6 sufficiency/readiness gates for RC7.2.

Reviewer identity is auditable, but reviewer prose cannot override deterministic
contract failures. Snapshots and decisions are persisted in the same R1 used by
RC7/RC7.2; this module creates no shadow truth store.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .models import ContractError, Gap, GapSeverity
from .rc72_domain import AutonomousMissionNode, NodeGate, NodeGateDecision
from .rc72_state_machine import RC72StateMachine
from .truth_overlay import append_entity, install_rc7_truth_overlay


@dataclass(frozen=True)
class SufficiencySnapshot:
    snapshot_id: str
    mission_id: str
    mission_node_id: str
    node_type: AutonomousMissionNode
    delivery_id: str
    source_artifact_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "mission_id", "mission_node_id", "delivery_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractError("%s_REQUIRED" % name.upper())
        if not isinstance(self.node_type, AutonomousMissionNode):
            object.__setattr__(self, "node_type", AutonomousMissionNode(str(self.node_type)))
        for name in ("source_artifact_refs", "evidence_refs"):
            values = getattr(self, name)
            if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
                raise ContractError("%s_INVALID" % name.upper())
        if not isinstance(self.facts, dict):
            raise ContractError("SUFFICIENCY_FACTS_MUST_BE_OBJECT")


@dataclass(frozen=True)
class SufficiencyGateResult:
    snapshot_id: str
    gate_id: str
    decision: str
    passed_codes: List[str]
    failed_codes: List[str]
    gap_ids: List[str]
    reviewer_worker_id: str
    reviewer_session_id: str


_SNAPSHOT_EVENT = "RC72_SUFFICIENCY_SNAPSHOT_UPSERTED"
_SNAPSHOT_ARTIFACT = "rc72_sufficiency_snapshot"
_SNAPSHOT_BUCKET = "rc72_sufficiency_snapshots"


def _snapshot_validator(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in ("snapshot_id", "mission_id", "mission_node_id", "node_type", "delivery_id", "release_id"):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] not in {node.value for node in AutonomousMissionNode}:
        raise _contracts.DomainValidationError("SUFFICIENCY_NODE_TYPE_INVALID")
    for name in ("source_artifact_refs", "evidence_refs"):
        _contracts._require_string_list(out, name)
    if not isinstance(out.get("facts"), dict):
        raise _contracts.DomainValidationError("SUFFICIENCY_FACTS_MUST_BE_OBJECT")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("SUFFICIENCY_CREATED_AT_INVALID")
    out["artifact_type"] = _SNAPSHOT_ARTIFACT
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def install_rc72_sufficiency_truth_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_SNAPSHOT_ARTIFACT] = _snapshot_validator
    _truth.EVENT_TYPES[_SNAPSHOT_EVENT] = (_SNAPSHOT_ARTIFACT, "snapshot_id")
    _truth.BUCKETS[_SNAPSHOT_ARTIFACT] = _SNAPSHOT_BUCKET
    _truth.IDENTITY_FIELDS[_SNAPSHOT_ARTIFACT] = "snapshot_id"


def _serialize(snapshot: SufficiencySnapshot, release_id: str) -> Dict[str, Any]:
    payload = asdict(snapshot)
    payload["node_type"] = snapshot.node_type.value
    payload["release_id"] = release_id
    payload["artifact_version"] = 1
    return payload


def _nonempty_list(facts: Mapping[str, Any], key: str) -> bool:
    value = facts.get(key)
    return isinstance(value, list) and bool(value) and all(v not in (None, "") for v in value)


def _contains_unresolved(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().upper() in {"TBD", "UNKNOWN", "TO_BE_DETERMINED"}
    if isinstance(value, Mapping):
        return any(_contains_unresolved(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_unresolved(v) for v in value)
    return False


def _explicit_na(facts: Mapping[str, Any], dimension: str, evidence_refs: Sequence[str]) -> bool:
    values = facts.get("not_applicable")
    if not isinstance(values, Mapping):
        return False
    item = values.get(dimension)
    if not isinstance(item, Mapping):
        return False
    reason = item.get("reason")
    refs = item.get("evidence_refs")
    return bool(
        isinstance(reason, str)
        and reason.strip()
        and isinstance(refs, list)
        and refs
        and all(isinstance(ref, str) and ref in evidence_refs for ref in refs)
    )


def _required_or_na(failed: List[str], facts: Mapping[str, Any], key: str, code: str, evidence_refs: Sequence[str]) -> None:
    if not _nonempty_list(facts, key) and not _explicit_na(facts, key, evidence_refs):
        failed.append(code)


class SufficiencyGateService:
    SUPPORTED = {
        AutonomousMissionNode.N2_REQUIREMENT,
        AutonomousMissionNode.N3_CODE_ANALYSIS,
        AutonomousMissionNode.N4_TEST_DESIGN,
        AutonomousMissionNode.N5_TEST_DATA,
        AutonomousMissionNode.N6_EXECUTABLE_READINESS,
    }

    def __init__(self, runtime: RC72StateMachine) -> None:
        install_rc72_sufficiency_truth_overlay()
        self.runtime = runtime
        self.truth = runtime.truth

    def evaluate_and_apply(
        self,
        snapshot: SufficiencySnapshot,
        *,
        reviewer_worker_id: str,
        reviewer_session_id: str,
        reviewer_recommendation: Optional[str] = None,
    ) -> SufficiencyGateResult:
        del reviewer_recommendation
        self._validate_context(snapshot)
        self._persist_snapshot(snapshot)
        failed = list(dict.fromkeys(self._evaluate(snapshot)))
        criteria = self._criteria_codes(snapshot.node_type)
        passed = [code for code in criteria if code not in failed]
        decision = NodeGateDecision.PASS if not failed else NodeGateDecision.NEEDS_REVISION
        gap_ids = self._persist_gaps(snapshot, failed)
        gate_id = "NG-SSF-%s" % uuid.uuid4().hex[:16]
        self.runtime.apply_gate(
            NodeGate(
                gate_id=gate_id,
                mission_id=snapshot.mission_id,
                mission_node_id=snapshot.mission_node_id,
                node_type=snapshot.node_type,
                delivery_id=snapshot.delivery_id,
                decision=decision,
                reviewer_worker_id=reviewer_worker_id,
                reviewer_session_id=reviewer_session_id,
                criteria=criteria,
                passed=passed,
                failed=failed,
                evidence_refs=list(snapshot.evidence_refs),
                return_node=snapshot.node_type if failed else None,
                reason=("deterministic sufficiency contract satisfied" if not failed else "deterministic sufficiency failures: %s" % ",".join(failed)),
            )
        )
        return SufficiencyGateResult(snapshot.snapshot_id, gate_id, decision.value, passed, failed, gap_ids, reviewer_worker_id, reviewer_session_id)

    def _validate_context(self, snapshot: SufficiencySnapshot) -> None:
        if snapshot.node_type not in self.SUPPORTED:
            raise ContractError("SUFFICIENCY_NODE_NOT_SUPPORTED")
        node = self.runtime.node(snapshot.mission_node_id)
        if node.get("mission_id") != snapshot.mission_id or node.get("node_type") != snapshot.node_type.value:
            raise ContractError("SUFFICIENCY_NODE_IDENTITY_MISMATCH")
        deliveries = self.truth.query("rc72_node_delivery", delivery_id=snapshot.delivery_id)
        if len(deliveries) != 1 or deliveries[0].get("mission_node_id") != snapshot.mission_node_id:
            raise ContractError("SUFFICIENCY_DELIVERY_NOT_CANONICAL")
        for evidence_ref in snapshot.evidence_refs:
            rows = self.truth.query("rc7_evidence", evidence_id=evidence_ref)
            if len(rows) != 1 or rows[0].get("mission_id") != snapshot.mission_id:
                raise ContractError("SUFFICIENCY_EVIDENCE_NOT_CANONICAL:%s" % evidence_ref)

    def _persist_snapshot(self, snapshot: SufficiencySnapshot) -> None:
        if self.truth.query(_SNAPSHOT_ARTIFACT, snapshot_id=snapshot.snapshot_id):
            raise ContractError("SUFFICIENCY_SNAPSHOT_ALREADY_EXISTS")
        self.truth.append_atomic(_SNAPSHOT_EVENT, _serialize(snapshot, self.runtime.release_id))

    def _evaluate(self, snapshot: SufficiencySnapshot) -> List[str]:
        return {
            AutonomousMissionNode.N2_REQUIREMENT: self._n2,
            AutonomousMissionNode.N3_CODE_ANALYSIS: self._n3,
            AutonomousMissionNode.N4_TEST_DESIGN: self._n4,
            AutonomousMissionNode.N5_TEST_DATA: self._n5,
            AutonomousMissionNode.N6_EXECUTABLE_READINESS: self._n6,
        }[snapshot.node_type](snapshot)

    def _n2(self, snapshot: SufficiencySnapshot) -> List[str]:
        f, failed = snapshot.facts, []
        for key, code in (("br", "N2_BR_REQUIRED"), ("sr", "N2_SR_REQUIRED"), ("tr", "N2_TR_REQUIRED"), ("business_rules", "N2_BUSINESS_RULES_REQUIRED"), ("roles", "N2_ROLES_REQUIRED"), ("states", "N2_STATES_REQUIRED"), ("state_transitions", "N2_STATE_TRANSITIONS_REQUIRED"), ("negative_rules", "N2_NEGATIVE_RULES_REQUIRED"), ("boundary_rules", "N2_BOUNDARY_RULES_REQUIRED"), ("permission_rules", "N2_PERMISSION_RULES_REQUIRED"), ("data_rules", "N2_DATA_RULES_REQUIRED")):
            _required_or_na(failed, f, key, code, snapshot.evidence_refs)
        if not isinstance(f.get("requirement_id"), str) or not f["requirement_id"].strip(): failed.append("N2_REQUIREMENT_ID_REQUIRED")
        if not isinstance(f.get("sst_id"), str) or not f["sst_id"].strip(): failed.append("N2_SST_ID_REQUIRED")
        if not isinstance(f.get("unresolved_unknowns"), list) or f.get("unresolved_unknowns"): failed.append("N2_UNRESOLVED_UNKNOWNS")
        return failed

    def _n3(self, snapshot: SufficiencySnapshot) -> List[str]:
        f, failed = snapshot.facts, []
        for key, code in (("requirement_ids", "N3_REQUIREMENT_MAPPING_REQUIRED"), ("sst_ids", "N3_SST_MAPPING_REQUIRED"), ("changed_refs", "N3_CHANGED_CODE_REQUIRED"), ("api_contracts", "N3_API_CONTRACT_REQUIRED"), ("dto_constraints", "N3_DTO_CONSTRAINTS_REQUIRED"), ("service_impacts", "N3_SERVICE_IMPACT_REQUIRED"), ("db_constraints", "N3_DB_CONSTRAINTS_REQUIRED"), ("dependency_impacts", "N3_DEPENDENCY_IMPACT_REQUIRED"), ("reverse_mappings", "N3_REVERSE_MAPPING_REQUIRED"), ("graph_evidence_refs", "N3_CODEGRAPH_EVIDENCE_REQUIRED"), ("git_evidence_refs", "N3_GIT_EVIDENCE_REQUIRED")):
            if not _nonempty_list(f, key): failed.append(code)
        if (f.get("graph_evidence_refs") or []) and not all(ref in snapshot.evidence_refs for ref in f["graph_evidence_refs"]): failed.append("N3_CODEGRAPH_EVIDENCE_NOT_CANONICAL")
        if (f.get("git_evidence_refs") or []) and not all(ref in snapshot.evidence_refs for ref in f["git_evidence_refs"]): failed.append("N3_GIT_EVIDENCE_NOT_CANONICAL")
        if not isinstance(f.get("uncertainties"), list) or f.get("uncertainties"): failed.append("N3_UNRESOLVED_UNCERTAINTIES")
        return failed

    def _n4(self, snapshot: SufficiencySnapshot) -> List[str]:
        failed = []
        cases = snapshot.facts.get("cases")
        if not isinstance(cases, list) or not cases: return ["N4_CASES_REQUIRED"]
        obligations = {row.get("obligation_id"): row for row in self.truth.query("rc72_test_obligation", mission_id=snapshot.mission_id)}
        kinds: Dict[str, set] = {}
        for case in cases:
            if not isinstance(case, Mapping): failed.append("N4_CASE_SHAPE_INVALID"); continue
            oid, obligation = case.get("obligation_id"), obligations.get(case.get("obligation_id"))
            if obligation is None: failed.append("N4_ORPHAN_CASE")
            else:
                if case.get("requirement_id") != obligation.get("requirement_id"): failed.append("N4_REQUIREMENT_LINEAGE_MISMATCH")
                if case.get("sst_id") != obligation.get("sst_id"): failed.append("N4_SST_LINEAGE_MISMATCH")
                if case.get("test_level") != obligation.get("test_level"): failed.append("N4_TEST_LEVEL_LINEAGE_MISMATCH")
                kinds.setdefault(str(oid), set()).add(str(case.get("case_kind") or "").upper())
            if _contains_unresolved(case): failed.append("N4_UNRESOLVED_TBD_UNKNOWN")
            if not isinstance(case.get("preconditions"), list) or not case.get("preconditions"): failed.append("N4_PRECONDITIONS_REQUIRED")
            if not isinstance(case.get("steps"), list) or not case.get("steps"): failed.append("N4_STEPS_REQUIRED")
            if not isinstance(case.get("oracle"), Mapping) or not case.get("oracle"): failed.append("N4_ORACLE_REQUIRED")
            if not isinstance(case.get("evidence_requirements"), list) or not case.get("evidence_requirements"): failed.append("N4_EVIDENCE_REQUIREMENTS_REQUIRED")
        for oid, obligation in obligations.items():
            if str(obligation.get("risk_level") or "").upper() == "HIGH":
                if "NEGATIVE" not in kinds.get(str(oid), set()): failed.append("N4_HIGH_RISK_NEGATIVE_REQUIRED")
                if "BOUNDARY" not in kinds.get(str(oid), set()): failed.append("N4_HIGH_RISK_BOUNDARY_REQUIRED")
        return failed

    def _n5(self, snapshot: SufficiencySnapshot) -> List[str]:
        failed, rows = [], snapshot.facts.get("case_data")
        if not isinstance(rows, list) or not rows: return ["N5_CASE_DATA_REQUIRED"]
        for row in rows:
            if not isinstance(row, Mapping): failed.append("N5_CASE_DATA_SHAPE_INVALID"); continue
            if str(row.get("strategy") or "").upper() == "NONE_REQUIRED":
                if not isinstance(row.get("reason"), str) or not row.get("reason").strip(): failed.append("N5_NONE_REQUIRED_REASON_REQUIRED")
                continue
            if not isinstance(row.get("data_refs"), list) or not row.get("data_refs"): failed.append("N5_DATA_REF_REQUIRED")
            if not isinstance(row.get("precondition_refs"), list) or not row.get("precondition_refs"): failed.append("N5_PRECONDITION_REF_REQUIRED")
            if row.get("verified") is not True: failed.append("N5_DATA_VERIFY_REQUIRED")
            if row.get("reserved") is not True: failed.append("N5_DATA_RESERVE_REQUIRED")
            if not isinstance(row.get("cleanup_policy"), str) or not row.get("cleanup_policy").strip(): failed.append("N5_CLEANUP_POLICY_REQUIRED")
        return failed

    def _n6(self, snapshot: SufficiencySnapshot) -> List[str]:
        failed, contracts = [], snapshot.facts.get("contracts")
        if not isinstance(contracts, list) or not contracts: return ["N6_EXECUTABLE_CONTRACT_REQUIRED"]
        for c in contracts:
            if not isinstance(c, Mapping): failed.append("N6_CONTRACT_SHAPE_INVALID"); continue
            for key, code in (("case_id", "N6_CASE_REF_REQUIRED"), ("execution_target", "N6_EXECUTION_TARGET_REQUIRED"), ("tool_route", "N6_TOOL_ROUTE_REQUIRED"), ("cleanup", "N6_CLEANUP_REQUIRED")):
                if not isinstance(c.get(key), str) or not c.get(key).strip(): failed.append(code)
            if _contains_unresolved(c): failed.append("N6_UNRESOLVED_TBD_UNKNOWN")
            if not isinstance(c.get("input_bindings"), Mapping) or not c.get("input_bindings"): failed.append("N6_INPUT_BINDINGS_REQUIRED")
            if not isinstance(c.get("data_refs"), list) or not c.get("data_refs"): failed.append("N6_DATA_REFS_REQUIRED")
            if not isinstance(c.get("assertions"), list) or not c.get("assertions"): failed.append("N6_ASSERTIONS_REQUIRED")
            if not isinstance(c.get("oracle"), Mapping) or not c.get("oracle"): failed.append("N6_ORACLE_REQUIRED")
            if not isinstance(c.get("evidence_requirements"), list) or not c.get("evidence_requirements"): failed.append("N6_EVIDENCE_REQUIREMENTS_REQUIRED")
            if not isinstance(c.get("required_capabilities"), list) or not c.get("required_capabilities"): failed.append("N6_CAPABILITIES_REQUIRED")
            if not isinstance(c.get("required_resources"), list) or not c.get("required_resources"): failed.append("N6_RESOURCES_REQUIRED")
        return failed

    @staticmethod
    def _criteria_codes(n: AutonomousMissionNode) -> List[str]:
        return {
            AutonomousMissionNode.N2_REQUIREMENT: ["N2_REQUIREMENT_ID_REQUIRED", "N2_SST_ID_REQUIRED", "N2_BR_REQUIRED", "N2_SR_REQUIRED", "N2_TR_REQUIRED", "N2_BUSINESS_RULES_REQUIRED", "N2_ROLES_REQUIRED", "N2_STATES_REQUIRED", "N2_STATE_TRANSITIONS_REQUIRED", "N2_NEGATIVE_RULES_REQUIRED", "N2_BOUNDARY_RULES_REQUIRED", "N2_PERMISSION_RULES_REQUIRED", "N2_DATA_RULES_REQUIRED", "N2_UNRESOLVED_UNKNOWNS"],
            AutonomousMissionNode.N3_CODE_ANALYSIS: ["N3_REQUIREMENT_MAPPING_REQUIRED", "N3_SST_MAPPING_REQUIRED", "N3_CHANGED_CODE_REQUIRED", "N3_API_CONTRACT_REQUIRED", "N3_DTO_CONSTRAINTS_REQUIRED", "N3_SERVICE_IMPACT_REQUIRED", "N3_DB_CONSTRAINTS_REQUIRED", "N3_DEPENDENCY_IMPACT_REQUIRED", "N3_REVERSE_MAPPING_REQUIRED", "N3_CODEGRAPH_EVIDENCE_REQUIRED", "N3_GIT_EVIDENCE_REQUIRED", "N3_CODEGRAPH_EVIDENCE_NOT_CANONICAL", "N3_GIT_EVIDENCE_NOT_CANONICAL", "N3_UNRESOLVED_UNCERTAINTIES"],
            AutonomousMissionNode.N4_TEST_DESIGN: ["N4_CASES_REQUIRED", "N4_CASE_SHAPE_INVALID", "N4_ORPHAN_CASE", "N4_REQUIREMENT_LINEAGE_MISMATCH", "N4_SST_LINEAGE_MISMATCH", "N4_TEST_LEVEL_LINEAGE_MISMATCH", "N4_UNRESOLVED_TBD_UNKNOWN", "N4_PRECONDITIONS_REQUIRED", "N4_STEPS_REQUIRED", "N4_ORACLE_REQUIRED", "N4_EVIDENCE_REQUIREMENTS_REQUIRED", "N4_HIGH_RISK_NEGATIVE_REQUIRED", "N4_HIGH_RISK_BOUNDARY_REQUIRED"],
            AutonomousMissionNode.N5_TEST_DATA: ["N5_CASE_DATA_REQUIRED", "N5_CASE_DATA_SHAPE_INVALID", "N5_NONE_REQUIRED_REASON_REQUIRED", "N5_DATA_REF_REQUIRED", "N5_PRECONDITION_REF_REQUIRED", "N5_DATA_VERIFY_REQUIRED", "N5_DATA_RESERVE_REQUIRED", "N5_CLEANUP_POLICY_REQUIRED"],
            AutonomousMissionNode.N6_EXECUTABLE_READINESS: ["N6_EXECUTABLE_CONTRACT_REQUIRED", "N6_CONTRACT_SHAPE_INVALID", "N6_CASE_REF_REQUIRED", "N6_EXECUTION_TARGET_REQUIRED", "N6_TOOL_ROUTE_REQUIRED", "N6_CLEANUP_REQUIRED", "N6_UNRESOLVED_TBD_UNKNOWN", "N6_INPUT_BINDINGS_REQUIRED", "N6_DATA_REFS_REQUIRED", "N6_ASSERTIONS_REQUIRED", "N6_ORACLE_REQUIRED", "N6_EVIDENCE_REQUIREMENTS_REQUIRED", "N6_CAPABILITIES_REQUIRED", "N6_RESOURCES_REQUIRED"],
        }[n]

    def _persist_gaps(self, snapshot: SufficiencySnapshot, failed: Sequence[str]) -> List[str]:
        ids = []
        for code in failed:
            gap_id = "GAP-SSF-%s" % uuid.uuid4().hex[:16]
            append_entity(self.truth, Gap(gap_id=gap_id, mission_id=snapshot.mission_id, source_node=snapshot.node_type.value, category=code, severity=GapSeverity.HIGH, target_node=snapshot.node_type.value, description="deterministic sufficiency gate failed: %s" % code, subject_refs=[snapshot.delivery_id] + list(snapshot.source_artifact_refs), evidence_refs=list(snapshot.evidence_refs), acceptance_criteria=["resolve %s and regenerate/review node delivery" % code]), release_id=self.runtime.release_id)
            ids.append(gap_id)
        return ids


install_rc72_sufficiency_truth_overlay()
