"""Bridge approved N4 candidates to canonical obligations and readable Cases.

Only an active PASS delivery with hash-verified candidate bytes is accepted.
No agent prose, fixture fact flags or coverage gaps can create an obligation.
This service supplies the exact approved assets to N6/planning consumers.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from rc6_runtime.truth import TruthRuntime
from .candidate_payload import CandidatePayloadReader
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, TestObligation
from .rc72_n5_data_inventory import N5DataRequirementInventoryService, _canonical_sha256
from .rc72_repository import CanonicalRC72Repository


class CanonicalDesignError(ContractError):
    pass


@dataclass(frozen=True)
class ApprovedDesign:
    batch: Dict[str, Any]
    delivery: Dict[str, Any]
    gate: Dict[str, Any]
    obligations: List[TestObligation]
    cases: List[Dict[str, Any]]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalDesignError('N4_CANONICAL_%s_REQUIRED' % name.upper())
    return value.strip()


class CanonicalDesignService:
    def __init__(self, truth: TruthRuntime, *, release_id: str, source_commit: str):
        self.truth = truth
        self.release_id = _text(release_id, 'release_id')
        self.source_commit = _text(source_commit, 'source_commit')
        self.inventory = N5DataRequirementInventoryService(truth, source_commit=source_commit)
        self.repository = CanonicalRC72Repository(truth, release_id=release_id)

    def _one(self, kind: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise CanonicalDesignError('N4_CANONICAL_TRUTH_NOT_UNIQUE:%s' % kind)
        return rows[0]

    def load(self, *, release_batch_id: str) -> ApprovedDesign:
        batch = self._one('rc72_release_batch', release_batch_id=release_batch_id)
        if batch.get('release_id') != self.release_id:
            raise CanonicalDesignError('N4_CANONICAL_RELEASE_MISMATCH')
        mission_id = str(batch['mission_id'])
        for kind in AutonomousMissionNode.ordered()[:3]:
            self.inventory._active_pass_delivery(mission_id=mission_id, node_type=kind)
        _node, delivery, gate = self.inventory._active_pass_delivery(
            mission_id=mission_id, node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        )
        if delivery.get('known_gaps'):
            raise CanonicalDesignError('N4_CANONICAL_OPEN_GAPS')
        raw_obligations, cases = {}, {}
        for artifact_id in delivery.get('artifact_refs', []):
            artifact = self._one('rc7_artifact', artifact_id=artifact_id)
            task = self._one('rc7_task', task_id=artifact['producer_task_id'])
            evaluation = self._one('rc7_evaluation', evaluation_id=task.get('evaluation_id'))
            if (artifact.get('state') != 'VALID' or artifact.get('artifact_type_name') != 'TEST_DESIGN_CANDIDATE'
                    or task.get('mission_id') != mission_id or task.get('state') != 'PASS'
                    or evaluation.get('mission_id') != mission_id or evaluation.get('result') != 'PASS'
                    or artifact_id not in evaluation.get('artifact_refs', [])):
                raise CanonicalDesignError('N4_CANONICAL_ARTIFACT_NOT_APPROVED')
            durable = CandidatePayloadReader().load(self.truth, artifact_id, expected_mission_id=mission_id)
            if durable.envelope.get('runtime_lineage', {}).get('source_commit') != self.source_commit:
                raise CanonicalDesignError('N4_CANONICAL_SOURCE_MISMATCH')
            semantic = durable.semantic_payload
            if (semantic.get('candidate_kind') != 'TEST_DESIGN_CANDIDATE'
                    or semantic.get('candidate_unknowns') or semantic.get('candidate_gaps')):
                raise CanonicalDesignError('N4_CANONICAL_CANDIDATE_INCOMPLETE')
            for raw in semantic.get('obligations', []):
                oid = _text(raw.get('obligation_id'), 'obligation_id')
                if oid in raw_obligations:
                    raise CanonicalDesignError('N4_CANONICAL_OBLIGATION_DUPLICATE')
                raw_obligations[oid] = (dict(raw), artifact_id, artifact['content_hash'])
            for raw in semantic.get('cases', []):
                cid = _text(raw.get('tc_id'), 'case_id')
                if cid in cases:
                    raise CanonicalDesignError('N4_CANONICAL_CASE_DUPLICATE')
                if raw.get('release_batch_id') != release_batch_id:
                    raise CanonicalDesignError('N4_CANONICAL_CASE_BATCH_MISMATCH')
                case = deepcopy(raw)
                case.update(source_artifact_id=artifact_id, source_artifact_sha256=artifact['content_hash'],
                            source_case_sha256=_canonical_sha256(dict(raw)))
                cases[cid] = case
        if not cases or not raw_obligations:
            raise CanonicalDesignError('N4_CANONICAL_DESIGN_EMPTY')
        obligations = []
        for oid, (raw, artifact_id, artifact_hash) in sorted(raw_obligations.items()):
            members = [case for case in cases.values() if case.get('obligation_id') == oid]
            if not members:
                raise CanonicalDesignError('N4_CANONICAL_OBLIGATION_WITHOUT_CASE')
            requirement_id = _text(raw.get('requirement_id'), 'requirement_id')
            sst_id = _text(raw.get('sst_id'), 'sst_id')
            if any(case.get('requirement_id') != requirement_id or case.get('sst_id') != sst_id
                   or case.get('layer') != raw.get('layer') for case in members):
                raise CanonicalDesignError('N4_CANONICAL_CASE_LINEAGE_MISMATCH')
            apps = set(case.get('application_id') for case in members if case.get('application_id'))
            if raw.get('application_id'):
                apps.add(raw['application_id'])
            if not apps and len(batch.get('application_ids', [])) == 1:
                apps = {batch['application_ids'][0]}
            if len(apps) != 1 or not apps.issubset(set(batch.get('application_ids', []))):
                raise CanonicalDesignError('N4_CANONICAL_APPLICATION_AMBIGUOUS')
            # business_scope is the existing approved N4 candidate field. These
            # aliases copy its exact text; no extra business analysis is invented.
            scope = _text(raw.get('business_scope'), 'business_scope')
            codes = sorted({ref for case in members for ref in case.get('code_trace', [])})
            if not codes:
                raise CanonicalDesignError('N4_CANONICAL_CODE_TRACE_REQUIRED')
            obligation = TestObligation(
                obligation_id=oid, mission_id=mission_id, release_batch_id=release_batch_id,
                requirement_id=requirement_id, sst_id=sst_id, application_id=next(iter(apps)),
                business_scenario=raw.get('business_scenario') or scope,
                business_rule=raw.get('business_rule') or scope,
                risk_level=_text(raw.get('risk'), 'risk'), test_level=_text(raw.get('layer'), 'layer'),
                code_slice_refs=codes,
                change_refs=[_text(raw.get('change_slice'), 'change_slice'),
                             'artifact://' + artifact_id, artifact_hash,
                             'n4-delivery://' + delivery['delivery_id'], 'n4-gate://' + gate['gate_id']],
                oracle_refs=list(raw.get('oracle_types') or []),
            )
            self.repository._validate_lineage(obligation)
            obligations.append(obligation)
        if any(case.get('obligation_id') not in raw_obligations for case in cases.values()):
            raise CanonicalDesignError('N4_CANONICAL_ORPHAN_CASE')
        return ApprovedDesign(batch, delivery, gate, obligations, [cases[key] for key in sorted(cases)])

    def promote_obligations(self, *, release_batch_id: str) -> ApprovedDesign:
        design = self.load(release_batch_id=release_batch_id)
        pending = []
        for entity in design.obligations:
            expected = asdict(entity)
            ignored = {'created_at', 'updated_at', 'status'}
            current = self.truth.query('rc72_test_obligation', obligation_id=entity.obligation_id)
            if len(current) > 1:
                raise CanonicalDesignError('N4_CANONICAL_OBLIGATION_NOT_UNIQUE')
            if current:
                row = current[0]
                if row.get('mission_id') != entity.mission_id or row.get('release_batch_id') != release_batch_id:
                    raise CanonicalDesignError('N4_CANONICAL_OBLIGATION_IDENTITY_COLLISION')
                if all(row.get(key) == value for key, value in expected.items() if key not in ignored):
                    continue
            pending.append((entity, int(current[0]['artifact_version']) + 1 if current else 1))
        for entity, version in pending:
            self.repository.persist(entity, artifact_version=version)
        return design
