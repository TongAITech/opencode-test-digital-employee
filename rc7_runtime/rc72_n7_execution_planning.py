"""Product-side consumer of canonical N7 admissions and persistent decomposition.

The plan reuses RC7 Task as WorkItem. It creates no worker, Attempt, lease or
execution result; actual signed dispatch owns those identities. Repeating the
same approved inputs resumes the same snapshot, ETUs and Tasks.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, Optional

from rc6_runtime import contracts, truth as registry
from rc6_runtime.truth import TruthRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task
from .rc72_canonical_design import CanonicalDesignService
from .rc72_decomposer import DecompositionSnapshot, PlanningCase
from .rc72_decomposition_truth import PersistentAdaptiveTaskDecomposer
from .rc72_n7_execution_admission import ExecutionAdmissionService, _hash
from .truth_overlay import install_rc7_truth_overlay

_ARTIFACT = 'rc72_n7_execution_plan'
_EVENT = 'RC72_N7_EXECUTION_PLAN_UPSERTED'


class ExecutionPlanningError(ContractError):
    pass


def _validate(payload):
    out = dict(payload)
    for key in ('plan_id', 'release_id', 'source_commit', 'release_batch_id',
                'mission_id', 'snapshot_id', 'input_digest'):
        out[key] = contracts._require_str(out, key)
    if out.get('status') != 'PLANNED' or not isinstance(out.get('items'), list) or not out['items']:
        raise contracts.DomainValidationError('N7_PLAN_ITEMS_REQUIRED')
    keys = {'case_id', 'contract_id', 'admission_id', 'etu_id', 'workitem_id', 'input_artifact_refs'}
    for item in out['items']:
        if not isinstance(item, dict) or set(item) != keys:
            raise contracts.DomainValidationError('N7_PLAN_ITEM_INVALID')
        for key in keys - {'input_artifact_refs'}:
            contracts._require_str(item, key)
        contracts._require_string_list(item, 'input_artifact_refs')
    if len({item['case_id'] for item in out['items']}) != len(out['items']):
        raise contracts.DomainValidationError('N7_PLAN_CASE_DUPLICATE')
    for key in ('actual_result', 'assertion_result', 'data_lease_id', 'field_verified', 'bank_final'):
        if key in out:
            raise contracts.DomainValidationError('N7_PLAN_PREMATURE_CLAIM')
    out.update(artifact_type=_ARTIFACT, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n7_execution_planning_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_ARTIFACT] = _validate
    registry.EVENT_TYPES[_EVENT] = (_ARTIFACT, 'plan_id')
    registry.BUCKETS[_ARTIFACT] = 'rc72_n7_execution_plans'
    registry.IDENTITY_FIELDS[_ARTIFACT] = 'plan_id'


class ExecutionPlanningService:
    def __init__(self, truth: TruthRuntime, *, release_id: str, source_commit: str,
                 now: Optional[datetime] = None, authority=None):
        install_rc72_n7_execution_planning_overlay()
        self.truth, self.release_id, self.source_commit = truth, release_id, source_commit
        self.authority = authority
        self.admission = ExecutionAdmissionService(truth, release_id=release_id, source_commit=source_commit, now=now)

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ExecutionPlanningError('N7_PLAN_TRUTH_NOT_UNIQUE:%s' % kind)
        return rows[0]

    def _planning_case(self, case, contract, obligation):
        values = case.get('execution', {}).get('planning')
        fields = ('primary_code_slice', 'auth_role', 'browser_context', 'data_domain', 'execution_tool')
        if not isinstance(values, dict) or any(not isinstance(values.get(key), str) or not values[key].strip() for key in fields):
            raise ExecutionPlanningError('N7_PLANNING_METADATA_MISSING:N4')
        if values['primary_code_slice'] not in case.get('code_trace', []):
            raise ExecutionPlanningError('N7_PLANNING_CODE_SLICE_OUTSIDE_APPROVED_CASE')
        families = {'L1': {'UNIT'}, 'L2': {'COMPONENT'}, 'L3': {'API'},
                    'L4': {'BROWSER'}, 'L5': {'JOURNEY'}, 'L6': {'PERFORMANCE'}, 'L7': {'SECURITY'}}
        if contract['tool_route'].get('family') not in families.get(case['layer'], set()):
            raise ExecutionPlanningError('N7_TEST_LEVEL_TOOL_FAMILY_UNPROVEN:N1')
        if values['execution_tool'] != contract['tool_route'].get('tool'):
            raise ExecutionPlanningError('N7_PLANNING_TOOL_MISMATCH')
        resources = [self._one('rc72_data_resource', data_ref=ref['data_ref']) for ref in contract['data_refs']]
        if any(row['data_domain'] != values['data_domain'] for row in resources):
            raise ExecutionPlanningError('N7_PLANNING_DATA_DOMAIN_MISMATCH')
        exclusive = any(ref.get('reservation_policy') == 'EXCLUSIVE_WRITE' for ref in contract['data_refs'])
        return PlanningCase(
            case_id=case['tc_id'], release_batch_id=case['release_batch_id'],
            requirement_id=case['requirement_id'], sst_id=case['sst_id'], obligation_id=case['obligation_id'],
            business_scenario=obligation.business_scenario, code_slice=values['primary_code_slice'],
            test_level=case['layer'], data_domain=values['data_domain'], auth_role=values['auth_role'],
            oracle_family='|'.join(sorted(check['type'] for check in case['oracle']['checks'])),
            execution_tool=values['execution_tool'], browser_context=values['browser_context'],
            environment=contract['environment']['name'],
            case_kind='NEGATIVE' if case['action_semantics']['negative'] else 'POSITIVE',
            data_strategy='EXCLUSIVE_MUTABLE' if exclusive else 'SHARED_REFERENCE',
            data_resource_key='|'.join(sorted(ref['data_ref'] for ref in contract['data_refs'])) if exclusive else '',
            requires_isolated_data=exclusive,
        )

    def plan(self, *, release_batch_id: str) -> Dict[str, Any]:
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
                                        source_commit=self.source_commit).load(release_batch_id=release_batch_id)
        mission_id = design.batch['mission_id']
        node = self._one('rc72_mission_node', mission_id=mission_id, node_type='N6_EXECUTABLE_READINESS')
        delivery = next((row for row in self.truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
                         if row['version'] == node.get('active_delivery_version') and row['delivery_id'] in node.get('delivery_refs', [])), None)
        if delivery is None:
            raise ExecutionPlanningError('N7_PLAN_ACTIVE_N6_DELIVERY_REQUIRED')
        contracts_by_case = {}
        inputs = []
        for contract_id in delivery['artifact_refs']:
            checked = self.admission._check(release_batch_id, contract_id)
            contract = self._one('rc72_n6_executable_contract', contract_id=contract_id)
            if contract['case_id'] in contracts_by_case:
                raise ExecutionPlanningError('N7_PLAN_CONTRACT_CASE_DUPLICATE')
            contracts_by_case[contract['case_id']] = contract
            inputs.append(checked)
        if set(contracts_by_case) != {case['tc_id'] for case in design.cases}:
            raise ExecutionPlanningError('N7_PLAN_CASE_DENOMINATOR_MISMATCH')
        obligations = {item.obligation_id: item for item in design.obligations}
        planning_cases = [self._planning_case(case, contracts_by_case[case['tc_id']], obligations[case['obligation_id']])
                          for case in design.cases]
        digest = _hash(dict(inputs=sorted(inputs, key=lambda value: value['case_id']), planning_cases=[asdict(item) for item in planning_cases], config='canonical-n7-v1'))
        plan_id, snapshot_id = 'N7PLAN-' + digest[:24], 'N7SNAP-' + digest[:24]
        recovered = [row for row in self.truth.query(_ARTIFACT, mission_id=mission_id)
                     if row.get('recovery_id') and row['input_digest'] == digest]
        if recovered:
            if len(recovered) != 1:
                raise ExecutionPlanningError('N7_RECOVERY_PLAN_NOT_UNIQUE')
            return self.assert_current(recovered[0]['plan_id'])
        if self.truth.query('rc72_diagnosis_repair', mission_id=mission_id):
            raise ExecutionPlanningError('N7_GOVERNED_REPAIR_RECONCILIATION_REQUIRED')
        current = self.truth.query(_ARTIFACT, plan_id=plan_id)
        if current:
            return self.assert_current(plan_id)
        snapshots = self.truth.query('rc72_decomposition_snapshot', snapshot_id=snapshot_id)
        if snapshots:
            snapshot = snapshots[0]
            if (len(snapshots) != 1 or snapshot.get('planning_cases') != [asdict(item) for item in planning_cases]
                    or snapshot.get('current_node') != 'N7_EXECUTION' or snapshot.get('mission_id') != mission_id):
                raise ExecutionPlanningError('N7_PLAN_SNAPSHOT_REPLAY_CONFLICT')
            etu_ids = snapshot['etu_ids']
        else:
            result = PersistentAdaptiveTaskDecomposer(self.truth, release_id=self.release_id).plan_and_persist(
                DecompositionSnapshot(snapshot_id=snapshot_id, mission_id=mission_id,
                                      release_batch_id=release_batch_id, current_node='N7_EXECUTION',
                                      obligations=design.obligations, cases=planning_cases, config_version='canonical-n7-v1'))
            etu_ids = [item.etu_id for item in result.etus]
        etu_for_case = {}
        for etu_id in etu_ids:
            etu = self._one('rc72_etu', etu_id=etu_id)
            for case_id in etu['case_ids']:
                if case_id in etu_for_case:
                    raise ExecutionPlanningError('N7_PLAN_CASE_IN_MULTIPLE_ETUS')
                etu_for_case[case_id] = etu_id
        if set(etu_for_case) != set(contracts_by_case):
            raise ExecutionPlanningError('N7_PLAN_ETU_DENOMINATOR_MISMATCH')
        control = ClosedLoopControlPlane(self.truth, self.release_id, mission_id)
        items = []
        for index, case in enumerate(design.cases):
            contract = contracts_by_case[case['tc_id']]
            receipt = self.admission.admit(release_batch_id=release_batch_id, contract_id=contract['contract_id'])
            task_id = 'N7WI-' + _hash([plan_id, case['tc_id']])[:24]
            refs = [case['source_artifact_id']]
            row = self.truth.query('rc7_task', task_id=task_id)
            if row:
                if (len(row) != 1 or row[0].get('mission_id') != mission_id
                        or row[0].get('task_type') != 'RC72_CASE_EXECUTION'
                        or row[0].get('input_artifact_refs') != refs):
                    raise ExecutionPlanningError('N7_PLAN_TASK_REPLAY_CONFLICT')
            else:
                control.register_task(Task(task_id=task_id, mission_id=mission_id, node='EXECUTION',
                    task_type='RC72_CASE_EXECUTION', objective='Execute approved Case ' + case['tc_id'],
                    required_capabilities=[item['name'] for item in contract['capabilities']],
                    input_artifact_refs=refs, acceptance_criteria=['Defined assertions and canonical Evidence; no upstream mutation'],
                    priority=100 + index))
            items.append(dict(case_id=case['tc_id'], contract_id=contract['contract_id'],
                              admission_id=receipt['admission_id'], etu_id=etu_for_case[case['tc_id']],
                              workitem_id=task_id, input_artifact_refs=refs))
        payload = dict(plan_id=plan_id, release_id=self.release_id, source_commit=self.source_commit,
                       release_batch_id=release_batch_id, mission_id=mission_id, snapshot_id=snapshot_id,
                       input_digest=digest, status='PLANNED', items=items, artifact_version=1)
        self.truth.append_atomic(_EVENT, payload)
        return self.assert_current(plan_id)

    def assert_current(self, plan_id: str) -> Dict[str, Any]:
        plan = self._one(_ARTIFACT, plan_id=plan_id)
        if plan.get('source_commit') != self.source_commit or plan.get('release_id') != self.release_id:
            raise ExecutionPlanningError('N7_PLAN_SOURCE_MISMATCH')
        recovery = None
        if plan.get('recovery_id'):
            from .rc72_n8_retry_truth import assert_reconciled_plan
            recovery = assert_reconciled_plan(self, plan)
        design = CanonicalDesignService(self.truth, release_id=self.release_id,
                                        source_commit=self.source_commit).load(release_batch_id=plan['release_batch_id'])
        source_cases = {case['tc_id']: case for case in design.cases}
        obligations = {item.obligation_id: item for item in design.obligations}
        if {item['case_id'] for item in plan['items']} != set(source_cases):
            raise ExecutionPlanningError('N7_PLAN_CASE_DENOMINATOR_MISMATCH')
        snapshot = self._one('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id'])
        current_inputs, current_cases = [], []
        for item in plan['items']:
            admission = self.admission.assert_current(item['admission_id'])
            current_inputs.append(self.admission._check(plan['release_batch_id'], item['contract_id']))
            task = self._one('rc7_task', task_id=item['workitem_id'])
            etu = self._one('rc72_etu', etu_id=item['etu_id'])
            contract = self._one('rc72_n6_executable_contract', contract_id=item['contract_id'])
            case = source_cases[item['case_id']]
            planned = asdict(self._planning_case(case, contract, obligations[case['obligation_id']]))
            current_cases.append(planned)
            if (admission['contract_id'] != item['contract_id'] or admission['case_id'] != item['case_id']
                    or task.get('mission_id') != plan['mission_id'] or task.get('release_id') != self.release_id
                    or task.get('node') != 'EXECUTION' or task.get('task_type') != 'RC72_CASE_EXECUTION'
                    or task.get('required_capabilities') != [value['name'] for value in contract['capabilities']]
                    or task.get('input_artifact_refs') != item['input_artifact_refs']
                    or item['input_artifact_refs'] != [case['source_artifact_id']]
                    or etu.get('mission_id') != plan['mission_id'] or etu.get('planning_snapshot_ref') != plan['snapshot_id']
                    or etu.get('obligation_id') != admission['obligation_id'] or etu.get('test_level') != planned['test_level']
                    or etu.get('primary_tool_family') != planned['execution_tool'] or etu.get('data_domain') != planned['data_domain']
                    or etu.get('primary_code_slice') != planned['code_slice']
                    or etu.get('state') in {'STALE', 'MERGED', 'BLOCKED', 'SPLIT_REQUIRED', 'NEEDS_REVISION'}
                    or item['case_id'] not in etu.get('case_ids', [])):
                raise ExecutionPlanningError('N7_PLAN_LINEAGE_MISMATCH')
        current_cases.sort(key=lambda value: value['case_id'])
        digest = _hash(dict(inputs=sorted(current_inputs, key=lambda value: value['case_id']),
                            planning_cases=current_cases, config='canonical-n7-v1'))
        if (plan['input_digest'] != digest
                or (recovery is None and (plan['plan_id'] != 'N7PLAN-' + digest[:24]
                                          or plan['snapshot_id'] != 'N7SNAP-' + digest[:24]))
                or snapshot.get('planning_cases') != current_cases or snapshot.get('current_node') != 'N7_EXECUTION'
                or snapshot.get('mission_id') != plan['mission_id']):
            raise ExecutionPlanningError('N7_PLAN_SNAPSHOT_STALE')
        return plan


install_rc72_n7_execution_planning_overlay()
