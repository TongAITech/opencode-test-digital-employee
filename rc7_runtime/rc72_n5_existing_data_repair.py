"""Governed independent N5 re-verification of an already bound exact DataRef.

No discovery candidate is invented for reuse-only data. Accepted N8 compensation
opens this path; a fresh STRICT DSH verifier must observe the exact binding. The
runtime anchors raw output and uses native binding revision and whole-N5 gates.
"""
from dataclasses import asdict
import hashlib
import hmac
import json
from pathlib import Path

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.authority import TaskLease, WorkerIdentity
from .models import Artifact, ContractError, Evidence, Evaluation, EvaluationResult, Task, TaskStatus
from .closed_loop_control import ClosedLoopControlPlane
from .state_machine import transition_task
from .rc72_authority import DATA_PREPARER, DATA_VERIFIER
from .rc72_canonical_design import CanonicalDesignService
from .rc72_n5_data_verification_anchor import _strict_final_json
from .rc72_n5_data_verification_finalization import N5DataVerificationFinalizationService
from .rc72_n7_execution_admission import _hash
from .rc72_n8_repair_boundary import RepairBoundaryService
from .truth_overlay import append_entity

from .rc72_n5_existing_data_repair_truth import (
    _KIND, _EVENT, _SCHEMA, _FINAL, install_rc72_n5_existing_data_repair_overlay,
)


class ExistingDataRepairService:
    def __init__(self, boundary, *, launcher, allowed_tools):
        install_rc72_n5_existing_data_repair_overlay()
        if not isinstance(boundary, RepairBoundaryService) or not isinstance(launcher, DshHeadlessWorkerLauncher):
            raise ContractError('N5_EXISTING_REPAIR_NATIVE_BOUNDARY_AND_LAUNCHER_REQUIRED')
        self.boundary, self.preparation = boundary, boundary.preparation
        self.truth, self.authority, self.launcher = boundary.truth, boundary.preparation.authority, launcher
        if (launcher.truth is not self.truth or launcher.authority is not self.authority
                or launcher.release_id != self.preparation.release_id):
            raise ContractError('N5_EXISTING_REPAIR_RUNTIME_AUTHORITY_MISMATCH')
        if (not isinstance(allowed_tools, (list, tuple)) or not allowed_tools
                or any(not isinstance(tool, str) or not tool.strip() or '*' in tool for tool in allowed_tools)):
            raise ContractError('N5_EXISTING_REPAIR_SCOPED_TOOLS_REQUIRED')
        self.tools = tuple(sorted(set(allowed_tools)))

    def _finalizer(self, mission_id):
        return N5DataVerificationFinalizationService(self.truth,
            release_id=self.preparation.release_id, mission_id=mission_id,
            source_commit=self.preparation.source_commit, state_root=str(self.launcher.state_root))

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _signed(self, row):
        value = {key: item for key, item in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        if not hmac.compare_digest(row['signature'], self.authority._sign(value)):
            raise ContractError('N5_EXISTING_REPAIR_SIGNATURE_INVALID')
        if row['release_id'] != self.preparation.release_id or row['source_commit'] != self.preparation.source_commit:
            raise ContractError('N5_EXISTING_REPAIR_SOURCE_CHANGED')
        return row

    def _persist(self, row, **changes):
        value = {key: item for key, item in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        value.update(changes)
        version = int(row.get('artifact_version', 0)) + 1
        self.truth.append_atomic(_EVENT, dict(value, signature=self.authority._sign(value), artifact_version=version))
        return self._signed(self._one(_KIND, repair_id=row['repair_id']))

    def _context(self, preparation_id):
        grant = self.boundary._signed(self._one('rc72_n8_repair_boundary', preparation_id=preparation_id))
        if grant['state'] != 'REPAIR_OPEN':
            raise ContractError('N5_EXISTING_REPAIR_COMPENSATION_REQUIRED')
        self.boundary._audit_completed(grant)
        p, c, _ = self.boundary._context(preparation_id, opened=True)
        design = CanonicalDesignService(self.truth, release_id=p['release_id'], source_commit=p['source_commit']).load(
            release_batch_id=p['release_batch_id'])
        source = next((case for case in design.cases if case['tc_id'] == p['case_id']), None)
        if source is None or source['source_case_sha256'] not in c['authoritative_sources']:
            raise ContractError('N5_EXISTING_REPAIR_APPROVED_CASE_CHANGED')

        if p['status'] != 'INTERRUPTED':
            raise ContractError('N5_EXISTING_REPAIR_EXECUTION_NOT_SUSPENDED')
        for kind in ('N6_EXECUTABLE_READINESS', 'N7_EXECUTION'):
            node = self._one('rc72_mission_node', mission_id=p['mission_id'], node_type=kind)
            if node['state'] != 'NOT_STARTED' or node['active_delivery_version'] is not None:
                raise ContractError('N5_EXISTING_REPAIR_DOWNSTREAM_MUST_REMAIN_LOCKED')
        if self._one('rc72_mission_node', mission_id=p['mission_id'], node_type='N5_TEST_DATA')['state'] != 'RUNNING':
            raise ContractError('N5_EXISTING_REPAIR_N5_RUNNING_REQUIRED')
        return p, c, grant

    def _source_contract(self, p, requirement, binding):
        # N5 owns the whole approved inventory, including unexecuted Cases.
        # Every request still has one exact original Case/contract/DataRef scope.
        plan = self._one('rc72_n7_execution_plan', plan_id=p['plan_id'])
        items = [item for item in plan['items'] if item['case_id'] == requirement['case_id']]
        if len(items) != 1:
            raise ContractError('N5_EXISTING_REPAIR_CASE_OUTSIDE_ORIGINAL_PLAN')
        contract = self._one('rc72_n6_executable_contract', contract_id=items[0]['contract_id'])
        from .rc72_n6_completion import _digest, _stable_id
        if (contract['mission_id'] != p['mission_id'] or contract['release_batch_id'] != p['release_batch_id']
                or contract['source_commit'] != p['source_commit'] or contract['case_id'] != requirement['case_id']
                or contract['contract_sha256'] != _digest(contract)
                or contract['contract_id'] != _stable_id('N6CONTRACT', p['mission_id'], requirement['case_id'], contract['contract_sha256'])
                or requirement['source_case_sha256'] not in contract['authoritative_sources']
                or not any(ref['data_ref'] == binding['data_ref'] and ref['data_requirement_id'] == requirement['data_requirement_id']
                           for ref in contract['data_refs'])):
            raise ContractError('N5_EXISTING_REPAIR_EXACT_BINDING_REQUIRED')
        if any(lease['state'] == 'ACTIVE' and lease['data_ref'] == binding['data_ref']
               for lease in self.truth.query('rc72_data_lease')):
            raise ContractError('N5_EXISTING_REPAIR_DATA_OWNER_MUST_DRAIN')
        return contract

    def request(self, preparation_id, *, data_requirement_id, binding_revision):
        if isinstance(binding_revision, bool) or not isinstance(binding_revision, int) or binding_revision < 1:
            raise ContractError('N5_EXISTING_REPAIR_BINDING_REVISION_REQUIRED')
        repair_id = 'N5REPAIR-' + _hash([preparation_id, data_requirement_id, binding_revision])[:24]
        prior = self.truth.query(_KIND, repair_id=repair_id)
        if prior:
            row = self._signed(self._one(_KIND, repair_id=repair_id))
            if tuple(row['allowed_tools']) != self.tools or row['runtime_root'] != str(self.launcher.state_root):
                raise ContractError('N5_EXISTING_REPAIR_TOOL_SCOPE_CHANGED')
            return row
        p, c, grant = self._context(preparation_id)
        requirement = self._finalizer(p['mission_id']).resolution._requirement(data_requirement_id)
        binding = self._one('rc72_n5_data_binding', data_requirement_id=data_requirement_id)
        resource = self._one('rc72_data_resource', data_ref=binding['data_ref'])
        c = self._source_contract(p, requirement, binding)
        expected = dict(release_id=p['release_id'], mission_id=p['mission_id'], release_batch_id=p['release_batch_id'],
                        source_commit=p['source_commit'], data_requirement_id=data_requirement_id)
        if (any(requirement.get(key) != value or binding.get(key) != value for key, value in expected.items())
                or binding['source_case_sha256'] != requirement['source_case_sha256']
                or binding['artifact_version'] != binding_revision
                or binding['data_ref'] not in {item['data_ref'] for item in c['data_refs']}
                or resource['release_id'] != p['release_id'] or resource['verified'] is not True
                or binding['resource_metadata_ref'] != resource['metadata_ref']):
            raise ContractError('N5_EXISTING_REPAIR_EXACT_BINDING_REQUIRED')
        if any(row['state'] not in _FINAL for row in self.truth.query(_KIND, data_requirement_id=data_requirement_id)):
            raise ContractError('N5_EXISTING_REPAIR_PRIOR_REQUEST_UNRESOLVED')
        row = dict(expected, **{key: requirement[key] for key in ('mission_node_id', 'case_id', 'requirement_id',
                'sst_id', 'obligation_id', 'source_case_sha256')},
            repair_id=repair_id, preparation_id=preparation_id, boundary_id=grant['boundary_id'],
            source_contract_id=c['contract_id'], source_contract_sha256=c['contract_sha256'],
            verification_attempt_id='N5RVERIFY-' + _hash(repair_id)[:24],
            workitem_id='WI-N5RVERIFY-' + _hash(repair_id)[:24], workitem_role=DATA_VERIFIER, original_binding=binding,
            requirement=requirement, resource=resource, allowed_tools=list(self.tools), runtime_root=str(self.launcher.state_root), state='REQUESTED')
        row = self._persist(row)
        self._ensure_workitem(row)
        self._suspend(row)
        return row

    def _live(self, row):
        if tuple(row['allowed_tools']) != self.tools or row['runtime_root'] != str(self.launcher.state_root):
            raise ContractError('N5_EXISTING_REPAIR_TOOL_SCOPE_CHANGED')
        p, _, grant = self._context(row['preparation_id'])
        contract = self._source_contract(p, row['requirement'], row['original_binding'])
        if (contract['contract_id'] != row.get('source_contract_id', p['contract_id'])
                or contract['contract_sha256'] != row.get('source_contract_sha256', contract['contract_sha256'])):
            raise ContractError('N5_EXISTING_REPAIR_SOURCE_CONTEXT_CHANGED')
        if grant['boundary_id'] != row['boundary_id']:
            raise ContractError('N5_EXISTING_REPAIR_BOUNDARY_CHANGED')
        if (self._one('rc72_n5_data_requirement', data_requirement_id=row['data_requirement_id']) != row['requirement']
                or self._one('rc72_data_resource', data_ref=row['resource']['data_ref']) != row['resource']):
            raise ContractError('N5_EXISTING_REPAIR_SOURCE_CONTEXT_CHANGED')

    def _suspend(self, row):
        original = row['original_binding']
        current = self._one('rc72_n5_data_binding', binding_id=original['binding_id'])
        if current == original:
            self.truth.append_atomic('RC72_N5_DATA_BINDING_UPSERTED', dict(current,
                verification_blocked_by_anchor=row['repair_id'], artifact_version=current['artifact_version'] + 1))
        elif (current.get('verification_blocked_by_anchor') != row['repair_id']
                or current['artifact_version'] != original['artifact_version'] + 1
                or {k: v for k, v in current.items() if k not in {'verification_blocked_by_anchor', 'artifact_version'}}
                    != {k: v for k, v in original.items() if k not in {'verification_blocked_by_anchor', 'artifact_version'}}):
            if current.get('reverification_anchor_id') != row['repair_id']:
                raise ContractError('N5_EXISTING_REPAIR_BINDING_CHANGED')
        return self._one('rc72_n5_data_binding', binding_id=original['binding_id'])

    def _control(self, row):
        return ClosedLoopControlPlane(self.truth, row['release_id'], row['mission_id'])

    def _ensure_workitem(self, row, *, create=True):
        workitem_id = row['workitem_id']
        if row.get('workitem_role') not in {DATA_PREPARER, DATA_VERIFIER}:
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_ROLE_INVALID')
        kind = {DATA_PREPARER: 'RC72_EXISTING_DATA_REPAIR_PREPARATION',
                DATA_VERIFIER: 'RC72_EXISTING_DATA_REPAIR_VERIFICATION'}[row['workitem_role']]
        source_refs = [row['requirement']['source_n4_artifact_id']]
        tasks = self.truth.query('rc7_task', task_id=workitem_id)
        if not tasks:
            if not create:
                raise ContractError('N5_EXISTING_REPAIR_WORKITEM_MISSING')
            self._control(row).register_task(Task(task_id=workitem_id, mission_id=row['mission_id'],
                node='TEST_DATA', task_type=kind, objective='Repair exact DataRequirement ' + row['data_requirement_id'],
                required_capabilities=['test_data'], input_artifact_refs=source_refs,
                acceptance_criteria=['Exact DataRef and source Case retained; independent verification required']))
        task = self._one('rc7_task', task_id=workitem_id)
        if (task['mission_id'] != row['mission_id'] or task['release_id'] != row['release_id']
                or task['node'] != 'TEST_DATA' or task['task_type'] != kind
                or task['input_artifact_refs'] != source_refs or task['required_capabilities'] != ['test_data']):
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_SCOPE_CHANGED')
        if create and task['state'] == 'REGISTERED':
            self._control(row).scheduler.refresh_ready(row['mission_id'])
            task = self._one('rc7_task', task_id=workitem_id)
        return task

    def _start_workitem(self, row):
        task = self._ensure_workitem(row)
        control = self._control(row)
        if task['state'] != 'READY':
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_NOT_READY')
        if control.scheduler.lease_task(row['mission_id'], row['workitem_id'],
                worker_ref=row['identity']['worker_id'], capabilities=['test_data']) is None:
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_LEASE_DENIED')
        control.start(row['workitem_id'], worker_ref=row['identity']['worker_id'])

    def _output_workitem(self, row, *, failed=False, create=True):
        task_row = self._ensure_workitem(row, create=False)
        artifact_id = 'N5REPAIRART-' + _hash([row['workitem_id'], row['raw_output_sha256']])[:24]
        evidence_id = self._evidence(row, create=create)
        expected = dict(mission_id=row['mission_id'], artifact_type_name='N5_EXISTING_DATA_REPAIR_RAW_PROOF',
            producer_task_id=row['workitem_id'], content_ref=row['raw_output_ref'], content_hash=row['raw_output_sha256'],
            evidence_refs=[evidence_id], parent_refs=[row['data_requirement_id'], row['original_binding']['binding_id']])
        artifacts = self.truth.query('rc7_artifact', artifact_id=artifact_id)
        if artifacts:
            if len(artifacts) != 1 or artifacts[0]['state'] != 'VALID' or any(artifacts[0].get(k) != v for k, v in expected.items()):
                raise ContractError('N5_EXISTING_REPAIR_WORKITEM_OUTPUT_CHANGED')
        elif create:
            append_entity(self.truth, Artifact(artifact_id=artifact_id,
                artifact_type=expected['artifact_type_name'], **{k: v for k, v in expected.items() if k != 'artifact_type_name'}),
                release_id=row['release_id'])
        else:
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_OUTPUT_MISSING')
        if not create:
            if (task_row['output_artifact_refs'] != [artifact_id]
                    or task_row['state'] not in {'OUTPUT_PRODUCED', 'PASS', 'FAILED', 'CANCELLED'}):
                raise ContractError('N5_EXISTING_REPAIR_WORKITEM_RESULT_CONFLICT')
            return artifact_id
        if task_row['state'] == 'RUNNING':
            task = self._control(row).scheduler.task(row['workitem_id'])
            task.output_artifact_refs = [artifact_id]
            transition_task(task, TaskStatus.FAILED if failed else TaskStatus.OUTPUT_PRODUCED)
            if failed:
                task.lease_owner = None
            self._control(row).scheduler._persist_task(task, task_row['artifact_version'] + 1)
        elif task_row['output_artifact_refs'] != [artifact_id] or task_row['state'] not in {'OUTPUT_PRODUCED', 'PASS', 'FAILED', 'CANCELLED'}:
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_RESULT_CONFLICT')
        return artifact_id

    def _accept_workitem(self, row, *, evaluator_ref, audit=False):
        artifact_id = self._output_workitem(row, create=not audit)
        task_row = self._one('rc7_task', task_id=row['workitem_id'])
        evaluation_id = 'N5REPAIREVAL-' + _hash(row['workitem_id'])[:24]
        expected = dict(evaluation_id=evaluation_id, mission_id=row['mission_id'], node='TEST_DATA',
            artifact_refs=[artifact_id], result=EvaluationResult.PASS, evaluator_ref=evaluator_ref,
            dimensions=dict(exact_data_ref=row['original_binding']['data_ref'], raw_proof=row['raw_output_sha256']),
            evidence_refs=[self._evidence(row)])
        current = self.truth.query('rc7_evaluation', evaluation_id=evaluation_id)
        if current and (len(current) != 1 or any(current[0].get(k) != v for k, v in expected.items())):
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_EVALUATION_CHANGED')
        if task_row['state'] == 'PASS':
            if not current or task_row['evaluation_id'] != evaluation_id:
                raise ContractError('N5_EXISTING_REPAIR_WORKITEM_EVALUATION_MISSING')
            return
        if audit or task_row['state'] != 'OUTPUT_PRODUCED' or evaluator_ref == task_row['lease_owner']:
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_REVIEW_INVALID')
        control = self._control(row)
        if current:
            # Resume the native task transition after a durable evaluation.
            task = control.scheduler.task(row['workitem_id'])
            transition_task(task, TaskStatus.EVALUATING)
            transition_task(task, TaskStatus.PASS, evaluation_id=evaluation_id)
            control.scheduler.persist_evaluated_task(task)
        else:
            control.accept_evaluation(row['workitem_id'], evaluation=Evaluation(**expected))

    def _finish_workitems(self, row):
        if row['result']['status'] != 'VERIFIED':
            self._output_workitem(row, failed=True)
            return []
        self._accept_workitem(row, evaluator_ref='runtime://n5-independent-proof-gate/' + row['repair_id'])
        if row.get('producer'):
            producer = self._producer_row(row)
            if producer['result']['status'] == 'PREPARED':
                self._accept_workitem(producer, evaluator_ref=row['identity']['worker_id'])
            else:
                self._cancel_failed_workitem(producer)
        superseded = []
        for prior in self.truth.query(_KIND, data_requirement_id=row['data_requirement_id']):
            if (prior['repair_id'] != row['repair_id'] and prior['preparation_id'] == row['preparation_id']
                    and prior['state'] == 'REPAIR_REQUIRED'):
                prior = self._signed(prior)
                if prior['original_binding']['data_ref'] != row['original_binding']['data_ref']:
                    raise ContractError('N5_EXISTING_REPAIR_PRIOR_DATA_SCOPE_CHANGED')
                self._cancel_failed_workitem(prior)
                if prior.get('producer'):
                    self._cancel_failed_workitem(self._producer_row(prior))
                superseded.append(prior['repair_id'])
        return sorted(superseded)

    def _cancel_failed_workitem(self, row):
        task_row = self._ensure_workitem(row, create=False)
        if task_row['state'] == 'OUTPUT_PRODUCED' and row['identity']['role'] == DATA_PREPARER:
            task = self._control(row).scheduler.task(row['workitem_id'])
            transition_task(task, TaskStatus.STALE)
            self._control(row).scheduler._persist_task(task, task_row['artifact_version'] + 1)
            task_row = self._one('rc7_task', task_id=row['workitem_id'])
        if task_row['state'] in {'FAILED', 'STALE'}:
            task = self._control(row).scheduler.task(row['workitem_id'])
            transition_task(task, TaskStatus.CANCELLED)
            self._control(row).scheduler._persist_task(task, task_row['artifact_version'] + 1)
        elif task_row['state'] not in {'CANCELLED', 'PASS'}:
            raise ContractError('N5_EXISTING_REPAIR_PRIOR_WORKITEM_UNRESOLVED')

    def _prompt(self, row):
        output = dict(schema=_SCHEMA, repair_id=row['repair_id'], data_ref=row['original_binding']['data_ref'],
            binding_revision=row['original_binding']['artifact_version'], source_case_sha256=row['requirement']['source_case_sha256'],
            status='VERIFIED or REPAIR_REQUIRED', verification='independent observation and tool evidence explanation',
            precondition_refs=row['original_binding']['precondition_refs'], unknowns=[], gaps=[])
        return ('You are the independent RC7.2 N5 DATA_VERIFIER for an existing exact DataRef. '
                'Use authorized real tools to observe that resource and every Case precondition again. '
                'Old verification is context only. Do not substitute data or alter strategy, source, cleanup or validity. '
                'Return REPAIR_REQUIRED with reasons when any precondition is unproved. '
                'You have zero canonical artifact-write authority. Emit exactly one final JSON object matching output_contract.\n'
                + json.dumps(dict(repair_id=row['repair_id'], requirement=row['requirement'],
                    existing_binding=row['original_binding'], resource=row['resource'], authorized_tools=row['allowed_tools'],
                    output_contract=output), sort_keys=True, ensure_ascii=False))

    def _proof(self, row, event, *, role=DATA_VERIFIER, phase='DATA_VERIFICATION',
               schema=_SCHEMA, statuses=_FINAL, successful='VERIFIED'):
        identity = WorkerIdentity(**row['identity'])
        lease = dict(row['lease'])
        for key in ('allowed_artifact_types', 'allowed_tools'):
            lease[key] = tuple(lease[key])
        lease = TaskLease(**lease)
        self.authority.validate_historical_lease(identity, lease)
        if (identity.role != role or row['workitem_role'] != role or identity.phase != phase
                or lease.scope_ref != 'task:%s/attempt:%s' % (row['workitem_id'], row['verification_attempt_id']) or lease.allowed_artifact_types
                or lease.allowed_tools != tuple(row['allowed_tools'])
                or event.get('result') != 'PASS' or event.get('exit_code') != 0
                or event.get('worker_instance_id') != identity.worker_id or event.get('lease_id') != lease.lease_id
                or event.get('assignment_id') != row['assignment_id'] or event.get('scope') != lease.scope_ref
                or event.get('attempt_id') != row['verification_attempt_id']
                or event.get('input_refs') != row['input_refs'] or event.get('release_id') != row['release_id']
                or event.get('started_at', 0) < lease.issued_at
                or not event.get('started_at', 0) <= event.get('finished_at', 0) <= lease.expires_at):
            raise ContractError('N5_EXISTING_REPAIR_RUNTIME_PROOF_INVALID')
        task = self._ensure_workitem(row, create=False)
        history = self.truth.projection.history('rc7_task', row['workitem_id'])
        if not any(item['state'] == 'RUNNING' and item.get('lease_owner') == identity.worker_id for item in history):
            raise ContractError('N5_EXISTING_REPAIR_WORKITEM_ATTEMPT_UNBOUND')
        refs = [ref for ref in event.get('evidence_refs', []) if ref.startswith('file://')]
        if len(refs) != 1:
            raise ContractError('N5_EXISTING_REPAIR_RAW_PROOF_REQUIRED')
        path = Path(refs[0][len('file://'):]).resolve()
        try:
            path.relative_to(Path(row['runtime_root']))
        except ValueError as exc:
            raise ContractError('N5_EXISTING_REPAIR_RAW_PROOF_OUTSIDE_RUNTIME') from exc
        try:
            raw = path.read_bytes()
            events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(raw.decode('utf-8')))
        except (OSError, UnicodeDecodeError) as exc:
            raise ContractError('N5_EXISTING_REPAIR_RAW_PROOF_UNREADABLE') from exc
        session = DshHeadlessWorkerLauncher._session_id(events)
        calls = DshHeadlessWorkerLauncher._tool_calls(events)
        if (not session or session != event.get('dsh_session_id') or not calls or calls != event.get('tool_calls')
                or any(call['tool_name'] not in row['allowed_tools'] for call in calls)):
            raise ContractError('N5_EXISTING_REPAIR_RAW_TOOL_OR_SESSION_MISMATCH')
        for prior in self.truth.query('agent_runtime_event'):
            if prior.get('dsh_session_id') == session and prior.get('assignment_id') != row['assignment_id']:
                raise ContractError('N5_EXISTING_REPAIR_VERIFIER_SESSION_REUSED')
        if any(prior['worker_id'] == identity.worker_id or prior['session_id'] == session
               for prior in self.truth.query('rc72_worker_session')):
            raise ContractError('N5_EXISTING_REPAIR_VERIFIER_NOT_INDEPENDENT')
        result = _strict_final_json(events)
        keys = {'schema', 'repair_id', 'data_ref', 'binding_revision', 'source_case_sha256', 'status',
                'verification', 'precondition_refs', 'unknowns', 'gaps'}
        expected = dict(schema=schema, repair_id=row['repair_id'], data_ref=row['original_binding']['data_ref'],
            binding_revision=row['original_binding']['artifact_version'], source_case_sha256=row['requirement']['source_case_sha256'],
            precondition_refs=row['original_binding']['precondition_refs'])
        if set(result) != keys or any(result.get(key) != value for key, value in expected.items()):
            raise ContractError('N5_EXISTING_REPAIR_RESULT_SCOPE_INVALID')
        if result['status'] not in statuses or not isinstance(result['verification'], str) or not result['verification'].strip():
            raise ContractError('N5_EXISTING_REPAIR_RESULT_INVALID')
        for key in ('unknowns', 'gaps'):
            if not isinstance(result[key], list) or any(not isinstance(v, str) or not v.strip() for v in result[key]):
                raise ContractError('N5_EXISTING_REPAIR_RESULT_INVALID')
        if ((result['status'] == successful and (result['unknowns'] or result['gaps']))
                or (result['status'] == 'REPAIR_REQUIRED' and not result['unknowns'] and not result['gaps'])):
            raise ContractError('N5_EXISTING_REPAIR_RESULT_REASONS_INVALID')
        proof = dict(raw_output_ref=refs[0], raw_output_sha256='sha256:' + hashlib.sha256(raw).hexdigest(),
                     result=result, dsh_session_id=session, observed_tool_calls=calls)
        if 'raw_output_sha256' in row and any(row.get(key) != value for key, value in proof.items()):
            raise ContractError('N5_EXISTING_REPAIR_SAVED_PROOF_CHANGED')
        return proof

    def _event(self, row):
        events = self.truth.query('agent_runtime_event', mission_id=row['mission_id'],
            attempt_id=row['verification_attempt_id'], event_name='HANDOFF_RETURNED')
        if len(events) > 1:
            raise ContractError('N5_EXISTING_REPAIR_HANDOFF_NOT_UNIQUE')
        return events[0] if events else None

    @staticmethod
    def _claim(path):
        try:
            with path.open('x', encoding='utf-8') as stream:
                stream.write(path.name)
        except FileExistsError as exc:
            raise ContractError('N5_EXISTING_REPAIR_DISPATCH_UNRESOLVED_NO_REPLAY') from exc

    def _producer_row(self, row):
        return dict(row, **row['producer'])

    def _producer_proof(self, row):
        producer = self._producer_row(row)
        event = self._event(producer)
        if event is None:
            raise ContractError('N5_EXISTING_REPAIR_PRODUCER_HANDOFF_REQUIRED')
        proof = self._proof(producer, event, role=DATA_PREPARER, phase='DATA_REPAIR_PREPARATION',
            schema='RC72_N5_EXISTING_DATA_PREPARATION_V1',
            statuses={'PREPARED', 'REPAIR_REQUIRED'}, successful='PREPARED')
        return producer, event, proof

    def prepare(self, repair_id, *, launcher, allowed_tools):
        """Repair the physical resource; this can never certify it as verified.

        The producer and subsequent verifier have distinct scopes and sessions.
        A durable shared claim prevents starting the producer after verification
        started, and blocks verifier dispatch while producer effects are unknown.
        """
        if (not isinstance(launcher, DshHeadlessWorkerLauncher) or launcher.truth is not self.truth
                or launcher.authority is not self.authority or launcher.release_id != self.preparation.release_id):
            raise ContractError('N5_EXISTING_REPAIR_RUNTIME_AUTHORITY_MISMATCH')
        if (not isinstance(allowed_tools, (list, tuple)) or not allowed_tools
                or any(not isinstance(tool, str) or not tool.strip() or '*' in tool for tool in allowed_tools)):
            raise ContractError('N5_EXISTING_REPAIR_SCOPED_TOOLS_REQUIRED')
        tools = sorted(set(allowed_tools))
        row = self._signed(self._one(_KIND, repair_id=repair_id))
        producer = row.get('producer')
        if producer and (producer['allowed_tools'] != tools or producer['runtime_root'] != str(launcher.state_root)):
            raise ContractError('N5_EXISTING_REPAIR_PRODUCER_SCOPE_CHANGED')
        if producer and producer.get('state') in {'PREPARED', 'REPAIR_REQUIRED'}:
            self._producer_proof(row)
            return dict(state=producer['state'], repair_id=repair_id)
        if row['state'] != 'REQUESTED':
            raise ContractError('N5_EXISTING_REPAIR_PRODUCER_ORDER_INVALID')
        self._live(row)
        self._suspend(row)
        event = self._event(self._producer_row(row)) if producer else None
        if event is None:
            if producer:
                raise ContractError('N5_EXISTING_REPAIR_DISPATCH_UNRESOLVED_NO_REPLAY')
            folder = Path(row['runtime_root']) / 'existing-data-repair-claims'
            folder.mkdir(parents=True, exist_ok=True)
            self._claim(folder / (repair_id + '.claim'))
            attempt_id = 'N5RPREP-' + _hash(repair_id)[:24]
            assignment = launcher.assign(agent_id='data-preparer', role=DATA_PREPARER, phase='DATA_REPAIR_PREPARATION',
                mission_id=row['mission_id'], attempt_id=attempt_id,
                scope='task:%s/attempt:%s' % ('WI-N5RPREP-' + _hash(repair_id)[:24], attempt_id),
                input_refs=(row['original_binding']['data_ref'], 'data-requirement://' + row['data_requirement_id'],
                            'repair-boundary://' + row['boundary_id']), allowed_artifact_types=(), allowed_tools=tuple(tools))
            producer = dict(state='DISPATCHING', verification_attempt_id=attempt_id,
                workitem_id='WI-N5RPREP-' + _hash(repair_id)[:24], workitem_role=DATA_PREPARER,
                identity=asdict(assignment.identity), lease=asdict(assignment.lease),
                assignment_id=assignment.assignment_id, input_refs=list(assignment.input_refs),
                allowed_tools=tools, runtime_root=str(launcher.state_root))
            row = self._persist(row, producer=producer)
            self._start_workitem(self._producer_row(row))
            context = json.loads(self._prompt(self._producer_row(row)).rsplit('\n', 1)[1])
            context['output_contract'].update(schema='RC72_N5_EXISTING_DATA_PREPARATION_V1',
                                              status='PREPARED or REPAIR_REQUIRED')
            prompt = ('You are the RC7.2 N5 DATA_PREPARER for an accepted exact-DataRef repair. '
                'Use only authorized real tools and the original source_or_constructor to restore the exact resource '
                'and Case preconditions. Never substitute another DataRef, redesign the Case, or change strategy, '
                'cleanup, source or validity policy. If this cannot be done, return REPAIR_REQUIRED with reasons. '
                'PREPARED reports physical preparation only: a different independent DATA_VERIFIER must verify next. '
                'You have zero canonical artifact-write authority. Emit exactly one final JSON object.\n'
                + json.dumps(context, sort_keys=True, ensure_ascii=False))
            try:
                launcher.execute(assignment, prompt)
            finally:
                self.authority.revoke_worker_lease(assignment.lease.lease_id)
        _, event, proof = self._producer_proof(row)
        self._live(row)
        producer = dict(row['producer'], **proof, state=proof['result']['status'])
        self._output_workitem(dict(row, **producer), failed=proof['result']['status'] == 'REPAIR_REQUIRED')
        self._persist(row, producer=producer)
        return dict(state=producer['state'], repair_id=repair_id)

    def run(self, repair_id):
        row = self._signed(self._one(_KIND, repair_id=repair_id))
        if row['state'] in _FINAL:
            return self._audit(row)
        self._live(row)
        self._suspend(row)
        event = self._event(row)
        if event is None:
            if row['state'] != 'REQUESTED':
                raise ContractError('N5_EXISTING_REPAIR_DISPATCH_UNRESOLVED_NO_REPLAY')
            folder = Path(row['runtime_root']) / 'existing-data-repair-claims'
            folder.mkdir(parents=True, exist_ok=True)
            producer = row.get('producer')
            if producer:
                if producer.get('state') not in {'PREPARED', 'REPAIR_REQUIRED'}:
                    raise ContractError('N5_EXISTING_REPAIR_PRODUCER_UNRESOLVED')
                self._producer_proof(row)
            else:
                self._claim(folder / (repair_id + '.claim'))
            self._claim(folder / (repair_id + '.verifier.claim'))
            assignment = self.launcher.assign(agent_id='data-verifier', role=DATA_VERIFIER,
                phase='DATA_VERIFICATION', mission_id=row['mission_id'], attempt_id=row['verification_attempt_id'],
                scope='task:%s/attempt:%s' % (row['workitem_id'], row['verification_attempt_id']),
                input_refs=(row['original_binding']['data_ref'],
                    'data-requirement://' + row['data_requirement_id'], 'repair-boundary://' + row['boundary_id']),
                allowed_artifact_types=(), allowed_tools=tuple(row['allowed_tools']))
            row = self._persist(row, state='DISPATCHING', identity=asdict(assignment.identity),
                lease=asdict(assignment.lease), assignment_id=assignment.assignment_id, input_refs=list(assignment.input_refs))
            self._start_workitem(row)
            try:
                self.launcher.execute(assignment, self._prompt(row))
            finally:
                # A returned or interrupted process never leaves reusable tool
                # authority behind. Recovery authenticates historical proof only.
                self.authority.revoke_worker_lease(assignment.lease.lease_id)
            event = self._event(row)
            if event is None:
                raise ContractError('N5_EXISTING_REPAIR_HANDOFF_REQUIRED')
        proof = self._proof(row, event)
        if row['state'] != 'OBSERVED':
            row = self._persist(row, state='OBSERVED', **proof)
        return self._finalize(row, event)

    def _evidence(self, row, *, create=True):
        evidence_id = 'N5REPAIREV-' + _hash([row['repair_id'], row['raw_output_sha256']])[:24]
        expected = dict(evidence_id=evidence_id, mission_id=row['mission_id'], kind=('N5_EXISTING_DATA_PREPARATION' if row['identity']['role'] == DATA_PREPARER else 'N5_EXISTING_DATA_REVERIFICATION'),
            source_ref='dsh://session/' + row['dsh_session_id'], content_ref=row['raw_output_ref'],
            content_hash=row['raw_output_sha256'], subject_refs=[row['data_requirement_id'],
                row['original_binding']['binding_id'], row['verification_attempt_id'], row['repair_id']])
        current = self.truth.query('rc7_evidence', evidence_id=evidence_id)
        if current:
            if (len(current) != 1 or current[0].get('release_id') != row['release_id']
                    or any(current[0].get(k) != v for k, v in expected.items())):
                raise ContractError('N5_EXISTING_REPAIR_EVIDENCE_CHANGED')
        elif create:
            append_entity(self.truth, Evidence(**expected), release_id=row['release_id'])
        else:
            raise ContractError('N5_EXISTING_REPAIR_EVIDENCE_MISSING')
        return evidence_id

    def _anchor(self, row, event):
        return dict(row['requirement'], verification_attempt_id=row['verification_attempt_id'],
                    anchor_id=row['repair_id'], created_at=int(event['finished_at']))

    def _finalize(self, row, event):
        # Recheck raw bytes and source after the independent process returned.
        self._proof(row, event)
        self._live(row)
        evidence_id = self._evidence(row)
        current = self._one('rc72_n5_data_binding', binding_id=row['original_binding']['binding_id'])
        anchor = self._anchor(row, event)
        if row['result']['status'] == 'VERIFIED':
            inputs = {key: row['original_binding'][key] for key in ('data_requirement_id', 'data_ref', 'strategy',
                'source_or_constructor', 'precondition_refs', 'validity_window', 'cleanup_policy')}
            inputs.update(verification=row['result']['verification'], verification_evidence_refs=[evidence_id])
            self._finalizer(row['mission_id'])._revise_binding(anchor=anchor, inputs=inputs)
        else:
            self._finalizer(row['mission_id'])._require_new_observation(anchor, current)
            if current.get('verification_blocked_by_anchor') != row['repair_id']:
                raise ContractError('N5_EXISTING_REPAIR_SUSPENSION_CHANGED')
        superseded = self._finish_workitems(row)
        row = self._persist(row, state=row['result']['status'], evidence_ref=evidence_id, superseded_repair_ids=superseded)
        self.authority.revoke_worker_lease(row['lease']['lease_id'])
        return self._audit(row)

    def _audit(self, row):
        if row.get('producer'):
            self._producer_proof(row)
        event = self._event(row)
        if event is None:
            raise ContractError('N5_EXISTING_REPAIR_HANDOFF_REQUIRED')
        self._proof(row, event)
        if self._evidence(row, create=False) != row['evidence_ref']:
            raise ContractError('N5_EXISTING_REPAIR_EVIDENCE_CHANGED')
        current = self._one('rc72_n5_data_binding', binding_id=row['original_binding']['binding_id'])
        if current['data_ref'] != row['original_binding']['data_ref']:
            raise ContractError('N5_EXISTING_REPAIR_DATA_SUBSTITUTION_FORBIDDEN')
        if row['state'] == 'VERIFIED' and row['evidence_ref'] not in current['verification_evidence_refs'] and not any(
                row['evidence_ref'] in item['verification_evidence_refs'] for item in current.get('verification_history', [])):
            raise ContractError('N5_EXISTING_REPAIR_VERIFICATION_REVISION_MISSING')
        if row['state'] == 'VERIFIED':
            self._accept_workitem(row, evaluator_ref='runtime://n5-independent-proof-gate/' + row['repair_id'], audit=True)
            if row.get('producer'):
                producer = self._producer_row(row)
                if producer['result']['status'] == 'PREPARED':
                    self._accept_workitem(producer, evaluator_ref=row['identity']['worker_id'], audit=True)
                else:
                    self._output_workitem(producer, failed=True, create=False)
        else:
            self._output_workitem(row, failed=True, create=False)
            if row.get('producer'):
                self._output_workitem(self._producer_row(row), create=False)
        self.authority.revoke_worker_lease(row['lease']['lease_id'])
        return dict(state=row['state'], repair_id=row['repair_id'], data_requirement_id=row['data_requirement_id'],
                    data_ref=current['data_ref'], evidence_ref=row['evidence_ref'])


install_rc72_n5_existing_data_repair_overlay()
