"""RC7.2 R1-native N10 Release Convergence aggregator.

Callers do not provide PASS booleans. Every ReleaseConvergenceFacts dimension
is derived from canonical R1 truth. A raw TestObligation `VERIFIED` flag is
insufficient: completion additionally requires PASS ETUs, PASS independently-
evaluated WorkItems, COMPLETED bindings, PASS execution attempts and resolvable
canonical Evidence.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_coverage_convergence import install_rc72_coverage_overlay
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_release_scope import ReleaseScopeService, install_rc72_release_scope_overlay
from .rc72_state_machine import RC72StateMachine, ReleaseConvergenceFacts, ReleaseConvergenceResult
from .truth_overlay import install_rc7_truth_overlay

_CONVERGENCE_SNAPSHOT = "rc72_release_convergence_snapshot"
_EVENT_TYPE = "RC72_RELEASE_CONVERGENCE_SNAPSHOT_UPSERTED"
_BUCKET = "rc72_release_convergence_snapshots"
_FACT_FIELDS = (
    "requirement_completion", "sst_completion", "obligation_completion",
    "required_l1_l7_completion", "high_risk_completion", "incremental_coverage_met",
    "critical_defects_closed", "no_blocked_workitems", "no_unresolved_gaps",
    "evidence_complete", "runtime_integrity", "human_gate_required", "runtime_blocked",
)


@dataclass(frozen=True)
class ReleaseConvergenceSnapshot:
    snapshot_id: str
    mission_id: str
    release_batch_id: str
    manifest_id: str
    scope_snapshot_id: str
    facts: ReleaseConvergenceFacts
    result: ReleaseConvergenceResult
    blockers: List[str] = field(default_factory=list)
    proven_obligation_ids: List[str] = field(default_factory=list)
    unproven_obligation_ids: List[str] = field(default_factory=list)
    coverage_observation_ids: List[str] = field(default_factory=list)
    created_at: int = field(default_factory=lambda: int(time.time()))


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _validate_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in ("snapshot_id", "mission_id", "release_batch_id", "manifest_id", "scope_snapshot_id", "release_id"):
        out[name] = _required(out, name)
    facts = out.get("facts")
    if not isinstance(facts, dict) or set(facts) != set(_FACT_FIELDS):
        raise _contracts.DomainValidationError("RELEASE_CONVERGENCE_FACTS_INVALID")
    if not all(isinstance(facts[name], bool) for name in _FACT_FIELDS):
        raise _contracts.DomainValidationError("RELEASE_CONVERGENCE_FACTS_MUST_BE_BOOLEAN")
    try:
        out["result"] = ReleaseConvergenceResult(_required(out, "result").upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("RELEASE_CONVERGENCE_RESULT_INVALID") from exc
    for name in ("blockers", "proven_obligation_ids", "unproven_obligation_ids", "coverage_observation_ids"):
        _contracts._require_string_list(out, name)
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("RELEASE_CONVERGENCE_CREATED_AT_INVALID")
    out["artifact_type"] = _CONVERGENCE_SNAPSHOT
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def install_rc72_release_convergence_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_coverage_overlay()
    install_rc72_release_scope_overlay()
    _contracts.VALIDATORS[_CONVERGENCE_SNAPSHOT] = _validate_snapshot
    _truth.BUCKETS[_CONVERGENCE_SNAPSHOT] = _BUCKET
    _truth.EVENT_TYPES[_EVENT_TYPE] = (_CONVERGENCE_SNAPSHOT, "snapshot_id")
    _truth.IDENTITY_FIELDS[_CONVERGENCE_SNAPSHOT] = "snapshot_id"


def _ensure_projection_bucket(truth: TruthRuntime) -> None:
    if not hasattr(truth.projection, _BUCKET):
        setattr(truth.projection, _BUCKET, {})
    truth.projection._versions.setdefault(_CONVERGENCE_SNAPSHOT, {})


class ReleaseConvergenceAggregator:
    _GAP_TERMINAL = {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}
    _COVERAGE_GAP_TERMINAL = {"RESOLVED", "EXCLUDED_APPROVED"}
    _BACK_EDGE_TERMINAL = {"RESOLVED", "SUPERSEDED"}
    _DEFECT_ACCEPTABLE = {"CLOSED", "DUPLICATE", "NOT_A_DEFECT"}
    _HIGH_RISKS = {"HIGH", "CRITICAL", "BLOCKER"}

    def __init__(self, truth: TruthRuntime, *, release_id: str, runtime: RC72StateMachine) -> None:
        install_rc72_release_convergence_overlay()
        _ensure_projection_bucket(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("RELEASE_CONVERGENCE_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.runtime = runtime
        self.scope = ReleaseScopeService(truth, release_id=self.release_id)

    def install_overlay(self) -> None:
        install_rc72_release_convergence_overlay()

    def _safe_query(self, artifact_type: str, **filters: Any) -> List[Dict[str, Any]]:
        if artifact_type not in _truth.BUCKETS:
            return []
        return self.truth.query(artifact_type, **filters)

    def _one_batch(self, mission_id: str) -> Dict[str, Any]:
        rows = self.truth.query("rc72_release_batch", mission_id=mission_id)
        if len(rows) != 1:
            raise ContractError("RELEASE_CONVERGENCE_RELEASE_BATCH_REQUIRED")
        return rows[0]

    def _one_manifest(self, mission_id: str, release_batch_id: str) -> Dict[str, Any]:
        rows = [
            row for row in self._safe_query("rc72_release_scope_manifest", mission_id=mission_id)
            if row.get("release_batch_id") == release_batch_id
        ]
        if not rows:
            raise ContractError("RELEASE_CONVERGENCE_SCOPE_MANIFEST_REQUIRED")
        if len(rows) != 1:
            raise ContractError("RELEASE_CONVERGENCE_SCOPE_MANIFEST_NOT_UNIQUE")
        return rows[0]

    def _canonical_evidence_resolves(self, *, mission_id: str, evidence_ids: Sequence[str], subject_refs: Set[str]) -> bool:
        if not evidence_ids:
            return False
        for evidence_id in evidence_ids:
            rows = self._safe_query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1 or rows[0].get("mission_id") != mission_id:
                return False
            if not set(rows[0].get("subject_refs") or []).intersection(subject_refs):
                return False
        return True

    def _binding_proves_case(self, *, mission_id: str, obligation: Mapping[str, Any], etu: Mapping[str, Any], case_id: str) -> bool:
        candidates = [
            row for row in self._safe_query("rc72_workitem_attempt_binding", mission_id=mission_id)
            if row.get("etu_id") == etu.get("etu_id")
            and row.get("case_id") == case_id
            and row.get("state") == "COMPLETED"
        ]
        for binding in candidates:
            tasks = self._safe_query("rc7_task", task_id=str(binding.get("workitem_id") or ""))
            if len(tasks) != 1 or tasks[0].get("mission_id") != mission_id or tasks[0].get("state") != "PASS":
                continue
            attempts = self._safe_query("execution_attempt", attempt_id=str(binding.get("attempt_id") or ""))
            if len(attempts) != 1:
                continue
            attempt = attempts[0]
            if attempt.get("status") != "PASS" or attempt.get("tc_id") != case_id:
                continue
            if str(attempt.get("layer") or "").upper() != str(obligation.get("test_level") or "").upper():
                continue
            evidence_ids = list(attempt.get("evidence_refs") or [])
            if self._canonical_evidence_resolves(
                mission_id=mission_id,
                evidence_ids=evidence_ids,
                subject_refs={str(binding.get("attempt_id")), case_id, str(obligation.get("obligation_id"))},
            ):
                return True
        return False

    def _obligation_proven(self, obligation: Mapping[str, Any]) -> bool:
        if obligation.get("status") != "VERIFIED":
            return False
        mission_id = str(obligation["mission_id"])
        etus = [
            row for row in self._safe_query("rc72_etu", mission_id=mission_id)
            if row.get("obligation_id") == obligation.get("obligation_id")
        ]
        if not etus:
            return False
        for etu in etus:
            if etu.get("state") != "PASS":
                return False
            case_ids = list(etu.get("case_ids") or [])
            if not case_ids:
                return False
            if not all(
                self._binding_proves_case(mission_id=mission_id, obligation=obligation, etu=etu, case_id=case_id)
                for case_id in case_ids
            ):
                return False
        return True

    def _coverage_met(self, batch: Mapping[str, Any]) -> Tuple[bool, List[str], List[str]]:
        blockers: List[str] = []
        selected: List[str] = []
        all_rows = self._safe_query("rc72_coverage_observation", mission_id=str(batch["mission_id"]))
        for application_id in list(batch.get("application_ids") or []):
            rows = [
                row for row in all_rows
                if row.get("release_batch_id") == batch.get("release_batch_id")
                and row.get("application_id") == application_id
            ]
            if not rows:
                blockers.append("coverage:%s:MISSING" % application_id)
                continue
            latest = sorted(rows, key=lambda row: (int(row.get("observed_at") or 0), str(row.get("observation_id") or "")))[-1]
            selected.append(str(latest["observation_id"]))
            total = int(latest.get("total_units") or 0)
            covered = int(latest.get("covered_units") or 0)
            target = float(latest.get("target_ratio") or 0.0)
            ratio = float(covered) / float(total) if total > 0 else 0.0
            if ratio + 1e-12 < target:
                blockers.append("coverage:%s:%.6f<%.6f" % (application_id, ratio, target))
        return not blockers, selected, blockers

    def _runtime_facts(self, mission_id: str) -> Tuple[bool, bool, bool, List[str]]:
        blockers: List[str] = []
        nodes = self._safe_query("rc72_mission_node", mission_id=mission_id)
        by_type = {str(row.get("node_type")): row for row in nodes}
        expected_types = [node.value for node in AutonomousMissionNode.ordered()]
        structurally_valid = len(nodes) == 10 and len(by_type) == 10 and set(by_type) == set(expected_types)
        if not structurally_valid:
            blockers.append("runtime:N1-N10_GRAPH_INVALID")
        human_gate = False
        runtime_blocked = False
        for node_type in expected_types[:-1]:
            row = by_type.get(node_type)
            state = str(row.get("state")) if row else "MISSING"
            if state != MissionNodeState.PASS.value:
                blockers.append("node:%s:%s" % (node_type, state))
            if state == MissionNodeState.HUMAN_GATE.value:
                human_gate = True
            if state == MissionNodeState.BLOCKED.value:
                runtime_blocked = True
        n10 = by_type.get(AutonomousMissionNode.N10_RELEASE_CONVERGENCE.value)
        if n10:
            state = str(n10.get("state"))
            if state == MissionNodeState.HUMAN_GATE.value:
                human_gate = True
            if state == MissionNodeState.BLOCKED.value:
                runtime_blocked = True
            if state in {MissionNodeState.STALE.value, MissionNodeState.NEEDS_REVISION.value, MissionNodeState.NOT_STARTED.value}:
                blockers.append("node:N10_RELEASE_CONVERGENCE:%s" % state)
        return structurally_valid and not any(item.startswith("node:") for item in blockers), human_gate, runtime_blocked, blockers

    def aggregate(self, *, mission_id: str) -> ReleaseConvergenceSnapshot:
        batch = self._one_batch(mission_id)
        manifest = self._one_manifest(mission_id, str(batch["release_batch_id"]))
        scope_snapshot = self.scope.evaluate_denominator(manifest_id=str(manifest["manifest_id"]))
        blockers: List[str] = []
        if not scope_snapshot.denominator_complete:
            blockers.extend("scope:missing-sst:%s" % sst for sst in scope_snapshot.missing_ssts)
            for sst, levels in sorted(scope_snapshot.missing_required_levels.items()):
                blockers.extend("scope:missing-level:%s:%s" % (sst, level) for level in levels)
            blockers.extend("scope:out-of-scope-obligation:%s" % oid for oid in scope_snapshot.out_of_scope_obligation_ids)

        obligations = [
            row for row in self._safe_query("rc72_test_obligation", mission_id=mission_id)
            if row.get("release_batch_id") == batch.get("release_batch_id")
        ]
        proven = {str(row["obligation_id"]) for row in obligations if self._obligation_proven(row)}
        all_ids = {str(row["obligation_id"]) for row in obligations}
        unproven = sorted(all_ids - proven)
        blockers.extend("obligation:%s:UNPROVEN" % oid for oid in unproven)

        requirement_ssts = dict(manifest["requirement_ssts"])
        required_levels = dict(manifest["required_levels_by_sst"])
        pair_proven: Dict[Tuple[str, str], bool] = {}
        for requirement_id, ssts in requirement_ssts.items():
            for sst_id in ssts:
                for level in required_levels[sst_id]:
                    matching = [
                        row for row in obligations
                        if row.get("requirement_id") == requirement_id
                        and row.get("sst_id") == sst_id
                        and str(row.get("test_level") or "").upper() == str(level).upper()
                    ]
                    pair_proven[(sst_id, str(level).upper())] = bool(matching) and any(
                        str(row["obligation_id"]) in proven for row in matching
                    )
        required_levels_complete = scope_snapshot.denominator_complete and bool(pair_proven) and all(pair_proven.values())
        sst_completion = required_levels_complete
        requirement_completion = required_levels_complete
        obligation_completion = scope_snapshot.denominator_complete and bool(obligations) and not unproven
        high_risk = [row for row in obligations if str(row.get("risk_level") or "").upper() in self._HIGH_RISKS]
        high_risk_completion = all(str(row["obligation_id"]) in proven for row in high_risk)
        evidence_complete = obligation_completion

        coverage_met, coverage_ids, coverage_blockers = self._coverage_met(batch)
        blockers.extend(coverage_blockers)

        critical_defects_closed = True
        for defect in self._safe_query("rc7_defect", mission_id=mission_id):
            if str(defect.get("severity") or "").upper() in self._HIGH_RISKS:
                state = str(defect.get("state") or "").upper()
                if state not in self._DEFECT_ACCEPTABLE:
                    critical_defects_closed = False
                    blockers.append("defect:%s:%s" % (defect.get("defect_id"), state))

        no_blocked_workitems = True
        human_gate_required = False
        for task in self._safe_query("rc7_task", mission_id=mission_id):
            state = str(task.get("state") or "").upper()
            if state != "PASS":
                no_blocked_workitems = False
                blockers.append("workitem:%s:%s" % (task.get("task_id"), state))
            if state == "HUMAN_REQUIRED":
                human_gate_required = True

        no_unresolved_gaps = True
        for gap in self._safe_query("rc7_gap", mission_id=mission_id):
            state = str(gap.get("state") or "").upper()
            if state not in self._GAP_TERMINAL:
                no_unresolved_gaps = False
                blockers.append("gap:%s:%s" % (gap.get("gap_id"), state))
            if state == "HUMAN_REQUIRED":
                human_gate_required = True
        for gap in self._safe_query("rc72_coverage_gap", mission_id=mission_id):
            state = str(gap.get("status") or "").upper()
            if state not in self._COVERAGE_GAP_TERMINAL:
                no_unresolved_gaps = False
                blockers.append("coverage-gap:%s" % gap.get("gap_id"))
        for edge in self._safe_query("rc72_back_edge", mission_id=mission_id):
            state = str(edge.get("state") or "").upper()
            if state not in self._BACK_EDGE_TERMINAL:
                no_unresolved_gaps = False
                blockers.append("back-edge:%s:%s" % (edge.get("back_edge_id"), state))

        runtime_integrity, node_human, runtime_blocked, runtime_blockers = self._runtime_facts(mission_id)
        human_gate_required = human_gate_required or node_human
        blockers.extend(runtime_blockers)
        for failure in self._safe_query("rc72_provider_failure", mission_id=mission_id):
            state = str(failure.get("state") or "").upper()
            if state in {"BLOCKED_PROVIDER", "OPERATOR_REPAIR_REQUIRED"}:
                runtime_blocked = True
                blockers.append("provider-failure:%s:%s" % (failure.get("failure_id"), state))
        for binding in self._safe_query("rc72_workitem_attempt_binding", mission_id=mission_id):
            if str(binding.get("state") or "").upper() == "BLOCKED":
                runtime_blocked = True
                blockers.append("attempt-binding:%s:BLOCKED" % binding.get("binding_id"))
        for decision in self._safe_query("rc72_capability_decision", mission_id=mission_id):
            if str(decision.get("decision") or "").upper() == "HUMAN_GATE":
                human_gate_required = True
                blockers.append("capability-request:%s:HUMAN_GATE" % decision.get("request_id"))

        facts = ReleaseConvergenceFacts(
            requirement_completion=requirement_completion,
            sst_completion=sst_completion,
            obligation_completion=obligation_completion,
            required_l1_l7_completion=required_levels_complete,
            high_risk_completion=high_risk_completion,
            incremental_coverage_met=coverage_met,
            critical_defects_closed=critical_defects_closed,
            no_blocked_workitems=no_blocked_workitems,
            no_unresolved_gaps=no_unresolved_gaps,
            evidence_complete=evidence_complete,
            runtime_integrity=runtime_integrity,
            human_gate_required=human_gate_required,
            runtime_blocked=runtime_blocked,
        )
        result = self.runtime.evaluate_convergence(facts)
        snapshot = ReleaseConvergenceSnapshot(
            snapshot_id=_new("CONVERGENCE"), mission_id=mission_id,
            release_batch_id=str(batch["release_batch_id"]), manifest_id=str(manifest["manifest_id"]),
            scope_snapshot_id=scope_snapshot.snapshot_id, facts=facts, result=result,
            blockers=sorted(set(blockers)), proven_obligation_ids=sorted(proven),
            unproven_obligation_ids=unproven, coverage_observation_ids=sorted(coverage_ids),
        )
        self.truth.append_atomic(
            _EVENT_TYPE,
            {
                "snapshot_id": snapshot.snapshot_id,
                "mission_id": snapshot.mission_id,
                "release_batch_id": snapshot.release_batch_id,
                "manifest_id": snapshot.manifest_id,
                "scope_snapshot_id": snapshot.scope_snapshot_id,
                "facts": asdict(snapshot.facts),
                "result": snapshot.result.value,
                "blockers": list(snapshot.blockers),
                "proven_obligation_ids": list(snapshot.proven_obligation_ids),
                "unproven_obligation_ids": list(snapshot.unproven_obligation_ids),
                "coverage_observation_ids": list(snapshot.coverage_observation_ids),
                "created_at": snapshot.created_at,
                "release_id": self.release_id,
                "artifact_version": 1,
            },
        )
        return snapshot
