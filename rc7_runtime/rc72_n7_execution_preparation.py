"""Scoped signed worker + deterministic Data/Browser acquisition for a planned Case.

Preparation is not tool execution and cannot produce a Case PASS. The signed
lease carries no professional write authority. Resources are acquired in stable
order and released on pre-execution failure; actual execution must revalidate
both admission and the prepared resource/authority tuple.
"""
from __future__ import annotations

from dataclasses import asdict, fields
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Mapping, Optional, Sequence

from rc6_runtime import contracts, truth as registry
from rc6_runtime.agent_runtime import WorkerAssignment
from rc6_runtime.authority import TaskLease, WorkerIdentity
from rc6_runtime.truth import TruthRuntime
from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Evidence, TaskStatus
from .rc72_authority import RC72AuthorityRuntime
from .rc72_browser_resources import BrowserPool, BrowserAccessMode
from .rc72_data_resources import DataLeaseManager, DataAccessMode
from .rc72_n7_execution_planning import ExecutionPlanningService
from .rc72_n7_execution_admission import _hash
from .rc72_worker_lifecycle import WorkerLifecycleService, FreshWorkerAssignment
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .state_machine import transition_task
from .truth_overlay import append_entity, install_rc7_truth_overlay

_ARTIFACT = 'rc72_n7_execution_preparation'
_EVENT = 'RC72_N7_EXECUTION_PREPARATION_UPSERTED'


class ExecutionPreparationError(ContractError):
    pass


def _validate(payload):
    out = deepcopy(payload)
    for key in ('preparation_id', 'release_id', 'source_commit', 'release_batch_id',
                'mission_id', 'plan_id', 'admission_id', 'contract_id', 'case_id',
                'etu_id', 'workitem_id', 'attempt_id', 'binding_id', 'worker_id', 'session_id'):
        out[key] = contracts._require_str(out, key)
    if out.get('status') not in {'PREPARED', 'INTERRUPTED', 'DRAINED'} or not isinstance(out.get('worker_identity'), dict) or not isinstance(out.get('task_lease'), dict):
        raise contracts.DomainValidationError('N7_PREPARATION_AUTHORITY_REQUIRED')
    for key in ('allowed_artifact_types', 'allowed_tools'):
        value = out['task_lease'].get(key)
        if isinstance(value, tuple):
            out['task_lease'][key] = list(value)
        contracts._require_string_list(out['task_lease'], key)
    if isinstance(out.get('attempt_generation'), bool) or not isinstance(out.get('attempt_generation'), int) or out['attempt_generation'] < 1:
        raise contracts.DomainValidationError('N7_PREPARATION_GENERATION_INVALID')
    contracts._require_string_list(out, 'data_lease_ids')
    contracts._require_string_list(out, 'browser_lease_ids')
    for key in ('actual_result', 'assertion_result', 'execution_result', 'field_verified', 'bank_final'):
        if key in out:
            raise contracts.DomainValidationError('N7_PREPARATION_RESULT_FORBIDDEN')
    out.update(artifact_type=_ARTIFACT, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n7_execution_preparation_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_ARTIFACT] = _validate
    registry.EVENT_TYPES[_EVENT] = (_ARTIFACT, 'preparation_id')
    registry.BUCKETS[_ARTIFACT] = 'rc72_n7_execution_preparations'
    registry.IDENTITY_FIELDS[_ARTIFACT] = 'preparation_id'


class ExecutionPreparationService:
    def __init__(self, truth: TruthRuntime, *, release_id: str, source_commit: str,
                 authority: RC72AuthorityRuntime, tool_registry: Mapping[str, Sequence[str]],
                 ttl_seconds: int = 300, now: Optional[datetime] = None):
        install_rc72_n7_execution_preparation_overlay()
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            raise ExecutionPreparationError('N7_PREPARATION_TTL_INVALID')
        self.truth, self.release_id, self.source_commit = truth, release_id, source_commit
        self.authority, self.tool_registry, self.ttl = authority, tool_registry, ttl_seconds
        self._active_dispatches = {}
        self._active_process_heartbeats = {}
        self.planning = ExecutionPlanningService(truth, release_id=release_id, source_commit=source_commit, now=now, authority=authority)
        self.lifecycle = WorkerLifecycleService(truth, release_id=release_id)
        self.data = DataLeaseManager(truth, release_id=release_id)
        self.browser = BrowserPool(truth, release_id=release_id)

    def _one(self, kind, **filters):
        rows = self.truth.query(kind, **filters)
        if len(rows) != 1:
            raise ExecutionPreparationError('N7_PREPARATION_TRUTH_NOT_UNIQUE:%s' % kind)
        return rows[0]

    def _tools(self, capabilities):
        tools = set()
        for capability in capabilities:
            names = self.tool_registry.get(capability)
            if not isinstance(names, (tuple, list)) or not names:
                raise ExecutionPreparationError('N7_CAPABILITY_ADAPTER_NOT_CONFIGURED:%s' % capability)
            if any(not isinstance(name, str) or not name.strip() or '*' in name for name in names):
                raise ExecutionPreparationError('N7_WILDCARD_OR_INVALID_TOOL_FORBIDDEN')
            tools.update(names)
        return tuple(sorted(tools))

    def prepare(self, *, plan_id: str, workitem_id: str,
                fenced_admission=None) -> Dict[str, Any]:
        plan = self.planning.assert_current(plan_id)
        items = [item for item in plan['items'] if item['workitem_id'] == workitem_id]
        if len(items) != 1:
            raise ExecutionPreparationError('N7_WORKITEM_OUTSIDE_PLAN')
        item = items[0]
        if plan.get('recovery_id'):
            from .rc72_n8_retry_truth import assert_reconciled_plan
            reconciliation = assert_reconciled_plan(self.planning, plan)
            if any(decision['workitem_id'] == workitem_id and decision['disposition'] == 'REUSE_FOR_CURRENT_REVIEW'
                   for decision in reconciliation.get('member_decisions', [])):
                raise ExecutionPreparationError('N7_MEMBER_ALREADY_EXECUTED_REVIEW_REQUIRED')
        current = self.truth.query(_ARTIFACT, workitem_id=workitem_id, status='PREPARED')
        if current:
            if len(current) != 1 or current[0].get('plan_id') != plan_id:
                raise ExecutionPreparationError('N7_PREPARATION_NOT_UNIQUE')
            return self.assert_current(current[0]['preparation_id'])
        history = self.truth.query(_ARTIFACT, workitem_id=workitem_id)
        previous = max(history, key=lambda value: value['attempt_generation']) if history else None
        generation = int(previous['attempt_generation']) + 1 if previous else 1
        contract = self._one('rc72_n6_executable_contract', contract_id=item['contract_id'])
        etu = self._one('rc72_etu', etu_id=item['etu_id'])
        tools = self._tools([value['name'] for value in contract['capabilities']])
        if contract['tool_route']['tool'] not in tools:
            raise ExecutionPreparationError('N7_PRIMARY_TOOL_NOT_IN_SCOPED_REGISTRY')
        control = ClosedLoopControlPlane(self.truth, self.release_id, plan['mission_id'])
        task = control.scheduler.task(workitem_id)
        if fenced_admission is None:
            if task.state != TaskStatus.READY:
                raise ExecutionPreparationError('N7_WORKITEM_NOT_READY')
            worker = self.lifecycle.assign_fresh_worker(
                mission_id=plan['mission_id'], team_id='TEAM-' + plan['mission_id'],
                role=etu['test_level'] + '_EXECUTE', etu_id=item['etu_id'], workitem_id=workitem_id,
                canonical_refs=dict(etu_refs=[item['etu_id']], executable_contract_refs=[item['contract_id']],
                                    data_refs=[ref['data_ref'] for ref in contract['data_refs']]),
                parent_session_id=previous['session_id'] if previous else None,
            )
        else:
            # The Captain-fenced admission is a real TaskScheduler lease in R1.
            # Reuse EXACTLY that Fresh Worker, not a second ungoverned session.
            # This opt-in path lets Session A connect the actual N7 preparation
            # to the governed AgentTeams scheduler without changing release driver.
            from .rc72_captain_scheduling import GovernedFreshDispatch
            from .rc72_captain_dispatch_fencing import CaptainDispatchFencer
            if not isinstance(fenced_admission, GovernedFreshDispatch):
                raise ExecutionPreparationError('N7_FENCED_ADMISSION_TYPE_REQUIRED')
            if (fenced_admission.state != 'LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH'
                    or fenced_admission.mission_id != plan['mission_id']
                    or fenced_admission.workitem_id != workitem_id
                    or fenced_admission.etu_id != item['etu_id']
                    or fenced_admission.role != etu['test_level'] + '_EXECUTE'
                    or task.state != TaskStatus.LEASED
                    or task.lease_owner != fenced_admission.worker_id):
                raise ExecutionPreparationError('N7_FENCED_ADMISSION_SCOPE_MISMATCH')
            # A caller-provided dataclass is not authority: exact admission
            # must have been durably written by the scoped scheduler in R1
            # *after* that real WorkItem lease. Missing/mismatched records
            # cannot mint a signed TaskLease or silently create a Worker.
            admission_rows = self.truth.query(
                'rc72_captain_etu_admission',
                admission_id=fenced_admission.admission_id)
            if len(admission_rows) != 1:
                raise ExecutionPreparationError('N7_FENCED_ADMISSION_R1_REQUIRED')
            admission = admission_rows[0]
            expected = dict(release_id=self.release_id,
                mission_id=plan['mission_id'], team_id=fenced_admission.team_id,
                captain_lease_id=fenced_admission.captain_lease_id,
                captain_session_id=fenced_admission.captain_session_id,
                captain_generation=fenced_admission.captain_generation,
                etu_id=item['etu_id'], workitem_id=workitem_id,
                role=fenced_admission.role, worker_id=fenced_admission.worker_id,
                session_id=fenced_admission.session_id,
                state='LEASED_AWAITING_SIGNED_AUTHORITY_AND_DSH')
            if admission.get('artifact_version') != 1 or any(
                    admission.get(k) != v for k, v in expected.items()):
                raise ExecutionPreparationError('N7_FENCED_ADMISSION_R1_MISMATCH')
            owner = CaptainDispatchFencer(self.truth, release_id=self.release_id).assert_owner(
                mission_id=plan['mission_id'], lease_id=fenced_admission.captain_lease_id,
                captain_session_id=fenced_admission.captain_session_id)
            if (owner['generation'] != fenced_admission.captain_generation
                    or owner['team_id'] != fenced_admission.team_id):
                raise ExecutionPreparationError('N7_FENCED_CAPTAIN_GENERATION_OR_TEAM_MISMATCH')
            session = self._one('rc72_worker_session', session_id=fenced_admission.session_id)
            context = session.get('context_bundle') or {}
            if (session.get('state') != 'ACTIVE'
                    or session.get('mission_id') != plan['mission_id']
                    or session.get('workitem_id') != workitem_id
                    or session.get('etu_id') != item['etu_id']
                    or session.get('worker_id') != fenced_admission.worker_id
                    or session.get('team_id') != owner['team_id']
                    or session.get('role') != fenced_admission.role
                    or session.get('purpose') != 'EXECUTION'
                    or session.get('runtime_assignment_id')
                    or session.get('task_lease_ref')
                    or session.get('dsh_session_id')
                    or session.get('binding_id')
                    or context.get('etu_refs') != [item['etu_id']]
                    or context.get('executable_contract_refs') != [item['contract_id']]
                    or sorted(context.get('data_refs') or []) != sorted(
                        ref['data_ref'] for ref in contract['data_refs'])
                    or context.get('lease_refs')):
                raise ExecutionPreparationError('N7_FENCED_FRESH_SESSION_PROOF_INVALID')
            worker = FreshWorkerAssignment(
                fenced_admission.worker_id, fenced_admission.session_id, dict(context))

        attempt_id = 'N7ATT-' + _hash([plan_id, workitem_id, worker.session_id])[:24]
        scope = 'task:%s/attempt:%s' % (workitem_id, attempt_id)
        identity = self.authority.adopt_identity(worker_id=worker.worker_id, role=etu['test_level'] + '_EXECUTE',
            phase='N7_EXECUTION', layer=etu['test_level'], generation=generation-1, session_id=worker.session_id)
        lease = self.authority.issue_lease(identity.worker_id, scope, (), tools, ttl_seconds=self.ttl)
        assignment = WorkerAssignment(identity=identity, lease=lease, worker_instance_id=identity.worker_id,
            agent_id='rc72-thin-executor', mission_id=plan['mission_id'], attempt_id=attempt_id,
            assignment_id='N7ASN-' + _hash([workitem_id, worker.session_id])[:24],
            parent_worker_id='rc72-runtime', scope=scope, input_refs=(item['contract_id'],),
            allowed_artifact_types=(), allowed_tools=tools)
        acquired, browser_leases = [], []
        binding = None
        try:
            if fenced_admission is None:
                leased = control.scheduler.lease_task(plan['mission_id'], workitem_id,
                    worker_ref=worker.worker_id, capabilities=[value['name'] for value in contract['capabilities']])
                if leased is None:
                    raise ExecutionPreparationError('N7_WORKITEM_SCHEDULING_DEFERRED')
            else:
                # Revalidate the exact pre-leased WorkItem before binding a
                # signed TaskLease. NEVER grant a second scheduler lease.
                current_task = control.scheduler.task(workitem_id)
                if (current_task.state != TaskStatus.LEASED
                        or current_task.lease_owner != worker.worker_id):
                    raise ExecutionPreparationError('N7_FENCED_WORKITEM_LEASE_LOST')
            binding = self.lifecycle.bind_signed_runtime_assignment(lifecycle_session_id=worker.session_id,
                                                                     assignment=assignment, case_id=item['case_id'],
                                                                     parent_attempt_id=previous['attempt_id'] if previous else None)
            for ref in sorted(contract['data_refs'], key=lambda value: value['data_ref']):
                grant = self.data.acquire(data_ref=ref['data_ref'], mission_id=plan['mission_id'], workitem_id=workitem_id,
                    attempt_id=attempt_id, worker_id=worker.worker_id,
                    mode=DataAccessMode(ref['reservation_policy']), ttl_seconds=self.ttl, cleanup_policy=ref['cleanup_policy'])
                acquired.append(grant.data_lease_id)
            if etu['test_level'] in {'L4', 'L5'}:
                snapshot = self._one('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id'])
                planned = next(case for case in snapshot['planning_cases'] if case['case_id'] == item['case_id'])
                grant = self.browser.acquire(mission_id=plan['mission_id'], workitem_id=workitem_id,
                    attempt_id=attempt_id, worker_id=worker.worker_id, access_mode=BrowserAccessMode.WRITE,
                    purpose=etu['test_level'] + '_EXECUTION', ttl_seconds=self.ttl, auth_asset_ref=planned['browser_context'])
                browser_leases.append(grant.browser_lease_id)
            bound = self._one('rc72_workitem_attempt_binding', binding_id=binding.binding_id)
            entity = WorkItemAttemptBinding(**{field.name: bound[field.name] for field in fields(WorkItemAttemptBinding) if field.name in bound})
            entity.resource_lease_refs = acquired + browser_leases
            self.lifecycle.repository.persist(entity, artifact_version=int(bound['artifact_version']) + 1)
            session = self._one('rc72_worker_session', session_id=worker.session_id)
            context = dict(session['context_bundle'])
            context['lease_refs'] = [lease.lease_id] + acquired + browser_leases
            self.lifecycle._update_session(session, context_bundle=context)
            payload = dict(preparation_id='N7PREP-' + _hash([plan_id, workitem_id, worker.session_id])[:24],
                release_id=self.release_id, source_commit=self.source_commit, release_batch_id=plan['release_batch_id'],
                mission_id=plan['mission_id'], plan_id=plan_id, admission_id=item['admission_id'],
                contract_id=item['contract_id'], case_id=item['case_id'], etu_id=item['etu_id'], workitem_id=workitem_id,
                attempt_id=attempt_id, binding_id=binding.binding_id, worker_id=worker.worker_id, session_id=worker.session_id,
                attempt_generation=generation, worker_identity=asdict(identity), task_lease=asdict(lease), data_lease_ids=acquired,
                browser_lease_ids=browser_leases, status='PREPARED', artifact_version=1)
            self.truth.append_atomic(_EVENT, payload)
        except Exception:
            # No tool has been invoked by this service. Rollback releases only
            # reservations and records that control-plane fact, never fake SUT cleanup.
            ev_id = 'N7ROLLBACK-' + _hash([workitem_id, worker.session_id])[:24]
            append_entity(self.truth, Evidence(evidence_id=ev_id, mission_id=plan['mission_id'],
                kind='N7_PRE_EXECUTION_RESERVATION_ROLLBACK', source_ref='runtime://n7-preparation',
                content_ref='runtime://no-tool-invoked/' + attempt_id, subject_refs=[workitem_id, attempt_id]), release_id=self.release_id)
            for value in reversed(browser_leases):
                self.browser.release(value, reason='pre-execution acquisition rollback')
            for value in reversed(acquired):
                self.data.release(value, cleanup_evidence_ref=ev_id, reason='no SUT tool invoked; release reservation')
            row = self._one('rc7_task', task_id=workitem_id)
            if row['state'] == 'LEASED':
                task = control.scheduler.task(workitem_id)
                transition_task(task, TaskStatus.READY)
                control.scheduler._persist_task(task, int(row['artifact_version']) + 1)
            if binding is not None:
                old = self._one('rc72_workitem_attempt_binding', binding_id=binding.binding_id)
                entity = WorkItemAttemptBinding(**{field.name: old[field.name] for field in fields(WorkItemAttemptBinding) if field.name in old})
                entity.state = WorkItemAttemptState.SUPERSEDED
                self.lifecycle.repository.persist(entity, artifact_version=int(old['artifact_version']) + 1)
            self.authority.revoke_worker_lease(lease.lease_id)
            self.lifecycle.checkpoint_and_close(worker.session_id, reason='pre-execution acquisition failed')
            raise
        return self.assert_current(payload['preparation_id'])

    def _assert_runtime_suspension(self, row):
        for drain in self.truth.query('rc72_n7_member_drain', preparation_id=row['preparation_id']):
            from .rc72_n7_member_drain import signed_member_drain
            signed_member_drain(self, drain)
            self.authority.revoke_worker_lease(row['task_lease']['lease_id'])
            raise ExecutionPreparationError('N7_EXECUTION_SUSPENDED_BY_MEMBER_CHECKPOINT')
        if self.truth.query('rc72_n8_repair_boundary', preparation_id=row['preparation_id']):
            self.authority.revoke_worker_lease(row['task_lease']['lease_id'])
            raise ExecutionPreparationError('N7_EXECUTION_SUSPENDED_BY_REPAIR_BOUNDARY')
        for heartbeat in self.truth.query('rc72_execution_process_heartbeat', preparation_id=row['preparation_id']):
            from .rc72_execution_heartbeat import signed_heartbeat
            signed_heartbeat(self, heartbeat)
            if (heartbeat['state'] == 'FAILED' or heartbeat['state'] in {'RUNNING', 'EXITED'}
                    and heartbeat['heartbeat_id'] not in self._active_process_heartbeats):
                self.authority.revoke_worker_lease(row['task_lease']['lease_id'])
                raise ExecutionPreparationError('N7_EXECUTION_PROCESS_RECOVERY_REQUIRED')
        calls = self.truth.query('rc72_n7_tool_dispatch', preparation_id=row['preparation_id'])
        # UNKNOWN means external I/O might already have committed. No caller,
        # including a different adapter or cold runtime, may restore the signed
        # TaskLease merely because the original IN_FLIGHT owner has exited.
        # FAILED is permitted only with the separately verified no-effect proof
        # and remains for independent N8 diagnosis, not unattended replay.
        if any(call['state'] == 'UNKNOWN' for call in calls):
            self.authority.revoke_worker_lease(row['task_lease']['lease_id'])
            raise ExecutionPreparationError('N7_EXECUTION_UNKNOWN_EFFECT_RECONCILIATION_REQUIRED')
        if any(call['state'] == 'IN_FLIGHT' for call in calls) and row['preparation_id'] not in self._active_dispatches:
            self.authority.revoke_worker_lease(row['task_lease']['lease_id'])
            raise ExecutionPreparationError('N7_EXECUTION_CONTROLLER_RECOVERY_REQUIRED')

    def _current_tuple(self, row):
        self._assert_runtime_suspension(row)
        plan = self.planning.assert_current(row['plan_id'])
        item = next((item for item in plan['items'] if item['workitem_id'] == row['workitem_id']), None)
        if item is None or item['contract_id'] != row['contract_id'] or item['admission_id'] != row['admission_id']:
            raise ExecutionPreparationError('N7_PREPARATION_LINEAGE_MISMATCH')
        identity = WorkerIdentity(**row['worker_identity'])
        lease_payload = dict(row['task_lease'])
        for key in ('allowed_artifact_types', 'allowed_tools'):
            lease_payload[key] = tuple(lease_payload[key])
        lease = TaskLease(**lease_payload)
        scope = 'task:%s/attempt:%s' % (row['workitem_id'], row['attempt_id'])
        session = self._one('rc72_worker_session', session_id=row['session_id'])
        binding = self._one('rc72_workitem_attempt_binding', binding_id=row['binding_id'])
        task = self._one('rc7_task', task_id=row['workitem_id'])
        etu = self._one('rc72_etu', etu_id=row['etu_id'])
        contract = self._one('rc72_n6_executable_contract', contract_id=row['contract_id'])
        expected_tools = self._tools([value['name'] for value in contract['capabilities']])
        if (row.get('status') != 'PREPARED' or row.get('release_id') != self.release_id or row.get('source_commit') != self.source_commit
                or identity.generation != row['attempt_generation'] - 1 or identity.worker_id != row['worker_id'] or identity.session_id != row['session_id']
                or identity.role != etu['test_level'] + '_EXECUTE' or identity.phase != 'N7_EXECUTION'
                or identity.layer != etu['test_level'] or lease.allowed_artifact_types
                or lease.scope_ref != scope
                or lease.allowed_tools != expected_tools or session['state'] != 'ACTIVE'
                or binding.get('worker_id') != row['worker_id'] or binding.get('attempt_id') != row['attempt_id']
                or binding.get('mission_id') != row['mission_id'] or binding.get('session_id') != row['session_id']
                or binding.get('workitem_id') != row['workitem_id'] or binding.get('etu_id') != row['etu_id']
                or binding.get('task_lease_ref') != lease.lease_id or binding.get('state') not in {'PREPARED', 'RUNNING', 'EVIDENCE_READY'}
                or binding.get('resource_lease_refs') != row['data_lease_ids'] + row['browser_lease_ids']
                or binding.get('case_id') != row['case_id'] or binding.get('mission_node_lineage_status') != 'RESOLVED'
                or binding.get('mission_node_type') != 'N7_EXECUTION'
                or task.get('state') not in {'LEASED', 'RUNNING'} or task.get('lease_owner') != row['worker_id']):
            raise ExecutionPreparationError('N7_PREPARATION_BINDING_INVALID')
        self.authority.validate_historical_lease(identity, lease)
        return identity, lease, contract, etu, scope, plan

    def _current_resources(self, row, contract, etu, plan, *, locked=False):
        data_check = self.data._assert_usable_locked if locked else self.data.assert_usable
        browser_check = self.browser._assert_usable_locked if locked else self.browser.assert_usable
        if len(row['data_lease_ids']) != len(contract['data_refs']):
            raise ExecutionPreparationError('N7_DATA_LEASE_DENOMINATOR_MISMATCH')
        for lease_id, ref in zip(row['data_lease_ids'], sorted(contract['data_refs'], key=lambda value: value['data_ref'])):
            resource = data_check(data_lease_id=lease_id, mission_id=row['mission_id'], workitem_id=row['workitem_id'],
                attempt_id=row['attempt_id'], worker_id=row['worker_id'], data_ref=ref['data_ref'])
            if resource['mode'] != ref['reservation_policy'] or resource['cleanup_policy'] != ref['cleanup_policy']:
                raise ExecutionPreparationError('N7_DATA_LEASE_CONTRACT_SCOPE_MISMATCH')
        if etu['test_level'] in {'L4', 'L5'} and len(row['browser_lease_ids']) != 1:
            raise ExecutionPreparationError('N7_BROWSER_LEASE_REQUIRED')
        if etu['test_level'] not in {'L4', 'L5'} and row['browser_lease_ids']:
            raise ExecutionPreparationError('N7_UNDECLARED_BROWSER_LEASE')
        snapshot = self._one('rc72_decomposition_snapshot', snapshot_id=plan['snapshot_id']) if row['browser_lease_ids'] else None
        planned = next((case for case in snapshot['planning_cases'] if case['case_id'] == row['case_id']), None) if snapshot else None
        for lease_id in row['browser_lease_ids']:
            browser_check(browser_lease_id=lease_id, mission_id=row['mission_id'], workitem_id=row['workitem_id'],
                attempt_id=row['attempt_id'], worker_id=row['worker_id'], access_mode=BrowserAccessMode.WRITE,
                auth_asset_ref=planned['browser_context'])

    def assert_current(self, preparation_id: str) -> Dict[str, Any]:
        from .rc72_ledger_lock import ledger_lock
        # Existing signed suspension is already sufficient to deny permission,
        # even while its live owner holds the ledger lock. Recheck after refresh.
        self._assert_runtime_suspension(self._one(_ARTIFACT, preparation_id=preparation_id))
        # Refresh and validate the complete tuple under one shared resource
        # decision lock. Per-resource refreshes followed by another replay left
        # a gap between the last ownership check and authority restoration.
        with ledger_lock(self.truth, busy='N7_PREPARATION_LEDGER_BUSY', conflict=ExecutionPreparationError):
            return self._assert_current_locked(preparation_id)

    def _assert_current_locked(self, preparation_id):
        """Internal: caller owns the shared ledger decision lock."""
        row = self._one(_ARTIFACT, preparation_id=preparation_id)
        self._assert_runtime_suspension(row)
        identity, lease, contract, etu, scope, plan = self._current_tuple(row)
        self._current_resources(row, contract, etu, plan, locked=True)
        from .rc72_lease_renewal import effective_worker_lease
        effective = effective_worker_lease(self, row)
        self.authority.restore_renewed_worker_lease(identity, lease, effective)
        return row

    def release_unstarted(self, preparation_id: str, *, reason: str) -> Dict[str, Any]:
        """Checkpoint an unstarted worker so takeover can create a fresh Attempt.

        Once RUNNING/tool evidence exists, cleanup belongs to execution/diagnosis;
        this path must not pretend business mutations were undone.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ExecutionPreparationError('N7_INTERRUPTION_REASON_REQUIRED')
        row = self._one(_ARTIFACT, preparation_id=preparation_id)
        if row['status'] == 'INTERRUPTED':
            return row
        task = self._one('rc7_task', task_id=row['workitem_id'])
        session = self._one('rc72_worker_session', session_id=row['session_id'])
        if (row.get('release_id') != self.release_id or row['status'] != 'PREPARED'
                or task['state'] != 'LEASED' or task.get('lease_owner') != row['worker_id']
                or session['state'] != 'ACTIVE' or self.truth.query('execution_attempt', attempt_id=row['attempt_id'])):
            raise ExecutionPreparationError('N7_INTERRUPTION_REQUIRES_UNSTARTED_OWNED_WORKER')
        payload = dict(row['task_lease'])
        for key in ('allowed_artifact_types', 'allowed_tools'):
            payload[key] = tuple(payload[key])
        lease = TaskLease(**payload)
        identity = WorkerIdentity(**row['worker_identity'])
        # Authenticate the original lease even after TTL expiration, solely to
        # release/revoke it. This never authorizes execution with an expired lease.
        self.authority._validate_lease(identity, lease, lease.issued_at)
        bound = self._one('rc72_workitem_attempt_binding', binding_id=row['binding_id'])
        if (lease.scope_ref != 'task:%s/attempt:%s' % (row['workitem_id'], row['attempt_id'])
                or lease.worker_id != row['worker_id'] or identity.worker_id != row['worker_id']
                or bound.get('worker_id') != row['worker_id'] or bound.get('attempt_id') != row['attempt_id']
                or bound.get('task_lease_ref') != lease.lease_id or bound.get('state') != 'PREPARED'):
            raise ExecutionPreparationError('N7_INTERRUPTION_BINDING_MISMATCH')
        for kind, values in (('rc72_browser_lease', row['browser_lease_ids']), ('rc72_data_lease', row['data_lease_ids'])):
            key = 'browser_lease_id' if kind == 'rc72_browser_lease' else 'data_lease_id'
            for value in values:
                resource = self._one(kind, **{key: value})
                if resource.get('worker_id') != row['worker_id'] or resource.get('attempt_id') != row['attempt_id']:
                    raise ExecutionPreparationError('N7_INTERRUPTION_RESOURCE_OWNER_MISMATCH')
        ev_id = 'N7INTERRUPT-' + _hash([preparation_id, reason])[:24]
        append_entity(self.truth, Evidence(evidence_id=ev_id, mission_id=row['mission_id'],
            kind='N7_UNSTARTED_WORKER_CHECKPOINT', source_ref='runtime://n7-preparation',
            content_ref='runtime://no-tool-invoked/' + row['attempt_id'],
            subject_refs=[row['workitem_id'], row['attempt_id']]), release_id=self.release_id)
        for value in row['browser_lease_ids']:
            current = self.browser.lease(value)
            if current.get('worker_id') != row['worker_id'] or current.get('attempt_id') != row['attempt_id']:
                raise ExecutionPreparationError('N7_INTERRUPTION_RESOURCE_OWNER_MISMATCH')
            if current['state'] == 'ACTIVE':
                self.browser.release(value, reason=reason)
        for value in row['data_lease_ids']:
            current = self.data.lease(value)
            if current.get('worker_id') != row['worker_id'] or current.get('attempt_id') != row['attempt_id']:
                raise ExecutionPreparationError('N7_INTERRUPTION_RESOURCE_OWNER_MISMATCH')
            if current['state'] == 'ACTIVE':
                self.data.release(value, cleanup_evidence_ref=ev_id, reason=reason)
        bound = self._one('rc72_workitem_attempt_binding', binding_id=row['binding_id'])
        entity = WorkItemAttemptBinding(**{field.name: bound[field.name] for field in fields(WorkItemAttemptBinding) if field.name in bound})
        entity.state = WorkItemAttemptState.SUPERSEDED
        self.lifecycle.repository.persist(entity, artifact_version=int(bound['artifact_version']) + 1)
        self.lifecycle.checkpoint_and_close(row['session_id'], reason=reason)
        control = ClosedLoopControlPlane(self.truth, self.release_id, row['mission_id'])
        value = control.scheduler.task(row['workitem_id'])
        try:
            self.planning.assert_current(row['plan_id'])
            target = TaskStatus.READY
        except (ValueError, RuntimeError):
            target = TaskStatus.STALE
        transition_task(value, target)
        control.scheduler._persist_task(value, int(task['artifact_version']) + 1)
        updated = dict(row, status='INTERRUPTED', artifact_version=int(row['artifact_version']) + 1)
        self.truth.append_atomic(_EVENT, updated)
        self.authority.revoke_worker_lease(lease.lease_id)
        return self._one(_ARTIFACT, preparation_id=preparation_id)


install_rc72_n7_execution_preparation_overlay()
