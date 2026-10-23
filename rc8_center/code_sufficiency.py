"""Center-owned CODE_SUFFICIENCY frozen-ledger evaluation.

The denominator comes from a frozen CodeSourceSnapshot plus its bound
TraceabilityGraph. Worker/LLM findings may enrich evidence but cannot decide
which changed files/methods exist or shrink the required set.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.governance import CoverageDimension, SufficiencyEvaluation
from rc8_runtime.sufficiency import DimensionAssessment, DimensionState, FrozenSufficiencyLedger, RequiredDimension, evaluate_frozen_ledger

from .traceability import TraceNode, TraceNodeType, TraceRelationType, TraceVerificationState, TraceabilityError


CENTER_CODE_EVALUATOR_ID = "RC8_CENTER_SUFFICIENCY_LEDGER"
CENTER_CODE_POLICY = "rc8.code-sufficiency-center.v1"
_VERIFIED_STATES = {
    TraceVerificationState.STATIC_VERIFIED,
    TraceVerificationState.RUNTIME_VERIFIED,
    TraceVerificationState.MULTI_SOURCE_VERIFIED,
}
_CODE_NODE_TYPES = {
    TraceNodeType.CONTROLLER,
    TraceNodeType.METHOD,
    TraceNodeType.SERVICE,
    TraceNodeType.REPOSITORY,
    TraceNodeType.MAPPER,
}
_PERSISTENCE_NODE_TYPES = {TraceNodeType.REPOSITORY, TraceNodeType.MAPPER, TraceNodeType.SQL, TraceNodeType.DATABASE, TraceNodeType.TABLE}


def _norm_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lstrip("./")


def _tuple_strings(value: object, name: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise RC8ContractError("CODE_SUFFICIENCY_%s_REQUIRED" % name.upper())
    result = tuple(_norm_path(item) for item in value if isinstance(item, str) and _norm_path(item))
    if len(result) != len(value):
        raise RC8ContractError("CODE_SUFFICIENCY_%s_INVALID" % name.upper())
    return result


def _evidence_ref(value: object) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


@dataclass(frozen=True)
class CodeSufficiencyFacts:
    graph_id: str
    snapshot_id: str
    changed_java_files: Tuple[str, ...]
    changed_methods: Tuple[str, ...]
    source_refs: Tuple[str, ...]


@dataclass(frozen=True)
class CodeSufficiencyEvaluation:
    ledger: FrozenSufficiencyLedger
    evaluation: SufficiencyEvaluation
    assessments: Tuple[DimensionAssessment, ...]


class CenterCodeSufficiencyEvaluator:
    """Evaluate CODE_SUFFICIENCY from durable snapshot/graph truth only."""

    def __init__(self, traceability_repository) -> None:
        self.repository = traceability_repository

    def evaluate(
        self,
        *,
        test_run_id: str,
        stage_instance_id: str,
        graph_id: str,
        active_gap_ids: Sequence[str] = (),
        worker_claimed_sufficient: Optional[bool] = None,
    ) -> CodeSufficiencyEvaluation:
        graph = self.repository.get_graph(graph_id)
        if graph is None:
            raise TraceabilityError("CODE_SUFFICIENCY_TRACE_GRAPH_NOT_FOUND")
        if graph.test_run_id != test_run_id:
            raise TraceabilityError("CODE_SUFFICIENCY_TEST_RUN_MISMATCH")
        snapshot = self.repository.get_code_source(graph.code_source_snapshot_id)
        if snapshot is None:
            raise TraceabilityError("CODE_SUFFICIENCY_CODE_SOURCE_NOT_FOUND")
        if snapshot.snapshot_id != graph.code_source_snapshot_id:
            raise TraceabilityError("CODE_SUFFICIENCY_CODE_SOURCE_MISMATCH")
        if snapshot.scope_revision_id != graph.scope_revision_id:
            raise TraceabilityError("CODE_SUFFICIENCY_SCOPE_REVISION_MISMATCH")

        payload = dict(snapshot.payload or {})
        changed_files = _tuple_strings(payload.get("changed_java_files"), "changed_java_files")
        changed_methods = _tuple_strings(payload.get("changed_methods"), "changed_methods")
        no_code_change_ref = _evidence_ref(payload.get("no_code_change_evidence_ref"))
        if not changed_files and not no_code_change_ref:
            raise RC8ContractError("CODE_SUFFICIENCY_EMPTY_CHANGESET_REQUIRES_EVIDENCE")
        if changed_files and not changed_methods:
            # Missing method inventory is an explicit required UNKNOWN dimension,
            # never interpreted as "there were no changed methods".
            changed_methods = tuple()

        facts = CodeSufficiencyFacts(
            graph_id=graph.graph_id,
            snapshot_id=snapshot.snapshot_id,
            changed_java_files=changed_files,
            changed_methods=changed_methods,
            source_refs=(
                "code-source:%s" % snapshot.snapshot_id,
                "trace-graph:%s" % graph.graph_id,
                "scope-revision:%s" % graph.scope_revision_id,
            ),
        )
        ledger = self._ledger(test_run_id, stage_instance_id, facts, payload)
        assessments = self._assess(graph, snapshot, facts, ledger, payload)
        decision = evaluate_frozen_ledger(
            ledger,
            assessments,
            evaluator_id=CENTER_CODE_EVALUATOR_ID,
            active_gap_ids=active_gap_ids,
            worker_claimed_sufficient=worker_claimed_sufficient,
        )
        return CodeSufficiencyEvaluation(
            ledger=ledger,
            evaluation=decision.to_evaluation("center-code-%s" % ledger.ledger_id),
            assessments=tuple(decision.assessments),
        )

    def _ledger(self, test_run_id: str, stage_instance_id: str, facts: CodeSufficiencyFacts, payload: Mapping[str, object]) -> FrozenSufficiencyLedger:
        dimensions: List[RequiredDimension] = [
            RequiredDimension("code:snapshot-consistency", CoverageDimension.VERIFICATION_POINT, facts.source_refs[0]),
        ]
        if facts.changed_java_files:
            for path in facts.changed_java_files:
                dimensions.append(RequiredDimension("code:changed-file:%s" % path, CoverageDimension.VERIFICATION_POINT, facts.source_refs[0]))
                dimensions.append(RequiredDimension("code:codegraph-file:%s" % path, CoverageDimension.VERIFICATION_POINT, facts.source_refs[1]))
        else:
            dimensions.append(RequiredDimension("code:no-code-change", CoverageDimension.VERIFICATION_POINT, facts.source_refs[0]))

        if facts.changed_java_files and not facts.changed_methods:
            dimensions.append(RequiredDimension("code:changed-method-inventory", CoverageDimension.CHANGED_METHOD, facts.source_refs[0]))
        else:
            for method in facts.changed_methods:
                dimensions.append(RequiredDimension("code:changed-method:%s" % method, CoverageDimension.CHANGED_METHOD, facts.source_refs[0]))

        dimensions.extend(
            [
                RequiredDimension("code:api-impact", CoverageDimension.API, facts.source_refs[1]),
                RequiredDimension("code:call-chain-impact", CoverageDimension.VERIFICATION_POINT, facts.source_refs[1]),
                RequiredDimension("code:persistence-impact", CoverageDimension.VERIFICATION_POINT, facts.source_refs[1]),
                RequiredDimension("code:cross-service-impact", CoverageDimension.VERIFICATION_POINT, facts.source_refs[1]),
                RequiredDimension("code:unknown-impact-zero", CoverageDimension.VERIFICATION_POINT, facts.source_refs[1]),
            ]
        )
        digest = hashlib.sha256("\x1f".join([test_run_id, stage_instance_id, facts.snapshot_id, facts.graph_id] + [item.dimension_id for item in dimensions]).encode("utf-8")).hexdigest()[:32]
        return FrozenSufficiencyLedger(
            ledger_id="ledger-code-%s" % digest,
            test_run_id=test_run_id,
            subject_id=stage_instance_id,
            policy_version=CENTER_CODE_POLICY,
            source_refs=facts.source_refs,
            required_dimensions=tuple(dimensions),
        )

    def _assess(self, graph, snapshot, facts: CodeSufficiencyFacts, ledger: FrozenSufficiencyLedger, payload: Mapping[str, object]) -> List[DimensionAssessment]:
        nodes = self.repository.find_nodes(graph.graph_id)
        edges = self.repository.list_edges(graph.graph_id)
        node_by_id = {node.node_id: node for node in nodes}
        evidence_by_edge = {edge.edge_id: self.repository.list_evidence(edge.edge_id) for edge in edges}
        verified_edges = [edge for edge in edges if edge.verification_state in _VERIFIED_STATES]

        assessments: Dict[str, DimensionAssessment] = {}
        assessments["code:snapshot-consistency"] = DimensionAssessment(
            "code:snapshot-consistency",
            DimensionState.SATISFIED,
            evidence_refs=("code-source:%s" % snapshot.snapshot_id, "trace-graph:%s" % graph.graph_id),
            reason="trace graph is bound to the frozen code source snapshot and scope revision",
        )

        no_code_change_ref = _evidence_ref(payload.get("no_code_change_evidence_ref"))
        if not facts.changed_java_files:
            assessments["code:no-code-change"] = DimensionAssessment(
                "code:no-code-change", DimensionState.NOT_APPLICABLE, evidence_refs=(no_code_change_ref,), reason="frozen change set proves no Java code change"
            )
        else:
            for path in facts.changed_java_files:
                file_nodes = [node for node in nodes if self._node_matches_file(node, path)]
                file_refs = tuple("trace-node:%s" % node.node_id for node in file_nodes)
                assessments["code:changed-file:%s" % path] = (
                    DimensionAssessment("code:changed-file:%s" % path, DimensionState.SATISFIED, evidence_refs=file_refs, reason="changed file is represented in frozen trace graph")
                    if file_refs
                    else DimensionAssessment("code:changed-file:%s" % path, DimensionState.UNKNOWN, reason="changed file has no trace node")
                )
                codegraph_refs = self._matching_evidence_refs(verified_edges, evidence_by_edge, path=path, evidence_types={"CODEGRAPH"})
                assessments["code:codegraph-file:%s" % path] = (
                    DimensionAssessment("code:codegraph-file:%s" % path, DimensionState.SATISFIED, evidence_refs=codegraph_refs, reason="verified CodeGraph evidence covers changed file")
                    if codegraph_refs
                    else DimensionAssessment("code:codegraph-file:%s" % path, DimensionState.UNKNOWN, reason="real CodeGraph evidence missing for changed file")
                )

        if facts.changed_java_files and not facts.changed_methods:
            assessments["code:changed-method-inventory"] = DimensionAssessment(
                "code:changed-method-inventory", DimensionState.UNKNOWN, reason="frozen snapshot does not contain changed method inventory"
            )
        else:
            for method in facts.changed_methods:
                method_nodes = [node for node in nodes if node.node_type == TraceNodeType.METHOD and (node.business_key == method or str(node.payload.get("method") or "") == method)]
                refs = tuple("trace-node:%s" % node.node_id for node in method_nodes)
                assessments["code:changed-method:%s" % method] = (
                    DimensionAssessment("code:changed-method:%s" % method, DimensionState.SATISFIED, evidence_refs=refs, reason="changed method exists in frozen trace graph")
                    if refs
                    else DimensionAssessment("code:changed-method:%s" % method, DimensionState.UNKNOWN, reason="changed method missing from trace graph")
                )

        assessments["code:api-impact"] = self._impact_dimension(
            "code:api-impact", nodes, verified_edges, evidence_by_edge,
            node_types={TraceNodeType.API},
            relation_types={TraceRelationType.API_IMPLEMENTED_BY, TraceRelationType.PAGE_CALLS_API},
            payload=graph.payload,
            na_flag="api_impact_not_applicable",
            na_evidence="api_impact_evidence_ref",
            satisfied_reason="API impact has verified trace evidence",
        )
        assessments["code:call-chain-impact"] = self._impact_dimension(
            "code:call-chain-impact", nodes, verified_edges, evidence_by_edge,
            node_types=_CODE_NODE_TYPES,
            relation_types={TraceRelationType.CALLS, TraceRelationType.API_IMPLEMENTED_BY},
            payload=graph.payload,
            na_flag="call_chain_not_applicable",
            na_evidence="call_chain_evidence_ref",
            satisfied_reason="upstream/downstream call chain is evidence verified",
            required_evidence_types={"CODEGRAPH", "SOURCE_CODE", "SPRING_MAPPING"},
        )
        assessments["code:persistence-impact"] = self._impact_dimension(
            "code:persistence-impact", nodes, verified_edges, evidence_by_edge,
            node_types=_PERSISTENCE_NODE_TYPES,
            relation_types={TraceRelationType.EXECUTES_SQL, TraceRelationType.READS_TABLE, TraceRelationType.WRITES_TABLE},
            payload=graph.payload,
            na_flag="persistence_not_applicable",
            na_evidence="persistence_evidence_ref",
            satisfied_reason="persistence/SQL/table impact has evidence verified",
            required_evidence_types={"SQL", "MYBATIS_MAPPING", "DATABASE_METADATA", "CODEGRAPH"},
        )
        assessments["code:cross-service-impact"] = self._explicit_applicability_dimension(
            "code:cross-service-impact", graph.payload, "cross_service_applicable", "cross_service_evidence_ref", "cross-service impact explicitly assessed"
        )

        unknowns = graph.payload.get("unknown_impacts") if isinstance(graph.payload, Mapping) else None
        unknown_ref = _evidence_ref(graph.payload.get("unknown_impact_evidence_ref")) if isinstance(graph.payload, Mapping) else None
        if isinstance(unknowns, list) and unknowns:
            assessments["code:unknown-impact-zero"] = DimensionAssessment(
                "code:unknown-impact-zero", DimensionState.UNSATISFIED, evidence_refs=(unknown_ref,) if unknown_ref else (), reason="unresolved code impacts remain: %s" % len(unknowns)
            )
        elif isinstance(unknowns, list) and not unknowns and unknown_ref:
            assessments["code:unknown-impact-zero"] = DimensionAssessment(
                "code:unknown-impact-zero", DimensionState.SATISFIED, evidence_refs=(unknown_ref,), reason="unknown impact inventory explicitly assessed and empty"
            )
        else:
            assessments["code:unknown-impact-zero"] = DimensionAssessment(
                "code:unknown-impact-zero", DimensionState.UNKNOWN, reason="unknown impact inventory or evidence is missing"
            )

        return [assessments[item.dimension_id] for item in ledger.required_dimensions]

    @staticmethod
    def _node_matches_file(node: TraceNode, path: str) -> bool:
        candidates = [node.payload.get("source_file"), node.payload.get("changed_file"), node.payload.get("file")]
        normalized = _norm_path(path)
        return any(_norm_path(value) == normalized for value in candidates if isinstance(value, str))

    @staticmethod
    def _matching_evidence_refs(edges, evidence_by_edge, *, path: Optional[str] = None, evidence_types: Optional[set] = None) -> Tuple[str, ...]:
        refs: List[str] = []
        normalized_path = _norm_path(path) if path else None
        for edge in edges:
            for evidence in evidence_by_edge.get(edge.edge_id, ()):
                if evidence_types and evidence.evidence_type.upper() not in evidence_types:
                    continue
                if normalized_path:
                    values = [evidence.payload.get("source_file"), evidence.payload.get("changed_file"), evidence.payload.get("file"), evidence.source]
                    if not any(normalized_path in _norm_path(value) for value in values if isinstance(value, str)):
                        continue
                refs.append("trace-evidence:%s" % evidence.evidence_id)
        return tuple(dict.fromkeys(refs))

    def _impact_dimension(self, dimension_id, nodes, verified_edges, evidence_by_edge, *, node_types, relation_types, payload, na_flag, na_evidence, satisfied_reason, required_evidence_types=None):
        relevant_node_ids = {node.node_id for node in nodes if node.node_type in node_types}
        relevant_edges = [edge for edge in verified_edges if edge.relation_type in relation_types and (edge.from_node_id in relevant_node_ids or edge.to_node_id in relevant_node_ids)]
        refs = self._matching_evidence_refs(relevant_edges, evidence_by_edge, evidence_types=required_evidence_types)
        if relevant_edges and refs:
            return DimensionAssessment(dimension_id, DimensionState.SATISFIED, evidence_refs=refs, reason=satisfied_reason)
        if isinstance(payload, Mapping) and payload.get(na_flag) is True:
            ref = _evidence_ref(payload.get(na_evidence))
            if ref:
                return DimensionAssessment(dimension_id, DimensionState.NOT_APPLICABLE, evidence_refs=(ref,), reason="Center-bound trace graph explicitly proves not applicable")
        return DimensionAssessment(dimension_id, DimensionState.UNKNOWN, reason="impact not verified and no evidence-backed N/A declaration exists")

    @staticmethod
    def _explicit_applicability_dimension(dimension_id: str, payload: Mapping[str, object], flag_name: str, evidence_name: str, reason: str) -> DimensionAssessment:
        flag = payload.get(flag_name) if isinstance(payload, Mapping) else None
        ref = _evidence_ref(payload.get(evidence_name)) if isinstance(payload, Mapping) else None
        if flag is False and ref:
            return DimensionAssessment(dimension_id, DimensionState.NOT_APPLICABLE, evidence_refs=(ref,), reason=reason + ": not applicable")
        if flag is True and ref:
            return DimensionAssessment(dimension_id, DimensionState.SATISFIED, evidence_refs=(ref,), reason=reason + ": applicable and assessed")
        return DimensionAssessment(dimension_id, DimensionState.UNKNOWN, reason=reason + " is missing evidence-backed applicability")
