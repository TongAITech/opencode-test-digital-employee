"""N7 signed dispatch boundary. A tool receipt is never a Case PASS.

Persist intent before external I/O. An interrupted intent is deliberately not
replayed: its side effects are unknown and need diagnosis. Resource release and
business cleanup belong to the subsequent execution finalizer.
"""
from dataclasses import fields
from copy import deepcopy
import json
import os
from pathlib import Path

from .oracle_runtime import DeterministicOracleRuntime

from rc6_runtime import contracts, truth as registry
from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError
from .rc72_state_machine import RC72StateMachine
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_n7_execution_admission import _hash
from .truth_overlay import install_rc7_truth_overlay

_KIND = 'rc72_n7_tool_dispatch'
_EVENT = 'RC72_N7_TOOL_DISPATCH_UPSERTED'


def _validate(payload):
    out = deepcopy(payload)
    for key in ('dispatch_id', 'preparation_id', 'release_id', 'source_commit',
                'workitem_id', 'attempt_id', 'worker_id', 'contract_id',
                'contract_sha256', 'tool', 'request_sha256'):
        out[key] = contracts._require_str(out, key)
    if out.get('state') not in {'IN_FLIGHT', 'RETURNED', 'FAILED', 'UNKNOWN'}:
        raise contracts.DomainValidationError('N7_DISPATCH_STATE_INVALID')
    if out.get('state') == 'RETURNED':
        if not isinstance(out.get('raw_result'), dict) or not out['raw_result']:
            raise contracts.DomainValidationError('N7_RAW_RESULT_REQUIRED')
        if out.get('receipt_sha256') != _hash(out['raw_result']):
            raise contracts.DomainValidationError('N7_RECEIPT_HASH_MISMATCH')
    if out.get('state') in {'FAILED', 'UNKNOWN'}:
        contracts._require_str(out, 'error_type')
    if out.get('state') == 'UNKNOWN' and (out.get('replay_prohibited') is not True or out.get('possible_external_effect') is not True):
        raise contracts.DomainValidationError('N7_UNKNOWN_EFFECT_MUST_BLOCK_REPLAY')
    for key in ('passed', 'field_verified', 'bank_final', 'cleanup_complete'):
        if key in out:
            raise contracts.DomainValidationError('N7_DISPATCH_PREMATURE_CLAIM')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n7_tool_dispatch_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'dispatch_id')
    registry.BUCKETS[_KIND] = 'rc72_n7_tool_dispatches'
    registry.IDENTITY_FIELDS[_KIND] = 'dispatch_id'


class ToolDispatchError(ContractError):
    pass


class SignedToolDispatchService:
    """Adapters receive copies of the frozen contract and scoped resource IDs.

    Adapters must implement the entire defined action sequence or reject it.
    They cannot return caller-provided success flags to complete the WorkItem.
    """
    def __init__(self, preparation, *, adapters):
        install_rc72_n7_tool_dispatch_overlay()
        self.preparation = preparation
        self._live_invocations = set()
        self.truth = preparation.truth
        self.adapters = dict(adapters)

    def dispatch(self, preparation_id):
        self.truth.rebuild_projection()
        pending = self.truth.query(_KIND, preparation_id=preparation_id)
        if any(row['state'] in {'IN_FLIGHT', 'UNKNOWN'} for row in pending):
            if preparation_id not in self.preparation._active_dispatches:
                original = self.preparation._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
                self.preparation.authority.revoke_worker_lease(original['task_lease']['lease_id'])
            raise ToolDispatchError('N7_SIDE_EFFECTS_UNKNOWN_DIAGNOSIS_REQUIRED')
        prepared = self.preparation.assert_current(preparation_id)
        contract = self.preparation._one('rc72_n6_executable_contract',
                                         contract_id=prepared['contract_id'])
        tool = contract['tool_route']['tool']
        adapter = self.adapters.get(tool)
        if not callable(adapter):
            raise ToolDispatchError('N7_TOOL_ADAPTER_REQUIRED:' + tool)
        self.preparation.authority.authorize_tool(prepared['worker_id'],
            prepared['task_lease']['lease_id'], tool)
        from .rc72_n7_cleanup import frozen_cleanup_spec
        cleanup, verification = frozen_cleanup_spec(contract)
        for spec in (cleanup, verification):
            if spec['tool'] not in prepared['task_lease']['allowed_tools'] or not callable(self.adapters.get(spec['tool'])):
                raise ToolDispatchError('N7_CLEANUP_TOOL_NOT_READY_OR_OUTSIDE_SCOPE')
        dispatch_id = 'N7CALL-' + _hash([preparation_id, contract['contract_sha256'], tool])[:24]
        existing = self.truth.query(_KIND, dispatch_id=dispatch_id)
        if existing:
            if len(existing) != 1:
                raise ToolDispatchError('N7_DISPATCH_NOT_UNIQUE')
            row = existing[0]
            if row['state'] in {'IN_FLIGHT', 'UNKNOWN'}:
                raise ToolDispatchError('N7_SIDE_EFFECTS_UNKNOWN_DIAGNOSIS_REQUIRED')
            return row
        context = {key: deepcopy(prepared[key]) for key in
                   ('workitem_id', 'attempt_id', 'worker_id', 'session_id',
                    'data_lease_ids', 'browser_lease_ids')}
        preflight = getattr(adapter, 'preflight', None)
        if callable(preflight):
            preflight(contract=deepcopy(contract), context=deepcopy(context))
        row = dict(dispatch_id=dispatch_id, preparation_id=preparation_id,
            release_id=prepared['release_id'], source_commit=prepared['source_commit'],
            workitem_id=prepared['workitem_id'], attempt_id=prepared['attempt_id'],
            worker_id=prepared['worker_id'], contract_id=contract['contract_id'],
            contract_sha256=contract['contract_sha256'], tool=tool,
            request_sha256=_hash({'contract': contract, 'context': context}),
            state='IN_FLIGHT', artifact_version=1)
        # The Captain handoff uses this SAME cross-process ledger gate.
        # Revalidate R1 Captain/Worker/leases and append IN_FLIGHT while still
        # owning it. Once intent is durable, handoff must refuse until the
        # active work is independently checkpointed or diagnosed. This closes
        # the previously unguarded check-to-external-I/O race.
        from .rc72_ledger_lock import ledger_lock
        from .rc72_lease_renewal import execution_authorization_snapshot
        with ledger_lock(self.truth, busy='N7_DISPATCH_ADMISSION_LEDGER_BUSY',
                         conflict=ToolDispatchError):
            current = self.preparation._one(
                'rc72_n7_execution_preparation', preparation_id=preparation_id)
            self.preparation._assert_captain_binding_locked(current)
            current = self.preparation._assert_current_locked(preparation_id)
            if (current['worker_id'] != prepared['worker_id']
                    or current['attempt_id'] != prepared['attempt_id']
                    or current['task_lease'] != prepared['task_lease']
                    or current['status'] != 'PREPARED'):
                raise ToolDispatchError('N7_DISPATCH_PREPARATION_CHANGED_DURING_ADMISSION')
            if self.truth.query(_KIND, dispatch_id=dispatch_id):
                raise ToolDispatchError('N7_DISPATCH_ALREADY_DURABLE_NO_REPLAY')
            row.update(authorization_protocol='TEMPORAL_LEASE_V1',
                       execution_authorization=execution_authorization_snapshot(
                           self.preparation, current))
            claim_dir = Path(str(self.truth.store.path) + '.n7-dispatch-claims')
            claim_dir.mkdir(parents=True, exist_ok=True)
            try:
                claim = os.open(str(claim_dir / dispatch_id),
                                os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError as exc:
                raise ToolDispatchError(
                    'N7_DISPATCH_ALREADY_CLAIMED_DIAGNOSIS_REQUIRED') from exc
            # A claim is a permanent exclusion marker, never business truth.
            # If the process dies before appending, no automatic replay occurs.
            os.close(claim)
            self.truth.append_atomic(_EVENT, row)
        ClosedLoopControlPlane(self.truth, prepared['release_id'], prepared['mission_id']).start(
            prepared['workitem_id'], worker_ref=prepared['worker_id'])
        runtime = RC72StateMachine(self.truth, release_id=prepared['release_id'])
        node = runtime.node_by_type(prepared['mission_id'], AutonomousMissionNode.N7_EXECUTION)
        if node['state'] == 'READY':
            runtime.transition_state(node['mission_node_id'], MissionNodeState.RUNNING, reason='signed N7 tool dispatch')
        elif node['state'] != 'RUNNING':
            raise ToolDispatchError('N7_EXECUTION_NODE_NOT_RUNNING')
        binding = self.preparation._one('rc72_workitem_attempt_binding', binding_id=prepared['binding_id'])
        entity = WorkItemAttemptBinding(**{field.name: binding[field.name]
            for field in fields(WorkItemAttemptBinding) if field.name in binding})
        entity.state = WorkItemAttemptState.RUNNING
        self.preparation.lifecycle.repository.persist(entity, artifact_version=binding['artifact_version'] + 1)
        self._live_invocations.add(preparation_id)
        self.preparation._active_dispatches[preparation_id] = self
        try:
            from .rc72_formal_runner import FormalN7RunnerAdapter
            if isinstance(adapter, FormalN7RunnerAdapter):
                result = adapter.run_with_dispatch(contract=deepcopy(contract), context=deepcopy(context), dispatcher=self)
            else:
                result = adapter(contract=deepcopy(contract), context=deepcopy(context))
            if not isinstance(result, dict) or not result:
                raise ToolDispatchError('N7_TOOL_RAW_RESULT_REQUIRED')
            # Reject non-durable Python objects and NaN rather than inventing
            # stringified receipts. Freeze before the adapter can mutate it.
            result = json.loads(json.dumps(result, allow_nan=False))
        except Exception as exc:
            # Exception text can contain credentials; persist the class only.
            # A trusted signed pre-execution negative check is a deterministic
            # non-business failure. All other adapter errors retain UNKNOWN
            # semantics: a remote write may have committed before response loss.
            from .rc72_n7_no_effect_attestation import verified_no_external_business_effect
            no_effect_refs = verified_no_external_business_effect(self.preparation, prepared, exc)
            if no_effect_refs:
                result_row = dict(row, state='FAILED',
                                  error_type=type(exc).__name__,
                                  verified_no_business_effect=True,
                                  no_effect_evidence_refs=list(no_effect_refs),
                                  artifact_version=2)
            else:
                result_row = dict(row, state='UNKNOWN',
                                  error_type=type(exc).__name__,
                                  possible_external_effect=True,
                                  replay_prohibited=True, artifact_version=2)
            self.truth.append_atomic(_EVENT, result_row)
            return self.truth.query(_KIND, dispatch_id=dispatch_id)[0]
        finally:
            self._live_invocations.discard(preparation_id)
            self.preparation._active_dispatches.pop(preparation_id, None)
        returned = dict(row, state='RETURNED', raw_result=result,
                        receipt_sha256=_hash(result), artifact_version=2)
        self.truth.append_atomic(_EVENT, returned)
        return self.truth.query(_KIND, dispatch_id=dispatch_id)[0]


    def evaluate(self, preparation_id):
        """Evaluate stored actual bytes against frozen N6 predicates only.

        This is assertion evidence; cleanup, independent review and Case/Node
        completion are intentionally still required by the execution finalizer.
        """
        self.truth.rebuild_projection()
        observed = self.truth.query(_KIND, preparation_id=preparation_id)
        if any(call['state'] in {'IN_FLIGHT', 'UNKNOWN'} for call in observed):
            original = self.preparation._one(
                'rc72_n7_execution_preparation', preparation_id=preparation_id)
            self.preparation.authority.revoke_worker_lease(
                original['task_lease']['lease_id'])
            raise ToolDispatchError('N7_SIDE_EFFECTS_UNKNOWN_DIAGNOSIS_REQUIRED')
        prepared = self.preparation.assert_current(preparation_id)
        contract = self.preparation._one('rc72_n6_executable_contract',
                                         contract_id=prepared['contract_id'])
        rows = self.truth.query(_KIND, preparation_id=preparation_id)
        if len(rows) != 1 or rows[0]['state'] != 'RETURNED':
            raise ToolDispatchError('N7_RETURNED_RECEIPT_REQUIRED')
        row = rows[0]
        if (row['contract_sha256'] != contract['contract_sha256']
                or row['attempt_id'] != prepared['attempt_id']
                or row['worker_id'] != prepared['worker_id']
                or row['receipt_sha256'] != _hash(row['raw_result'])):
            raise ToolDispatchError('N7_RECEIPT_BINDING_MISMATCH')
        result = DeterministicOracleRuntime().evaluate(
            {'checks': deepcopy(contract['oracles'])}, deepcopy(row['raw_result']),
            {'contract_sha256': contract['contract_sha256'], 'dispatch_id': row['dispatch_id'],
             'attempt_id': row['attempt_id'], 'receipt_sha256': row['receipt_sha256']})
        if 'oracle_result' in row:
            if row['oracle_result'] != result:
                raise ToolDispatchError('N7_ORACLE_REPLAY_CONFLICT')
            return row
        updated = dict(row, oracle_result=result, artifact_version=row['artifact_version'] + 1)
        self.truth.append_atomic(_EVENT, updated)
        return self.truth.query(_KIND, dispatch_id=row['dispatch_id'])[0]


install_rc72_n7_tool_dispatch_overlay()
