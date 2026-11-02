"""Checkpoint one actually executed and cleaned member, without declaring PASS.

The immutable signed candidate preserves its original execution evidence. It
withdraws execution authority and closes the worker; future repaired-plan reuse
needs a separate current-scope decision and full-denominator independent review.
No subprocess or compensation is launched by this service.
"""
from copy import deepcopy
import hashlib
import hmac
from pathlib import Path

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .rc72_canonical_design import CanonicalDesignService
from .rc72_ledger_lock import ledger_lock
from .rc72_n7_execution_admission import _hash
from .rc72_n7_evidence_review import ExecutionEvidenceReviewService

_KIND = 'rc72_n7_member_drain'
_EVENT = 'RC72_N7_MEMBER_DRAIN_UPSERTED'
_REASON = 'N7 executed member checkpoint; current whole-plan review still required'


def _validate(payload):
    row = deepcopy(payload)
    for key in ('drain_id', 'release_id', 'source_commit', 'mission_id', 'release_batch_id',
                'plan_id', 'preparation_id', 'signature'):
        contracts._require_str(row, key)
    if row.get('purpose') != 'N7_EXECUTED_MEMBER_CHECKPOINT' or row.get('state') not in {'PLANNED', 'DRAINED'}:
        raise contracts.DomainValidationError('N7_MEMBER_DRAIN_STATE_INVALID')
    for key in ('original_preparation', 'original_task', 'original_binding', 'case_snapshot'):
        if not isinstance(row.get(key), dict):
            raise contracts.DomainValidationError('N7_MEMBER_DRAIN_CONTEXT_REQUIRED')
    if not isinstance(row.get('captured_evidence'), list) or not row['captured_evidence']:
        raise contracts.DomainValidationError('N7_MEMBER_DRAIN_EVIDENCE_REQUIRED')
    if any(key in row for key in ('case_pass', 'n7_pass', 'field_verified', 'bank_final', 'reuse_approved')):
        raise contracts.DomainValidationError('N7_MEMBER_DRAIN_PREMATURE_CLAIM')
    row.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(row))
    return row


def install_rc72_n7_member_drain_overlay():
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'drain_id')
    registry.IDENTITY_FIELDS[_KIND] = 'drain_id'
    registry.BUCKETS[_KIND] = 'rc72_n7_member_drains'


def signed_member_drain(preparation, row):
    signed = {k: v for k, v in row.items() if k not in {'signature', 'artifact_type', 'artifact_version'}}
    if not hmac.compare_digest(row['signature'], preparation.authority._sign(signed)):
        raise ContractError('N7_MEMBER_DRAIN_SIGNATURE_INVALID')
    if (row['release_id'] != preparation.release_id or row['source_commit'] != preparation.source_commit
            or row['drain_id'] != 'N7DRAIN-' + _hash(row['preparation_id'])[:24]):
        raise ContractError('N7_MEMBER_DRAIN_SCOPE_CHANGED')
    return row


class ExecutionMemberDrainService:
    def __init__(self, evidence_review):
        if not isinstance(evidence_review, ExecutionEvidenceReviewService):
            raise ContractError('N7_MEMBER_DRAIN_NATIVE_EVIDENCE_REVIEW_REQUIRED')
        self.review = evidence_review
        self.preparation, self.truth = evidence_review.preparation, evidence_review.truth

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _persist(self, row, **changes):
        raw = {k: v for k, v in row.items() if k not in {'signature', 'artifact_type', 'artifact_version'}}
        raw.update(changes)
        current = self.truth.query(_KIND, preparation_id=row['preparation_id'])
        payload = dict(raw, signature=self.preparation.authority._sign(raw),
                       artifact_version=current[0]['artifact_version'] + 1 if current else 1)
        self.truth.append_atomic(_EVENT, payload)
        return signed_member_drain(self.preparation, self._one(_KIND, preparation_id=row['preparation_id']))

    def _snapshot(self, p, *, allow_finalized=False, historical_task=None):
        plan = self._one('rc72_n7_execution_plan', plan_id=p['plan_id'])
        if any(plan[key] != p[key] for key in ('release_id', 'source_commit', 'mission_id', 'release_batch_id')):
            raise ContractError('N7_MEMBER_DRAIN_PLAN_SCOPE_CHANGED')
        items = [item for item in plan['items'] if item['workitem_id'] == p['workitem_id']]
        design = CanonicalDesignService(self.truth, release_id=p['release_id'], source_commit=p['source_commit']).load(
            release_batch_id=p['release_batch_id'])
        cases = {case['tc_id']: case for case in design.cases}
        if (len(items) != 1 or len(plan['items']) != len(cases)
                or {item['case_id'] for item in plan['items']} != set(cases)):
            raise ContractError('N7_MEMBER_DRAIN_CASE_DENOMINATOR_CHANGED')
        admission = self._one('rc72_n7_execution_admission', admission_id=p['admission_id'])
        raw = {k: v for k, v in admission.items() if k not in {'admission_id', 'status', 'artifact_type', 'artifact_version'}}
        if admission['admission_id'] != 'N7ADM-' + _hash(raw)[:24]:
            raise ContractError('N7_MEMBER_DRAIN_ORIGINAL_ADMISSION_CHANGED')
        # Historical validation never admits current execution or a PASS. N5/N6
        # may already be invalidated by another member's accepted diagnosis.
        case = self.review._case_snapshot(plan, items[0], cases, p, current_upstream=False, allow_finalized=allow_finalized, historical_task=historical_task)
        if any(not call.get('runtime_signature') for call in self.truth.query(
                'rc72_n7_cleanup_call', preparation_id=p['preparation_id'])):
            raise ContractError('N7_MEMBER_DRAIN_SIGNED_CLEANUP_REQUIRED')
        if case['formal_proof_gaps'] or case['formal_runner_receipt_ref'] is None:
            raise ContractError('N7_MEMBER_DRAIN_ACTUAL_FORMAL_PROOF_REQUIRED')
        if p['preparation_id'] in self.preparation._active_dispatches:
            raise ContractError('N7_MEMBER_DRAIN_LIVE_DISPATCH_MUST_EXIT')
        return case

    def _accepted_finalization(self, row, task, binding):
        p = row['original_preparation']
        attempt = self._one('execution_attempt', attempt_id=p['attempt_id'])
        receipt_id = attempt.get('final_review_result_id')
        if not receipt_id or attempt['status'] != 'PASS':
            raise ContractError('N7_MEMBER_DRAIN_SIGNED_FINAL_REVIEW_REQUIRED')
        from .rc72_n7_finalization import ExecutionFinalizationService
        from .rc72_n7_evidence_review import _validate as validate_bundle
        receipt = ExecutionFinalizationService(self.review)._verify(
            self._one('rc72_n7_execution_review', review_result_id=receipt_id))
        bundle = validate_bundle(self._one('rc72_n7_evidence_bundle', bundle_id=receipt['bundle_id']))
        cases = [case for case in bundle['case_results'] if case['preparation_id'] == p['preparation_id']]
        if (receipt['verdict'] != 'PASS' or receipt['bundle_sha256'] != bundle['bundle_sha256'] or len(cases) != 1
                or any(receipt[key] != p[key] for key in ('release_id', 'source_commit'))
                or any(cases[0].get(k) != v for k, v in row['case_snapshot'].items())):
            raise ContractError('N7_MEMBER_DRAIN_FINAL_REVIEW_SCOPE_CHANGED')
        ignored_task = {'state', 'artifact_version', 'updated_at', 'output_artifact_refs', 'evaluation_id'}
        ignored_binding = {'state', 'artifact_version'}
        if (task['state'] not in {'RUNNING', 'OUTPUT_PRODUCED', 'EVALUATING', 'PASS'}
                or binding['state'] not in {'EVIDENCE_READY', 'COMPLETED'}
                or {k: v for k, v in task.items() if k not in ignored_task}
                != {k: v for k, v in row['original_task'].items() if k not in ignored_task}
                or {k: v for k, v in binding.items() if k not in ignored_binding}
                != {k: v for k, v in row['original_binding'].items() if k not in ignored_binding}):
            raise ContractError('N7_MEMBER_DRAIN_FINALIZED_OWNER_CHANGED')

    def _audit(self, row, *, terminal=False, allow_finalized=False, disposition=None):
        signed_member_drain(self.preparation, row)
        p = self._one('rc72_n7_execution_preparation', preparation_id=row['preparation_id'])
        original = row['original_preparation']
        expected = dict(original, status='DRAINED', artifact_version=original['artifact_version'] + 1)
        if disposition is not None:
            from .rc72_n8_member_disposition import verify_member_projection
            verify_member_projection(self.preparation.planning, disposition, row, partial=not terminal)
            expected = p  # Exact permitted projection was authenticated above.
        if p != (expected if terminal else original) and (terminal or p != expected):
            raise ContractError('N7_MEMBER_DRAIN_PREPARATION_CHANGED')
        task = self._one('rc7_task', task_id=p['workitem_id'])
        binding = self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
        if disposition is None and (task != row['original_task'] or binding != row['original_binding']):
            if not allow_finalized:
                raise ContractError('N7_MEMBER_DRAIN_EXECUTION_EVIDENCE_CHANGED')
            self._accepted_finalization(row, task, binding)
        if self._snapshot(p, allow_finalized=allow_finalized,
                historical_task=row['original_task'] if disposition is not None else None) != row['case_snapshot']:
            raise ContractError('N7_MEMBER_DRAIN_EXECUTION_EVIDENCE_CHANGED')
        declarations = {item['requirement']: item for item in row['case_snapshot']['evidence_declarations']}
        captures = row['captured_evidence']
        if (len(captures) != len(declarations)
                or {item['requirement'] for item in captures} != set(declarations)):
            raise ContractError('N7_MEMBER_DRAIN_CAPTURE_DENOMINATOR_CHANGED')
        for item in captures:
            path = Path(item['content_ref'][len('file://'):]) if item['content_ref'].startswith('file://') else None
            if (path is None or path.is_symlink() or not path.is_file()
                    or item['sha256'] != declarations[item['requirement']]['sha256']
                    or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']
                    or path.stat().st_size != item['size_bytes']):
                raise ContractError('N7_MEMBER_DRAIN_CAPTURE_BYTES_CHANGED')
        session = self._one('rc72_worker_session', session_id=p['session_id'])
        if (session['worker_id'] != p['worker_id'] or session['workitem_id'] != p['workitem_id']
                or session['state'] not in ({'CLOSED'} if terminal or disposition is not None else {'ACTIVE', 'CLOSED'})
                or (session['state'] == 'CLOSED' and session.get('close_reason') != _REASON)):
            raise ContractError('N7_MEMBER_DRAIN_SESSION_CHANGED')
        return p

    def assert_drained(self, preparation_id, *, allow_finalized=False):
        row = signed_member_drain(self.preparation, self._one(_KIND, preparation_id=preparation_id))
        if row['state'] != 'DRAINED':
            raise ContractError('N7_MEMBER_DRAIN_INCOMPLETE')
        self._audit(row, terminal=True, allow_finalized=allow_finalized)
        return row

    def drain(self, preparation_id):
        with ledger_lock(self.truth, busy='N7_MEMBER_DRAIN_LEDGER_BUSY'):
            prior = self.truth.query(_KIND, preparation_id=preparation_id)
            if prior:
                if len(prior) != 1:
                    raise ContractError('N7_MEMBER_DRAIN_NOT_UNIQUE')
                row = signed_member_drain(self.preparation, prior[0])
                if row['state'] == 'DRAINED':
                    return self.assert_drained(preparation_id, allow_finalized=True)
            else:
                p = self._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
                if p['status'] != 'PREPARED':
                    raise ContractError('N7_MEMBER_DRAIN_PREPARED_EXECUTION_REQUIRED')
                case = self._snapshot(p)
                collected, total = [], 0
                # Entire denominator is preflighted before checkpoint/closure.
                for declaration in case['evidence_declarations']:
                    data = self.review._file_bytes(declaration)
                    total += len(data)
                    if total > self.review.max_bundle_bytes:
                        raise ContractError('N7_MEMBER_DRAIN_CAPTURE_SIZE_LIMIT')
                    collected.append((declaration, data))
                self.review.capture_root.mkdir(parents=True, exist_ok=True)
                captures = []
                for declaration, data in collected:
                    path = self.review.capture_root / (declaration['sha256'] + '.bin')
                    self.review._capture(path, data, declaration['sha256'])
                    captures.append(dict(requirement=declaration['requirement'], content_ref='file://' + str(path),
                                         sha256=declaration['sha256'], size_bytes=len(data)))
                row = self._persist(dict(drain_id='N7DRAIN-' + _hash(preparation_id)[:24],
                    purpose='N7_EXECUTED_MEMBER_CHECKPOINT', **{key: p[key] for key in
                        ('release_id', 'source_commit', 'mission_id', 'release_batch_id', 'plan_id', 'preparation_id')},
                    adapter_output_root=str(self.review.output_root), capture_root=str(self.review.capture_root),
                    original_preparation=p, original_task=self._one('rc7_task', task_id=p['workitem_id']),
                    original_binding=self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id']),
                    case_snapshot=case, captured_evidence=captures, state='PLANNED'))
            p = self._audit(row)
            # The durable signed intent suspends cold restoration before any
            # local projection changes. A replay never renews execution rights.
            self.preparation.authority.revoke_worker_lease(p['task_lease']['lease_id'])
            session = self._one('rc72_worker_session', session_id=p['session_id'])
            if session['state'] == 'ACTIVE':
                self.preparation.lifecycle.checkpoint_and_close(p['session_id'], reason=_REASON)
            if p['status'] != 'DRAINED':
                self.truth.append_atomic('RC72_N7_EXECUTION_PREPARATION_UPSERTED',
                    dict(p, status='DRAINED', artifact_version=p['artifact_version'] + 1))
            row = self._persist(row, state='DRAINED')
            self._audit(row, terminal=True)
            return row


def assert_drained_member(preparation, preparation_id, *, allow_finalized=False):
    row = signed_member_drain(preparation, preparation._one(_KIND, preparation_id=preparation_id))
    review = ExecutionEvidenceReviewService(preparation, adapter_output_root=row['adapter_output_root'],
                                           capture_root=row['capture_root'])
    return ExecutionMemberDrainService(review).assert_drained(preparation_id, allow_finalized=allow_finalized)


install_rc72_n7_member_drain_overlay()
