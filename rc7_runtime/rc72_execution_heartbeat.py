"""Owned formal-process heartbeat and same-scope lease maintenance.

Only the actual dispatcher/Popen owner may renew. A failed guardian suspends
business authority and preserves custody; it does not establish remote-side
compensation, a product defect, Case PASS or Mission convergence.
"""
from copy import deepcopy
import hmac
import math
import subprocess
import time

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .rc72_ledger_lock import ledger_lock
from .rc72_lease_renewal import ExecutionLeaseRenewalService, effective_worker_lease
from .rc72_n7_execution_admission import _hash

_KIND = 'rc72_execution_process_heartbeat'
_EVENT = 'RC72_EXECUTION_PROCESS_HEARTBEAT_UPSERTED'


def _validate(payload):
    row = deepcopy(payload)
    for key in ('heartbeat_id', 'release_id', 'source_commit', 'preparation_id', 'mission_id',
                'workitem_id', 'attempt_id', 'worker_id', 'session_id', 'contract_id', 'contract_sha256',
                'run_id', 'command_sha256', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != 'OWNED_FORMAL_PROCESS_HEARTBEAT' or row.get('state') not in {'RUNNING', 'EXITED', 'COMPLETED', 'FAILED'}:
        raise contracts.DomainValidationError('N7_HEARTBEAT_STATE_INVALID')
    if not isinstance(row.get('pid'), int) or isinstance(row['pid'], bool) or row['pid'] < 1:
        raise contracts.DomainValidationError('N7_HEARTBEAT_PID_REQUIRED')
    if not isinstance(row.get('renewal_refs'), list):
        raise contracts.DomainValidationError('N7_HEARTBEAT_RENEWALS_REQUIRED')
    for key in ('case_pass', 'field_verified', 'bank_final', 'execution_result'):
        if key in row:
            raise contracts.DomainValidationError('N7_HEARTBEAT_PREMATURE_CLAIM')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_execution_heartbeat_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'heartbeat_id')
    registry.IDENTITY_FIELDS[_KIND] = 'heartbeat_id'
    registry.BUCKETS[_KIND] = 'rc72_execution_process_heartbeats'


def signed_heartbeat(preparation, row):
    value = {key: item for key, item in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], preparation.authority._sign(value)):
        raise ContractError('N7_HEARTBEAT_SIGNATURE_INVALID')
    return row


def verify_process_heartbeats(preparation, original, refs):
    """Read-only historical evidence validation, never authority restoration."""
    if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
        raise ContractError('N7_HEARTBEAT_PROOF_DENOMINATOR_REQUIRED')
    contract = preparation._one('rc72_n6_executable_contract', contract_id=original['contract_id'])
    rows = []
    for ref in refs:
        row = signed_heartbeat(preparation, preparation._one(_KIND, heartbeat_id=ref))
        if (any(row[key] != original[key] for key in ('release_id', 'source_commit', 'preparation_id',
                'mission_id', 'workitem_id', 'attempt_id', 'worker_id', 'session_id', 'contract_id'))
                or row['contract_sha256'] != contract['contract_sha256']
                or row['state'] not in {'COMPLETED', 'FAILED'} or row.get('observed_exit_code') is None
                or row['heartbeat_id'] != 'N7HB-' + _hash([original['preparation_id'], row['run_id']])[:24]):
            raise ContractError('N7_HEARTBEAT_SCOPE_OR_TERMINATION_INVALID')
        for renewal_id in row['renewal_refs']:
            renewal = preparation._one('rc72_execution_lease_renewal', renewal_id=renewal_id)
            from .rc72_lease_renewal import _signed
            _signed(preparation, renewal)
            if renewal['state'] != 'APPLIED' or renewal['preparation_id'] != original['preparation_id']:
                raise ContractError('N7_HEARTBEAT_RENEWAL_SCOPE_CHANGED')
        import hashlib
        files = row.get('captured_files')
        if not isinstance(files, dict) or set(files) != {'stdout', 'stderr', 'command'}:
            raise ContractError('N7_HEARTBEAT_CAPTURE_REQUIRED')
        from pathlib import Path
        for descriptor in files.values():
            ref = descriptor.get('ref', '')
            path = Path(ref[len('file://'):]) if ref.startswith('file://') else None
            if (path is None or path.is_symlink() or not path.is_file() or path.parent.name != row['run_id']
                    or hashlib.sha256(path.read_bytes()).hexdigest() != descriptor.get('sha256')):
                raise ContractError('N7_HEARTBEAT_CAPTURE_BYTES_CHANGED')
        import json
        command_ref = files['command']['ref']
        command = json.loads(Path(command_ref[len('file://'):]).read_text(encoding='utf-8'))
        if _hash(command.get('command')) != row['command_sha256'] or command.get('exit_code') != row['runtime_exit_code']:
            raise ContractError('N7_HEARTBEAT_COMMAND_OR_EXIT_MISMATCH')
        rows.append(row)
    return rows


class ExecutionProcessHeartbeat:
    def __init__(self, preparation, original, dispatcher, *, interval_seconds=5,
                 renew_before_seconds=30, renewal_ttl_seconds=None):
        from .rc72_n7_tool_dispatch import SignedToolDispatchService
        if (not isinstance(dispatcher, SignedToolDispatchService) or dispatcher.preparation is not preparation
                or original['preparation_id'] not in dispatcher._live_invocations):
            raise ContractError('N7_HEARTBEAT_OWNED_DISPATCH_REQUIRED')
        for value in (interval_seconds, renew_before_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ContractError('N7_HEARTBEAT_INTERVAL_INVALID')
        self.preparation, self.truth, self.original, self.dispatcher = preparation, preparation.truth, original, dispatcher
        self.interval, self.margin = interval_seconds, renew_before_seconds
        self.ttl = max(preparation.ttl, 60) if renewal_ttl_seconds is None else renewal_ttl_seconds
        if (isinstance(self.ttl, bool) or not isinstance(self.ttl, int) or self.ttl < 1
                or self.margin >= self.ttl or self.interval > self.margin):
            raise ContractError('N7_HEARTBEAT_POLICY_INVALID')
        self.renewal = ExecutionLeaseRenewalService(preparation, max_extension_seconds=max(preparation.ttl, 300, self.ttl))
        self.refs = []
        self.pending = {}

    def _persist(self, row, **changes):
        for attempt in range(20):
            try:
                return self._persist_once(row, **changes)
            except ContractError as exc:
                if str(exc) != 'N7_HEARTBEAT_LEDGER_BUSY' or attempt == 19:
                    raise
                time.sleep(0.01)

    def _persist_once(self, row, **changes):
        raw = {key: value for key, value in row.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        raw.update(changes)
        with ledger_lock(self.truth, busy='N7_HEARTBEAT_LEDGER_BUSY'):
            current = self.truth.query(_KIND, heartbeat_id=row['heartbeat_id'])
            version = current[0]['artifact_version'] if current else 0
            payload = dict(raw, signature=self.preparation.authority._sign(raw), artifact_version=version + 1)
            try:
                self.truth.append_atomic(_EVENT, payload)
            except Exception:
                # An append response may be lost after the fsync. Read the
                # actual signed observation; never repeat process I/O.
                self.truth.rebuild_projection()
                observed = self.truth.query(_KIND, heartbeat_id=row['heartbeat_id'])
                if not observed or any(observed[0].get(key) != value for key, value in payload.items()):
                    raise
            return signed_heartbeat(self.preparation, self.preparation._one(_KIND, heartbeat_id=row['heartbeat_id']))

    def _tick(self, row, process):
        if process.poll() is not None:
            return row
        if self.original['preparation_id'] not in self.dispatcher._live_invocations:
            raise ContractError('N7_HEARTBEAT_DISPATCH_LOST')
        lease = effective_worker_lease(self.preparation, self.original)
        if lease.expires_at - int(time.time()) > self.margin:
            try:
                self.preparation.assert_current(self.original['preparation_id'])
            except ContractError as exc:
                if str(exc) in {'DATA_RESOURCE_CONFLICT:LEDGER_BUSY', 'RESOURCE_CONFLICT:LEDGER_BUSY', 'N7_PREPARATION_LEDGER_BUSY'} and int(time.time()) < lease.expires_at:
                    return row
                raise
            return row
        if lease.expires_at - int(time.time()) <= self.margin:
            renewal_id = 'N7HBRENEW-' + _hash([row['heartbeat_id'], lease.expires_at])[:24]
            try:
                result = self.renewal.renew(self.original['preparation_id'], renewal_id=renewal_id,
                                          ttl_seconds=self.ttl, dispatcher=self.dispatcher)
            except ContractError as exc:
                if str(exc) == 'N7_RENEWAL_LEDGER_BUSY' and int(time.time()) < lease.expires_at:
                    return row
                raise
            row = self._persist(row, renewal_refs=row['renewal_refs'] + [result['renewal_id']])
        return row

    def execute(self, command, *, cwd, env, timeout_seconds, run_id):
        # Admission was performed before launch; keep actual Popen ownership in
        # this process. Cold runtimes cannot reconstruct it from a PID or JSON.
        self.preparation.assert_current(self.original['preparation_id'])
        process = subprocess.Popen(list(command), cwd=cwd, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        heartbeat_id = 'N7HB-' + _hash([self.original['preparation_id'], run_id])[:24]
        self.preparation._active_process_heartbeats[heartbeat_id] = process
        row = dict(heartbeat_id=heartbeat_id, purpose='OWNED_FORMAL_PROCESS_HEARTBEAT',
            **{key: self.original[key] for key in ('release_id', 'source_commit', 'preparation_id', 'mission_id',
                'workitem_id', 'attempt_id', 'worker_id', 'session_id', 'contract_id')},
            contract_sha256=self.preparation._one('rc72_n6_executable_contract', contract_id=self.original['contract_id'])['contract_sha256'],
            run_id=run_id, command_sha256=_hash(list(command)), pid=process.pid, started_at=int(time.time()),
            state='RUNNING', renewal_refs=[], observed_exit_code=None)
        deadline = time.monotonic() + timeout_seconds
        stdout, stderr, runtime_code = '', '', None
        failure, original_error = None, None
        try:
            row = self._persist(row)
            self.refs.append(heartbeat_id)
            row = self._tick(row, process)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure, runtime_code = 'PROCESS_TIMEOUT', 124
                    break
                try:
                    stdout, stderr = process.communicate(timeout=min(self.interval, remaining))
                    runtime_code = process.returncode
                    break
                except subprocess.TimeoutExpired:
                    row = self._tick(row, process)
        except BaseException as exc:
            failure, runtime_code, original_error = type(exc).__name__, 125, exc
        finally:
            if failure:
                self.preparation.authority.revoke_worker_lease(self.original['task_lease']['lease_id'])
            try:
                if process.poll() is None:
                    process.kill()
                stdout, stderr = process.communicate(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                failure, runtime_code = 'PROCESS_DRAIN_UNCONFIRMED', 125
                original_error = original_error or exc
            try:
                row = self._persist(row, state='FAILED' if failure else 'EXITED', failure_kind=failure,
                    observed_exit_code=process.poll(), runtime_exit_code=runtime_code, finished_at=int(time.time()))
                self.pending[run_id] = row
            except BaseException:
                self.preparation.authority.revoke_worker_lease(self.original['task_lease']['lease_id'])
                self.preparation._active_process_heartbeats.pop(heartbeat_id, None)
                raise
        if original_error is not None and not isinstance(original_error, Exception):
            self.preparation._active_process_heartbeats.pop(heartbeat_id, None)
            raise original_error
        if failure:
            stderr = (stderr or '') + '\nN7_PROCESS_GUARDIAN_STOPPED:' + failure
        return subprocess.CompletedProcess(list(command), runtime_code, stdout or '', stderr or '')

    def after_capture(self, run_id, *, stdout_path, stderr_path, command_path):
        import hashlib
        row = self.pending[run_id]
        try:
            files = {}
            for label, path in (('stdout', stdout_path), ('stderr', stderr_path), ('command', command_path)):
                if path.is_symlink() or not path.is_file() or path.parent.name != run_id:
                    raise ContractError('N7_HEARTBEAT_CAPTURE_SCOPE_INVALID')
                files[label] = dict(ref='file://' + str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            self._persist(row, state='FAILED' if row['failure_kind'] else 'COMPLETED', captured_files=files)
        finally:
            self.preparation._active_process_heartbeats.pop(row['heartbeat_id'], None)

    def capture_failed(self, run_id):
        row = self.pending.get(run_id)
        if row:
            self.preparation.authority.revoke_worker_lease(self.original['task_lease']['lease_id'])
            try:
                self._persist(row, state='FAILED', failure_kind='EVIDENCE_CAPTURE_FAILED')
            finally:
                self.preparation._active_process_heartbeats.pop(row['heartbeat_id'], None)


install_rc72_execution_heartbeat_overlay()
