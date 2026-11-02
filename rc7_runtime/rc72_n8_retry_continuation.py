"""Accepted exact-data repair -> native N6 -> original ETU/WorkItem retry.

Only unchanged approved Cases/planning semantics may reuse decomposition
identities. A signed durable reconciliation records all restoration targets and
binds the new admissions. It cannot execute tools or manufacture a Case PASS.
"""
from dataclasses import asdict

from .models import ContractError, TaskStatus
from .state_machine import transition_task
from .rc72_domain import AutonomousMissionNode, ETUState, MissionNodeState, ObligationStatus
from .rc72_linkage import NodeTransition, NodeTransitionKind
from .rc72_canonical_design import CanonicalDesignService
from .rc72_canonical_executable import CanonicalExecutableService
from .rc72_decomposer import AdaptiveTaskDecomposer, DecompositionSnapshot, PlanningCase
from .rc72_n7_execution_admission import _hash
from .rc72_n8_execution_diagnosis import ExecutionDiagnosisService
from .rc72_n8_repair_boundary import RepairBoundaryService
from .rc72_n8_retry_truth import _KIND, _EVENT, _PURPOSE, verify_record, install_rc72_n8_retry_truth_overlay


def _same_semantics(current, expected, *, state_key='state'):
    ignored = {'artifact_type', 'artifact_version', 'created_at', 'updated_at', state_key}
    return all(current.get(key) == value for key, value in expected.items() if key not in ignored)


class DataRepairContinuationService:
    def __init__(self, diagnosis):
        install_rc72_n8_retry_truth_overlay()
        if not isinstance(diagnosis, ExecutionDiagnosisService):
            raise ContractError('N8_RETRY_NATIVE_DIAGNOSIS_REQUIRED')
        self.diagnosis, self.preparation, self.truth = diagnosis, diagnosis.preparation, diagnosis.truth
        self.authority, self.runtime = self.preparation.authority, diagnosis.runtime
        self.planning = self.preparation.planning
        self.boundary = RepairBoundaryService(diagnosis, cleanup_adapters={})

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _persist(self, row, **changes):
        signed = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        signed.update(changes)
        self.truth.append_atomic(_EVENT, dict(signed, signature=self.authority._sign(signed),
                                             artifact_version=int(row.get('artifact_version', 0)) + 1))
        return verify_record(self.authority, self._one(_KIND, reconciliation_id=row['reconciliation_id']))

    def _n5(self, p):
        node, delivery, gate = self.planning.admission._active_pass(
            p['mission_id'], p['release_batch_id'], AutonomousMissionNode.N5_TEST_DATA)
        return dict(node=node, delivery=delivery, gate=gate)

    def _source(self, p):
        design = CanonicalDesignService(self.truth, release_id=p['release_id'], source_commit=p['source_commit']).load(
            release_batch_id=p['release_batch_id'])
        admission = self._one('rc72_n7_execution_admission', admission_id=p['admission_id'])
        required = {'N1_REALITY', 'N2_REQUIREMENT', 'N3_CODE_ANALYSIS', 'N4_TEST_DESIGN'}
        parents = [parent for parent in admission['upstream_refs'] if parent['node_type'] in required]
        if len(parents) != 4 or {parent['node_type'] for parent in parents} != required:
            raise ContractError('N8_RETRY_UPSTREAM_LINEAGE_INCOMPLETE')
        for parent in parents:
            node, delivery, gate = self.planning.admission._active_pass(
                p['mission_id'], p['release_batch_id'], AutonomousMissionNode(parent['node_type']))
            if _hash([node, delivery, gate]) != parent['digest']:
                raise ContractError('N8_RETRY_UPSTREAM_SEMANTIC_REPAIR_REQUIRED')
        return design

    def _drained(self, p, plan):
        for prepared in self.truth.query('rc72_n7_execution_preparation', mission_id=p['mission_id']):
            if prepared['status'] == 'PREPARED':
                raise ContractError('N8_RETRY_OTHER_EXECUTION_MUST_DRAIN')
        refs = {ref['data_ref'] for item in plan['items'] for ref in
                self._one('rc72_n6_executable_contract', contract_id=item['contract_id'])['data_refs']}
        if any(lease['state'] in {'ACTIVE', 'EXPIRED'} and (lease['mission_id'] == p['mission_id'] or lease['data_ref'] in refs)
               for lease in self.truth.query('rc72_data_lease')):
            raise ContractError('N8_RETRY_RESOURCE_OWNER_MUST_DRAIN')
        if any(lease['state'] in {'ACTIVE', 'EXPIRED'} for lease in self.truth.query('rc72_browser_lease', mission_id=p['mission_id'])):
            raise ContractError('N8_RETRY_RESOURCE_OWNER_MUST_DRAIN')

    def _original_plan(self, p, old, snapshot):
        if old.get('recovery_id'):
            from .rc72_n8_retry_truth import assert_reconciled_plan
            assert_reconciled_plan(self.planning, old)
            return
        inputs = []
        for item in old['items']:
            receipt = self._one('rc72_n7_execution_admission', admission_id=item['admission_id'])
            payload = {key: value for key, value in receipt.items()
                       if key not in {'admission_id', 'status', 'artifact_type', 'artifact_version'}}
            if (receipt['admission_id'] != 'N7ADM-' + _hash(payload)[:24]
                    or receipt['case_id'] != item['case_id'] or receipt['contract_id'] != item['contract_id']
                    or receipt['mission_id'] != p['mission_id'] or receipt['release_batch_id'] != p['release_batch_id']
                    or item['workitem_id'] != 'N7WI-' + _hash([old['plan_id'], item['case_id']])[:24]):
                raise ContractError('N8_RETRY_ORIGINAL_ADMISSION_OR_WORKITEM_CHANGED')
            inputs.append(payload)
        digest = _hash(dict(inputs=sorted(inputs, key=lambda value: value['case_id']),
                            planning_cases=snapshot['planning_cases'], config='canonical-n7-v1'))
        if (old['input_digest'] != digest or old['plan_id'] != 'N7PLAN-' + digest[:24]
                or old['snapshot_id'] != 'N7SNAP-' + digest[:24]):
            raise ContractError('N8_RETRY_ORIGINAL_PLAN_IDENTITY_CHANGED')
        matches = [item for item in old['items'] if item['workitem_id'] == p['workitem_id']]
        if len(matches) != 1 or any(matches[0][key] != p[key]
                                   for key in ('case_id', 'etu_id', 'contract_id', 'admission_id')):
            raise ContractError('N8_RETRY_ORIGINAL_PREPARATION_CHANGED')

    def _begin(self, preparation_id):
        p, _ = self.diagnosis._facts(preparation_id)
        if p['status'] != 'INTERRUPTED':
            raise ContractError('N8_RETRY_ORIGINAL_EXECUTION_NOT_SUSPENDED')
        grant = self.boundary._signed(self._one('rc72_n8_repair_boundary', preparation_id=preparation_id))
        if grant['state'] != 'REPAIR_OPEN':
            raise ContractError('N8_RETRY_VERIFIED_COMPENSATION_REQUIRED')
        self.boundary._audit_completed(grant)
        case = self._one('rc72_diagnosis_case', source_binding_id=p['binding_id'])
        repair = self._one('rc72_diagnosis_repair', diagnosis_id=case['diagnosis_id'])
        self.diagnosis.record_accepted_repair(preparation_id, repair_delivery_id=repair['repair_delivery_id'],
            changed_refs=repair['changed_refs'], reason=repair['reason'])
        impact = self._one('rc72_impact_set', impact_set_id=repair['impact_set_id'])
        applications = self.truth.query('rc72_impact_application')
        if not any(item['impact']['impact_set_id'] == impact['impact_set_id'] and item['state'] == 'APPLIED'
                   for item in applications):
            raise ContractError('N8_RETRY_APPLIED_REPAIR_IMPACT_REQUIRED')
        old = self._one('rc72_n7_execution_plan', plan_id=p['plan_id'])
        snapshot = self._one('rc72_decomposition_snapshot', snapshot_id=old['snapshot_id'])
        self._original_plan(p, old, snapshot)
        design = self._source(p)
        self._drained(p, old)
        if (old['release_id'] != p['release_id'] or old['source_commit'] != p['source_commit']
                or old['mission_id'] != p['mission_id'] or old['release_batch_id'] != p['release_batch_id']
                or snapshot['current_node'] != 'N7_EXECUTION' or snapshot['config_version'] != 'canonical-n7-v1'):
            raise ContractError('N8_RETRY_ORIGINAL_PLAN_SCOPE_CHANGED')
        source_cases = {case['tc_id']: case for case in design.cases}
        if set(source_cases) != {item['case_id'] for item in old['items']}:
            raise ContractError('N8_RETRY_CASE_DENOMINATOR_CHANGED')
        obligations = {item.obligation_id: item for item in design.obligations}
        planned, members = [], []
        for item in old['items']:
            case = source_cases[item['case_id']]
            contract = self._one('rc72_n6_executable_contract', contract_id=item['contract_id'])
            if case['source_case_sha256'] not in contract['authoritative_sources']:
                raise ContractError('N8_RETRY_APPROVED_CASE_CHANGED')
            planned.append(self.planning._planning_case(case, contract, obligations[case['obligation_id']]))
            candidates = self.truth.query('rc72_n7_execution_preparation', plan_id=old['plan_id'],
                                          workitem_id=item['workitem_id'], status='DRAINED')
            member = None
            if candidates:
                if len(candidates) != 1 or item['workitem_id'] == p['workitem_id']:
                    raise ContractError('N8_RETRY_MEMBER_CHECKPOINT_NOT_UNIQUE')
                from .rc72_n7_member_drain import assert_drained_member
                member = assert_drained_member(self.preparation, candidates[0]['preparation_id'])
                members.append(member)
            task = self._one('rc7_task', task_id=item['workitem_id'])
            if (task['mission_id'] != p['mission_id'] or task['node'] != 'EXECUTION'
                    or task['task_type'] != 'RC72_CASE_EXECUTION'
                    or task['input_artifact_refs'] != [case['source_artifact_id']]
                    or task['required_capabilities'] != [cap['name'] for cap in contract['capabilities']]
                    or task['state'] != ('RUNNING' if member else 'STALE' if item['workitem_id'] == p['workitem_id'] else 'READY')):
                raise ContractError('N8_RETRY_WORKITEM_RECONCILIATION_REQUIRED')
            if member is None and item['workitem_id'] != p['workitem_id'] and self.truth.query(
                    'rc72_workitem_attempt_binding', workitem_id=item['workitem_id']):
                raise ContractError('N8_RETRY_COMPLETED_MEMBERS_REQUIRE_RECONCILIATION')
        if [asdict(case) for case in planned] != snapshot['planning_cases']:
            raise ContractError('N8_RETRY_PLANNING_SEMANTICS_CHANGED')
        decomposition = AdaptiveTaskDecomposer().decompose(DecompositionSnapshot(
            snapshot_id=snapshot['snapshot_id'], mission_id=p['mission_id'], release_batch_id=p['release_batch_id'],
            current_node='N7_EXECUTION', obligations=design.obligations, cases=planned, config_version='canonical-n7-v1'))
        decisions = dict(
            obligation_ids=[item.obligation_id for item in design.obligations],
            case_ids=[item.case_id for item in planned], coverage_gaps=[], completed_case_ids=[],
            execution_history=[], planning_signals=[],
            priority_weights=dict(AdaptiveTaskDecomposer().config.priority_weights),
            priority_explanations={key: dict(value) for key, value in decomposition.priority_explanations.items()},
            obligation_priorities=dict(decomposition.obligation_priorities),
            coverage_routes=[asdict(item) for item in decomposition.coverage_routes],
            replan_reasons={key: list(value) for key, value in decomposition.replan_reasons.items()})
        if any(snapshot.get(key) != value for key, value in decisions.items()):
            raise ContractError('N8_RETRY_ORIGINAL_DECOMPOSITION_DECISIONS_CHANGED')
        expected_etus = {item.etu_id: item for item in decomposition.etus}
        if set(expected_etus) != set(snapshot['etu_ids']) or set(expected_etus) != {item['etu_id'] for item in old['items']}:
            raise ContractError('N8_RETRY_ORIGINAL_DECOMPOSITION_CHANGED')
        for item in old['items']:
            if item['case_id'] not in expected_etus[item['etu_id']].case_ids:
                raise ContractError('N8_RETRY_ORIGINAL_CASE_ETU_MAPPING_CHANGED')
        targets = []
        for obligation in design.obligations:
            current = self._one('rc72_test_obligation', obligation_id=obligation.obligation_id)
            if not _same_semantics(current, asdict(obligation), state_key='status'):
                raise ContractError('N8_RETRY_OBLIGATION_SEMANTICS_CHANGED')
            if current['status'] == 'STALE':
                if obligation.obligation_id not in impact['stale_obligation_ids']:
                    raise ContractError('N8_RETRY_UNRELATED_STALE_OBLIGATION')
                targets.append(dict(kind='rc72_test_obligation', key='obligation_id', original=current))
        for etu_id, expected in expected_etus.items():
            current = self._one('rc72_etu', etu_id=etu_id)
            if not _same_semantics(current, asdict(expected)):
                raise ContractError('N8_RETRY_ETU_SEMANTICS_CHANGED')
            if current['state'] == 'STALE':
                if etu_id not in impact['stale_etu_ids']:
                    raise ContractError('N8_RETRY_UNRELATED_STALE_ETU')
                targets.append(dict(kind='rc72_etu', key='etu_id', original=current))
            elif current['state'] not in {'REGISTERED', 'READY'}:
                raise ContractError('N8_RETRY_ETU_RECONCILIATION_REQUIRED')
        original_binding = self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
        if original_binding['state'] != 'SUPERSEDED':
            raise ContractError('N8_RETRY_ORIGINAL_BINDING_NOT_SUPERSEDED')
        targets.append(dict(kind='rc7_task', key='task_id',
                            original=self._one('rc7_task', task_id=p['workitem_id'])))
        n6 = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N6_EXECUTABLE_READINESS)
        n7 = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N7_EXECUTION)
        for node in (n6, n7):
            previous = grant['original_nodes'][node['node_type']]
            if node['delivery_refs'] != previous['delivery_refs'] or node['gate_refs'] != previous['gate_refs']:
                raise ContractError('N8_RETRY_NEWER_DOWNSTREAM_SCOPE_CHANGED')
        if n6['state'] != 'STALE' or n7['state'] != 'NOT_STARTED':
            raise ContractError('N8_RETRY_DOWNSTREAM_RECONCILIATION_REQUIRED')
        return self._persist(dict(reconciliation_id='N8RECON-' + _hash([preparation_id, repair['impact_set_id']])[:24],
            purpose=_PURPOSE, release_id=p['release_id'], source_commit=p['source_commit'], mission_id=p['mission_id'],
            release_batch_id=p['release_batch_id'], preparation_id=preparation_id, original_preparation=p,
            original_plan=old, original_snapshot=snapshot, original_binding=original_binding, members=members,
            repair_record=repair, impact_record=impact, boundary_record=grant, n5_context=self._n5(p), targets=targets, n6_before=n6, n7_before=n7, state='PLANNED'))

    def _pending_target(self, target):
        original, kind, key = target['original'], target['kind'], target['key']
        current = self._one(kind, **{key: original[key]})
        state_key = 'status' if kind == 'rc72_test_obligation' else 'state'
        if current == original:
            return current
        ignored = {'artifact_version', 'updated_at', state_key}
        if (current['artifact_version'] != original['artifact_version'] + 1 or current[state_key] != 'READY'
                or {k: v for k, v in current.items() if k not in ignored}
                != {k: v for k, v in original.items() if k not in ignored}):
            raise ContractError('N8_RETRY_RESTORATION_TARGET_CHANGED:' + original[key])
        return None

    def _restore(self, row):
        # Preflight the entire frozen target set before any resumed mutation.
        pending = [(target['kind'], self._pending_target(target)) for target in row['targets']]
        for kind, current in pending:
            if current is None:
                continue
            if kind == 'rc72_test_obligation':
                self.runtime._persist_obligation_status(current, ObligationStatus.READY)
            elif kind == 'rc72_etu':
                self.runtime._persist_etu_state(current, ETUState.READY)
            else:
                from .closed_loop_control import ClosedLoopControlPlane
                control = ClosedLoopControlPlane(self.truth, row['release_id'], row['mission_id'])
                task = control.scheduler.task(current['task_id'])
                transition_task(task, TaskStatus.READY)
                control.scheduler._persist_task(task, current['artifact_version'] + 1)

    def _assert_live(self, row):
        p = row['original_preparation']
        self._source(p)
        boundary = self.boundary._signed(self._one('rc72_n8_repair_boundary', preparation_id=p['preparation_id']))
        if boundary != row['boundary_record']:
            raise ContractError('N8_RETRY_REPAIR_BOUNDARY_CHANGED')
        self.boundary._audit_completed(boundary)
        if (self._one('rc72_n7_execution_preparation', preparation_id=p['preparation_id']) != p
                or self._one('rc72_n7_execution_plan', plan_id=p['plan_id']) != row['original_plan']
                or self._one('rc72_decomposition_snapshot', snapshot_id=row['original_snapshot']['snapshot_id']) != row['original_snapshot']
                or self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id']) != row['original_binding']
                or self._one('rc72_diagnosis_repair', diagnosis_id=row['repair_record']['diagnosis_id']) != row['repair_record']
                or self._n5(p) != row['n5_context']):
            raise ContractError('N8_RETRY_RECONCILIATION_SOURCE_CHANGED')
        repair = row['repair_record']
        self.diagnosis.record_accepted_repair(p['preparation_id'], repair_delivery_id=repair['repair_delivery_id'],
            changed_refs=repair['changed_refs'], reason=repair['reason'])
        self._drained(p, row['original_plan'])
        for member in row.get('members', []) if row['state'] == 'PLANNED' else []:
            from .rc72_n7_member_drain import assert_drained_member
            if assert_drained_member(self.preparation, member['preparation_id']) != member:
                raise ContractError('N8_RETRY_MEMBER_CHECKPOINT_CHANGED')

    def _compile(self, row):
        p = row['original_preparation']
        n6 = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N6_EXECUTABLE_READINESS)
        if n6['state'] == 'STALE':
            self.runtime.transition_state(n6['mission_node_id'], MissionNodeState.READY,
                reason='accepted unchanged-Case data repair ' + row['repair_record']['repair_delivery_id'])
        transition_id = 'NT-REPAIR-RESUME-' + _hash(row['reconciliation_id'])[:24]
        if not self.truth.query('rc72_node_transition', transition_id=transition_id):
            self.runtime.repository.persist(NodeTransition(transition_id=transition_id, mission_id=p['mission_id'],
                from_mission_node_id=row['n5_context']['node']['mission_node_id'],
                from_node_type=AutonomousMissionNode.N5_TEST_DATA, to_mission_node_id=n6['mission_node_id'],
                to_node_type=AutonomousMissionNode.N6_EXECUTABLE_READINESS, kind=NodeTransitionKind.RESUME,
                reason='accepted data repair reopens native N6 compilation', source_gate_id=row['n5_context']['gate']['gate_id'],
                evidence_refs=row['n5_context']['gate']['evidence_refs']))
        return CanonicalExecutableService(self.truth, release_id=p['release_id'], source_commit=p['source_commit'],
            now=self.planning.admission.now).compile_batch(release_batch_id=p['release_batch_id'])

    def _new_plan(self, row):
        p, old = row['original_preparation'], row['original_plan']
        design = self._source(p)
        _, delivery, _ = self.planning.admission._active_pass(
            p['mission_id'], p['release_batch_id'], AutonomousMissionNode.N6_EXECUTABLE_READINESS)
        contracts = {item['case_id']: item for item in
                     [self._one('rc72_n6_executable_contract', contract_id=value) for value in delivery['artifact_refs']]}
        obligations = {item.obligation_id: item for item in design.obligations}
        if set(contracts) != {item['case_id'] for item in old['items']}:
            raise ContractError('N8_RETRY_CURRENT_CONTRACT_DENOMINATOR_CHANGED')
        cases = [self.planning._planning_case(case, contracts[case['tc_id']], obligations[case['obligation_id']])
                 for case in design.cases]
        if [asdict(case) for case in cases] != row['original_snapshot']['planning_cases']:
            raise ContractError('N8_RETRY_NEW_PLANNING_SEMANTICS_CHANGED')
        inputs, items = [], []
        for item in old['items']:
            contract = contracts[item['case_id']]
            inputs.append(self.planning.admission._check(p['release_batch_id'], contract['contract_id']))
            admitted = self.planning.admission.admit(release_batch_id=p['release_batch_id'], contract_id=contract['contract_id'])
            items.append(dict(item, contract_id=contract['contract_id'], admission_id=admitted['admission_id']))
        digest = _hash(dict(inputs=sorted(inputs, key=lambda value: value['case_id']),
                            planning_cases=[asdict(case) for case in cases], config='canonical-n7-v1'))
        return dict(plan_id='N7REPLAN-' + _hash([row['reconciliation_id'], digest])[:24],
            release_id=p['release_id'], source_commit=p['source_commit'], release_batch_id=p['release_batch_id'],
            mission_id=p['mission_id'], snapshot_id=old['snapshot_id'], input_digest=digest, status='PLANNED',
            items=items, recovery_id=row['reconciliation_id'], artifact_version=1)

    def reconcile(self, preparation_id):
        prior = self.truth.query(_KIND, preparation_id=preparation_id)
        if prior:
            if len(prior) != 1:
                raise ContractError('N8_RETRY_RECONCILIATION_NOT_UNIQUE')
            row = verify_record(self.authority, prior[0])
            if row['state'] == 'READY' and self.truth.query('rc72_n7_execution_plan', plan_id=row['plan']['plan_id']):
                return self.planning.assert_current(row['plan']['plan_id'])
        else:
            row = self._begin(preparation_id)
        self._assert_live(row)
        self._restore(row)
        self._compile(row)
        plan = self._new_plan(row)
        if row['state'] == 'READY':
            if plan != row['plan']:
                raise ContractError('N8_RETRY_PLAN_REPLAY_CONFLICT')
        else:
            from .rc72_n8_member_reuse import member_reuse_decisions
            decisions = member_reuse_decisions(self.planning, row, plan)
            row = self._persist(row, state='READY', plan=plan, member_decisions=decisions)
        from .rc72_n8_member_disposition import apply_member_dispositions
        apply_member_dispositions(self.preparation, row)
        self.truth.append_atomic('RC72_N7_EXECUTION_PLAN_UPSERTED', plan)
        return self.planning.assert_current(plan['plan_id'])

    def prepare_replacement(self, preparation_id):
        plan = self.reconcile(preparation_id)
        original = self._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
        prepared = self.preparation.prepare(plan_id=plan['plan_id'], workitem_id=original['workitem_id'])
        case = self._one('rc72_diagnosis_case', source_binding_id=original['binding_id'])
        self.diagnosis.orchestrator.record_replacement_attempt(diagnosis_id=case['diagnosis_id'],
                                                              replacement_binding_id=prepared['binding_id'])
        return prepared
