"""Native N4 parent-denominator guard; scoped parent identity never collapses.

Use RC7.2's Case/execution contract. Do not substitute the legacy flat Case
contract or let equal source IDs from different repositories erase coverage.
"""
from dataclasses import replace
import hashlib

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_test_design_evaluator import DshTestDesignEvaluator
from .dsh_test_design_oracle_evaluator import DshExecutionReadyTestDesignEvaluator
from .test_design_sufficiency_v2 import TestDesignSufficiencyV2
from .models import ContractError, EvaluationResult, Gap, GapSeverity
from .rc72_n4_parent_truth import install_rc72_n4_parent_inventory_contract
from .rc72_n4_completion import N4DeliveryGateService
from .test_obligation_inventory import ParentDerivedTestObligationInventory


def parent_source_coverage(truth, *, mission_id, parent_refs, obligations):
    install_rc72_n4_parent_inventory_contract()
    sources = ParentDerivedTestObligationInventory().derive(truth, mission_id=mission_id, parent_artifact_refs=parent_refs)
    if not sources:
        raise ContractError('RC72_N4_PARENT_DENOMINATOR_REQUIRED')
    expected = {(s.kind, '%s:%s:%s' % (s.kind, s.source_id, s.parent_artifact_id)) for s in sources}
    represented = set()
    for obligation in obligations if isinstance(obligations, list) else []:
        if isinstance(obligation, dict) and obligation.get('required') is True:
            for ref in obligation.get('source_refs', []):
                represented.add((str(obligation.get('kind', '')).upper(), ref))
    return sources, sorted(ref for kind, ref in expected - represented)


class N4ParentScopedDesignEvaluator(DshTestDesignEvaluator):
    def evaluate(self, control, task_id, artifact_id):
        task = control.scheduler.task(task_id)
        candidate = self.reader.load(control.truth, artifact_id,
            expected_mission_id=control.mission_id, expected_task_id=task_id)
        sources, missing = parent_source_coverage(control.truth, mission_id=control.mission_id,
            parent_refs=task.input_artifact_refs, obligations=candidate.semantic_payload.get('obligations'))
        evaluated = super().evaluate(control, task_id, artifact_id)
        base = DshExecutionReadyTestDesignEvaluator._apply_oracle_guard(control,
            artifact_id=artifact_id, base=evaluated.loop_result,
            reasons=DshExecutionReadyTestDesignEvaluator._oracle_reasons(candidate.semantic_payload.get('cases')))
        sufficiency = TestDesignSufficiencyV2().evaluate(obligations=evaluated.obligations, cases=evaluated.cases)
        base = DshExecutionReadyTestDesignEvaluator._apply_sufficiency_v2_guard(control,
            artifact_id=artifact_id, base=base, result=sufficiency)
        dimensions = dict(base.evaluation.dimensions,
            native_parent_source_total=len(sources), native_parent_source_missing=missing)
        extra = tuple(Gap(gap_id='GAP-N4-PARENT-' + hashlib.sha256((control.mission_id+'|'+artifact_id+'|'+ref).encode()).hexdigest()[:24],
            mission_id=control.mission_id, source_node='TEST_DESIGN', target_node='TEST_DESIGN',
            category='TEST_DESIGN_SOURCE_OBLIGATION_GAP', severity=GapSeverity.HIGH,
            description='Required parent source has no required same-kind obligation: '+ref,
            subject_refs=[artifact_id, ref], evidence_refs=list(base.evaluation.evidence_refs),
            acceptance_criteria=['Represent and cover this exact parent-scoped source, then independently review again']) for ref in missing)
        evaluation = replace(base.evaluation, dimensions=dimensions)
        if missing:
            evaluation = replace(evaluation,
                evaluation_id='EVAL-N4-PARENT-' + hashlib.sha256((base.evaluation.evaluation_id+'|'+ '|'.join(missing)).encode()).hexdigest()[:24],
                result=EvaluationResult.REPAIR_REQUIRED,
                gap_refs=list(dict.fromkeys(list(base.evaluation.gap_refs)+[g.gap_id for g in extra])))
        return replace(evaluated, loop_result=replace(base, evaluation=evaluation, gaps=tuple(base.gaps)+extra))


class N4ParentScopedDeliveryGateService(N4DeliveryGateService):
    def complete(self, *, release_batch_id):
        # The native context revalidates the active N2/N3 lineage and full scope.
        batch, node, next_node, dispatches, scopes, parents = self._context(release_batch_id)
        for dispatch in dispatches:
            task = self._one('rc7_task', task_id=dispatch['workitem_id'])
            if task['state'] != 'PASS':
                continue  # Whole-node gate retains negative members below.
            refs = task.get('output_artifact_refs', [])
            if len(refs) != 1:
                raise ContractError('RC72_N4_PARENT_SCOPED_CANDIDATE_REQUIRED')
            payload = CandidatePayloadReader().load(self.truth, refs[0],
                expected_mission_id=batch['mission_id'], expected_task_id=task['task_id'])
            _, missing = parent_source_coverage(self.truth, mission_id=batch['mission_id'],
                parent_refs=dispatch['parent_artifact_refs'], obligations=payload.semantic_payload.get('obligations'))
            if missing:
                raise ContractError('RC72_N4_PARENT_SOURCE_DENOMINATOR_INCOMPLETE')
            if DshExecutionReadyTestDesignEvaluator._oracle_reasons(payload.semantic_payload.get('cases')):
                raise ContractError('RC72_N4_DETERMINISTIC_ORACLE_REQUIRED')
            control = ClosedLoopControlPlane(self.truth, batch['release_id'], batch['mission_id'])
            artifact = self._one('rc7_artifact', artifact_id=refs[0])
            aliases, _ = DshTestDesignEvaluator._candidate_evidence_aliases(control, artifact)
            obligations = DshTestDesignEvaluator._obligations(payload.semantic_payload.get('obligations'), aliases)
            cases = DshTestDesignEvaluator._cases(payload.semantic_payload.get('cases'), aliases)
            if not TestDesignSufficiencyV2().evaluate(obligations=obligations, cases=cases).passed:
                raise ContractError('RC72_N4_SUFFICIENCY_V2_REQUIRED')
        return super().complete(release_batch_id=release_batch_id)
