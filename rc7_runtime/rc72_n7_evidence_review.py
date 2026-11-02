"""Whole-plan N7 evidence capture and fresh review admission.

No evidence label, path, checksum or adapter success flag grants a Case PASS.
This service captures actual files for every frozen evidence requirement and
submits the whole Case denominator for review. Target/runner gaps stay explicit.
"""
from copy import deepcopy
import hashlib
import os
import tempfile
from pathlib import Path

from rc6_runtime import contracts, truth as registry
from .models import ContractError
from .oracle_runtime import DeterministicOracleRuntime
from .rc72_canonical_design import CanonicalDesignService
from .rc72_domain import AutonomousMissionNode, NodeDelivery, MissionNodeState
from .rc72_n7_cleanup import frozen_cleanup_spec
from .rc72_n7_execution_admission import _hash
from .rc72_n7_execution_evidence import ExecutionEvidenceService
from .rc72_state_machine import RC72StateMachine
from .truth_overlay import install_rc7_truth_overlay

_KIND = 'rc72_n7_evidence_bundle'
_EVENT = 'RC72_N7_EVIDENCE_BUNDLE_UPSERTED'
_GAPS = ['FULL_TARGET_IDENTITY_BINDING_REQUIRED', 'APPROVED_RUNNER_RECEIPT_REQUIRED']
_CRITERIA = ['COMPLETE_CASE_DENOMINATOR', 'CURRENT_APPROVED_SOURCES', 'EXACT_ATTEMPT_LINEAGE',
             'BUSINESS_ORACLE', 'CLEANUP_AND_RESOURCE_RELEASE', 'REQUIRED_EVIDENCE_BYTES',
             'FULL_TARGET_IDENTITY', 'APPROVED_RUNNER_RECEIPT']


class EvidenceReviewError(ContractError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _validate(payload):
    out = deepcopy(payload)
    for key in ('bundle_id', 'release_id', 'source_commit', 'release_batch_id', 'mission_id',
                'plan_id', 'input_digest', 'bundle_sha256'):
        contracts._require_str(out, key)
    if out.get('state') != 'EVIDENCE_READY_FOR_REVIEW' or not isinstance(out.get('case_results'), list) or not out['case_results']:
        raise contracts.DomainValidationError('N7_EVIDENCE_BUNDLE_CASES_REQUIRED')
    contracts._require_string_list(out, 'known_gaps')
    core = {k: v for k, v in out.items() if k not in {'bundle_id', 'bundle_sha256', 'artifact_type', 'artifact_version'}}
    if out['bundle_sha256'] != _hash(core) or out['bundle_id'] != 'N7BUNDLE-' + out['bundle_sha256'][:24]:
        raise contracts.DomainValidationError('N7_EVIDENCE_BUNDLE_DIGEST_INVALID')
    for key in ('passed', 'field_verified', 'bank_final', 'case_pass', 'n7_pass'):
        if key in out:
            raise contracts.DomainValidationError('N7_EVIDENCE_BUNDLE_PREMATURE_CLAIM')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n7_evidence_review_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'bundle_id')
    registry.BUCKETS[_KIND] = 'rc72_n7_evidence_bundles'
    registry.IDENTITY_FIELDS[_KIND] = 'bundle_id'


class ExecutionEvidenceReviewService:
    def __init__(self, preparation, *, adapter_output_root, capture_root,
                 max_file_bytes=16 * 1024 * 1024, max_bundle_bytes=64 * 1024 * 1024):
        install_rc72_n7_evidence_review_overlay()
        self.preparation, self.truth = preparation, preparation.truth
        self.output_root = Path(adapter_output_root).resolve()
        self.capture_root = Path(capture_root).resolve()
        for limit in (max_file_bytes, max_bundle_bytes):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise EvidenceReviewError('N7_EVIDENCE_CAPTURE_LIMIT_INVALID')
        self.max_file_bytes, self.max_bundle_bytes = max_file_bytes, max_bundle_bytes
        for child, parent in ((self.output_root, self.capture_root), (self.capture_root, self.output_root)):
            try:
                child.relative_to(parent)
            except ValueError:
                continue
            raise EvidenceReviewError('N7_CAPTURE_ROOT_MUST_BE_SEPARATE')
        self.evidence = ExecutionEvidenceService(preparation)
        self.runtime = RC72StateMachine(self.truth, release_id=preparation.release_id)

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _cleanup_proof(self, p, c):
        cleanup, verification = frozen_cleanup_spec(c)
        calls = []
        for phase, tool in (('CLEANUP', cleanup['tool']), ('VERIFY', verification['tool'])):
            call_id = 'N7CLEAN-' + _hash([p['preparation_id'], c['contract_sha256'], phase, tool])[:24]
            row = self._one('rc72_n7_cleanup_call', call_id=call_id)
            context = {key: deepcopy(p[key]) for key in ('workitem_id', 'attempt_id', 'worker_id',
                        'session_id', 'data_lease_ids', 'browser_lease_ids')}
            context.update(phase=phase, cleanup_receipt_ref=calls[0]['call_id'] if calls else None)
            if (row['state'] != 'RETURNED' or row['tool'] not in p['task_lease']['allowed_tools']
                    or row['phase'] != phase or row['tool'] != tool
                    or any(row.get(k) != p[k] for k in ('preparation_id', 'release_id', 'source_commit', 'attempt_id', 'worker_id', 'contract_id'))
                    or row['contract_sha256'] != c['contract_sha256']
                    or row['request_sha256'] != _hash({'contract': c, 'context': context})
                    or row['receipt_sha256'] != _hash(row['raw_result'])):
                raise EvidenceReviewError('N7_REVIEW_CLEANUP_RECEIPT_INVALID')
            calls.append(row)
        action, observed = calls
        actual = observed['raw_result'].get('data_results')
        refs = sorted(ref['data_ref'] for ref in c['data_refs'])
        if not isinstance(actual, dict) or set(actual) != set(refs):
            raise EvidenceReviewError('N7_REVIEW_CLEANUP_DENOMINATOR_MISMATCH')
        results = {ref: DeterministicOracleRuntime().evaluate(verification, actual[ref],
            {'attempt_id': p['attempt_id'], 'data_ref': ref, 'cleanup_call_ref': action['call_id'],
             'verification_call_ref': observed['call_id'], 'receipt_sha256': observed['receipt_sha256']}) for ref in refs}
        if not all(result['passed'] for result in results.values()):
            raise EvidenceReviewError('N7_REVIEW_CLEANUP_NOT_VERIFIED')
        proof_id = 'N7CLEANEV-' + _hash([p['attempt_id'], action['receipt_sha256'], observed['receipt_sha256'], results])[:24]
        proof = self._one('rc7_evidence', evidence_id=proof_id)
        canonical = self._one('evidence', id=proof_id)
        if (proof.get('mission_id') != p['mission_id'] or proof.get('data_assertions') != results
                or proof.get('content_hash') != _hash(results) or canonical.get('attempt_id') != p['attempt_id']):
            raise EvidenceReviewError('N7_REVIEW_CLEANUP_PROOF_INVALID')
        expected_data = dict(zip(p['data_lease_ids'], sorted(c['data_refs'], key=lambda ref: ref['data_ref'])))
        if len(expected_data) != len(c['data_refs']):
            raise EvidenceReviewError('N7_REVIEW_DATA_LEASE_DENOMINATOR_MISMATCH')
        for kind, key, ids in (('rc72_data_lease', 'data_lease_id', p['data_lease_ids']),
                               ('rc72_browser_lease', 'browser_lease_id', p['browser_lease_ids'])):
            for lease_id in ids:
                lease = self._one(kind, **{key: lease_id})
                if (any(lease.get(k) != p[k] for k in ('mission_id', 'workitem_id', 'attempt_id', 'worker_id'))
                        or lease['state'] != 'RELEASED' or lease.get('release_reason') != 'verified N7 cleanup evidence ' + proof_id
                        or (kind == 'rc72_data_lease' and (lease.get('cleanup_evidence_ref') != proof_id
                            or lease.get('data_ref') != expected_data[lease_id]['data_ref']))):
                    raise EvidenceReviewError('N7_REVIEW_RESOURCES_NOT_RELEASED')
        return proof_id

    def _snapshot(self, plan_id, *, allow_finalized=False):
        plan = self._one('rc72_n7_execution_plan', plan_id=plan_id)
        if plan['release_id'] != self.preparation.release_id or plan['source_commit'] != self.preparation.source_commit:
            raise EvidenceReviewError('N7_REVIEW_SOURCE_MISMATCH')
        node = self.runtime.node_by_type(plan['mission_id'], AutonomousMissionNode.N7_EXECUTION)
        allowed_nodes = {'RUNNING', 'REVIEW_PENDING', 'PASS'} if allow_finalized else {'RUNNING', 'REVIEW_PENDING'}
        if node['state'] not in allowed_nodes:
            raise EvidenceReviewError('N7_REVIEW_NODE_NOT_ACTIVE')
        design = CanonicalDesignService(self.truth, release_id=plan['release_id'],
            source_commit=plan['source_commit']).load(release_batch_id=plan['release_batch_id'])
        cases = {case['tc_id']: case for case in design.cases}
        if len(plan['items']) != len(cases) or {item['case_id'] for item in plan['items']} != set(cases):
            raise EvidenceReviewError('N7_REVIEW_CASE_DENOMINATOR_MISMATCH')
        result = []
        for item in sorted(plan['items'], key=lambda item: item['case_id']):
            prepared = self.truth.query('rc72_n7_execution_preparation', plan_id=plan_id,
                                        workitem_id=item['workitem_id'], status='PREPARED')
            if len(prepared) != 1:
                raise EvidenceReviewError('N7_REVIEW_CASE_EXECUTION_REQUIRED')
            p, c, binding, admission, dispatch, oracle = self.evidence.observation(prepared[0]['preparation_id'])
            if (p['case_id'] != item['case_id'] or p['contract_id'] != item['contract_id']
                    or p['admission_id'] != item['admission_id'] or p['etu_id'] != item['etu_id']
                    or p['mission_id'] != plan['mission_id'] or binding['state'] not in ({'EVIDENCE_READY', 'COMPLETED'} if allow_finalized else {'EVIDENCE_READY'})
                    or cases[p['case_id']]['source_case_sha256'] not in c['authoritative_sources']):
                raise EvidenceReviewError('N7_REVIEW_CASE_BINDING_INVALID')
            for parent in admission['upstream_refs']:
                current = self.preparation.planning.admission._active_pass(p['mission_id'], p['release_batch_id'],
                    AutonomousMissionNode(parent['node_type']))
                if parent['digest'] != _hash(list(current)):
                    raise EvidenceReviewError('N7_REVIEW_UPSTREAM_CHANGED')
            if dispatch['state'] != 'RETURNED' or not oracle or not oracle['passed']:
                raise EvidenceReviewError('N7_REVIEW_BUSINESS_RESULT_NOT_PASSING')
            task = self._one('rc7_task', task_id=p['workitem_id'])
            allowed_tasks = {'RUNNING', 'OUTPUT_PRODUCED', 'EVALUATING', 'PASS'} if allow_finalized else {'RUNNING'}
            if (task['state'] not in allowed_tasks or task.get('lease_owner') != p['worker_id']
                    or task.get('mission_id') != plan['mission_id']
                    or task.get('input_artifact_refs') != item['input_artifact_refs']):
                raise EvidenceReviewError('N7_REVIEW_WORKITEM_NOT_CURRENT')
            attempt = self._one('execution_attempt', attempt_id=p['attempt_id'])
            assertion = self._one('assertion', id=attempt['assertion_ref'])
            expected_assertion = 'N7ASSERT-' + _hash([p['attempt_id'], oracle])[:24]
            if (attempt['assertion_ref'] != expected_assertion
                    or attempt.get('tool_call_refs') != [dispatch['dispatch_id']]
                    or attempt.get('contract_sha256') != c['contract_sha256']
                    or assertion.get('details') != oracle['details']
                    or assertion.get('evidence_refs') != attempt.get('observation_evidence_refs', attempt['evidence_refs'])
                    or attempt.get('actual_result') != dispatch['raw_result'] or attempt.get('worker_id') != p['worker_id']
                    or assertion.get('attempt_id') != p['attempt_id'] or assertion.get('passed') is not True
                    or assertion.get('oracle_ref') != oracle['assertion_ref']):
                raise EvidenceReviewError('N7_REVIEW_ATTEMPT_ASSERTION_MISMATCH')
            from .rc72_formal_runner import verified_formal_receipt
            formal = verified_formal_receipt(self.preparation, p, c, dispatch['raw_result'])
            if formal and (formal['runner_result']['exit_code'] != 0 or not formal['required_tool_observed']):
                raise EvidenceReviewError('N7_REVIEW_FORMAL_RUNNER_INTEGRITY_FAILED')
            proof_id = self._cleanup_proof(p, c)
            required = c['evidence_required']
            declarations = dispatch['raw_result'].get('evidence')
            if (not all(isinstance(label, str) and label.strip() for label in required)
                    or len(set(required)) != len(required) or not isinstance(declarations, list)
                    or len(declarations) != len(required) or not all(isinstance(row, dict) and isinstance(row.get('requirement'), str) for row in declarations)
                    or {row.get('requirement') for row in declarations} != set(required)):
                raise EvidenceReviewError('N7_REQUIRED_EVIDENCE_DENOMINATOR_MISMATCH')
            for declared in declarations:
                if (declared.get('attempt_id') != p['attempt_id'] or declared.get('tool') != dispatch['tool']
                        or not isinstance(declared.get('path'), str) or not declared['path']
                        or not isinstance(declared.get('sha256'), str) or len(declared['sha256']) != 64
                        or any(ch not in '0123456789abcdef' for ch in declared['sha256'])):
                    raise EvidenceReviewError('N7_REQUIRED_EVIDENCE_BINDING_INVALID')
            result.append(dict(case_id=p['case_id'], workitem_id=p['workitem_id'], preparation_id=p['preparation_id'],
                attempt_id=p['attempt_id'], worker_id=p['worker_id'], session_id=p['session_id'],
                contract_id=c['contract_id'], contract_sha256=c['contract_sha256'], dispatch_id=dispatch['dispatch_id'],
                receipt_sha256=dispatch['receipt_sha256'], assertion_ref=attempt['assertion_ref'],
                observation_evidence_refs=attempt.get('observation_evidence_refs', attempt['evidence_refs']), cleanup_evidence_ref=proof_id,
                formal_runner_receipt_ref=formal['runner_receipt_id'] if formal else None,
                formal_proof_gaps=[] if formal else list(_GAPS),
                evidence_declarations=sorted(declarations, key=lambda row: row['requirement'])))
        return plan, result

    def _file_bytes(self, declared):
        path = (self.output_root / declared['path']).resolve()
        try:
            path.relative_to(self.output_root)
        except ValueError as exc:
            raise EvidenceReviewError('N7_EVIDENCE_PATH_OUTSIDE_ADAPTER_OUTPUT') from exc
        if not path.is_file():
            raise EvidenceReviewError('N7_REQUIRED_EVIDENCE_FILE_MISSING')
        with path.open('rb') as source:
            data = source.read(self.max_file_bytes + 1)
        if len(data) > self.max_file_bytes:
            raise EvidenceReviewError('N7_EVIDENCE_FILE_SIZE_LIMIT_EXCEEDED')
        if not data or _sha(data) != declared['sha256']:
            raise EvidenceReviewError('N7_REQUIRED_EVIDENCE_FILE_DIGEST_MISMATCH')
        return data

    def _capture(self, destination, data, digest):
        # Publish complete bytes atomically without replacing an existing blob.
        # A crash before link leaves no half-written canonical evidence file.
        fd, temporary = tempfile.mkstemp(prefix='.capture-', dir=str(self.capture_root))
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            try:
                os.link(temporary, str(destination))
            except FileExistsError:
                if destination.is_symlink():
                    raise EvidenceReviewError('N7_CAPTURE_STORE_SYMLINK_FORBIDDEN')
                if not destination.is_file() or _sha(destination.read_bytes()) != digest:
                    raise EvidenceReviewError('N7_CAPTURE_STORE_DIGEST_MISMATCH')
        finally:
            Path(temporary).unlink(missing_ok=True)

    def build(self, plan_id):
        plan, cases = self._snapshot(plan_id)
        input_digest = _hash([plan_id, cases])
        existing = self.truth.query(_KIND, plan_id=plan_id, input_digest=input_digest)
        if existing:
            if len(existing) != 1:
                raise EvidenceReviewError('N7_EVIDENCE_BUNDLE_NOT_UNIQUE')
            return self.assert_current(existing[0]['bundle_id'])
        # Preflight the complete denominator before any file or R1 write.
        collected, total_bytes = [], 0
        for case in cases:
            for declared in case['evidence_declarations']:
                data = self._file_bytes(declared)
                total_bytes += len(data)
                if total_bytes > self.max_bundle_bytes:
                    raise EvidenceReviewError('N7_EVIDENCE_BUNDLE_SIZE_LIMIT_EXCEEDED')
                collected.append((case, declared, data))
        self.capture_root.mkdir(parents=True, exist_ok=True)
        captured = {case['case_id']: [] for case in cases}
        for case, declared, data in collected:
            destination = self.capture_root / (declared['sha256'] + '.bin')
            self._capture(destination, data, declared['sha256'])
            evidence_id = 'N7FILE-' + _hash([case['attempt_id'], declared['requirement'], declared['sha256']])[:24]
            ref = 'file://' + str(destination)
            self.evidence._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
                evidence_id=evidence_id, release_id=plan['release_id'], mission_id=plan['mission_id'],
                kind='N7_REQUIRED_EVIDENCE_FILE', source_ref='r1://artifact/' + case['dispatch_id'],
                content_ref=ref, content_hash=declared['sha256'], subject_refs=[case['attempt_id'], case['case_id']],
                evidence_requirement=declared['requirement'], artifact_version=1))
            self.evidence._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(
                id=evidence_id, release_id=plan['release_id'], kind='N7_REQUIRED_EVIDENCE_FILE', ref=ref,
                source_artifact_ref=case['dispatch_id'], tc_id=case['case_id'], attempt_id=case['attempt_id'],
                artifact_version=1))
            captured[case['case_id']].append(dict(evidence_id=evidence_id, requirement=declared['requirement'],
                sha256=declared['sha256'], size_bytes=len(data), content_ref=ref))
        payload = dict(release_id=plan['release_id'], source_commit=plan['source_commit'],
            release_batch_id=plan['release_batch_id'], mission_id=plan['mission_id'], plan_id=plan_id,
            input_digest=input_digest, state='EVIDENCE_READY_FOR_REVIEW',
            case_results=[dict(case, captured_evidence=captured[case['case_id']]) for case in cases],
            known_gaps=[gap for gap in _GAPS if any(gap in case['formal_proof_gaps'] for case in cases)])
        digest = _hash(payload)
        payload.update(bundle_id='N7BUNDLE-' + digest[:24], bundle_sha256=digest, artifact_version=1)
        self.truth.append_atomic(_EVENT, payload)
        return self.assert_current(payload['bundle_id'])

    def assert_current(self, bundle_id, *, allow_finalized=False):
        bundle = self._one(_KIND, bundle_id=bundle_id)
        _validate(bundle)
        plan, cases = self._snapshot(bundle['plan_id'], allow_finalized=allow_finalized)
        if (any(bundle.get(k) != plan[k] for k in ('release_id', 'source_commit', 'release_batch_id', 'mission_id'))
                or bundle['known_gaps'] != [gap for gap in _GAPS if any(gap in case['formal_proof_gaps'] for case in cases)]):
            raise EvidenceReviewError('N7_EVIDENCE_BUNDLE_SCOPE_OR_GAPS_CHANGED')
        if bundle['input_digest'] != _hash([bundle['plan_id'], cases]):
            raise EvidenceReviewError('N7_EVIDENCE_BUNDLE_INPUTS_CHANGED')
        if len(bundle['case_results']) != len(cases):
            raise EvidenceReviewError('N7_EVIDENCE_BUNDLE_CASES_CHANGED')
        for stored, current in zip(bundle['case_results'], cases):
            if any(stored.get(k) != v for k, v in current.items()):
                raise EvidenceReviewError('N7_EVIDENCE_BUNDLE_CASES_CHANGED')
            files = stored.get('captured_evidence', [])
            required = {row['requirement']: row for row in current['evidence_declarations']}
            if len(files) != len(required) or {row['requirement'] for row in files} != set(required):
                raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_DENOMINATOR_MISMATCH')
            for row in files:
                expected_id = 'N7FILE-' + _hash([current['attempt_id'], row['requirement'], row['sha256']])[:24]
                if row['evidence_id'] != expected_id:
                    raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_ID_INVALID')
                expected = self.capture_root / (row['sha256'] + '.bin')
                if row['content_ref'] != 'file://' + str(expected) or row['sha256'] != required[row['requirement']]['sha256']:
                    raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_REF_INVALID')
                if not expected.is_file() or expected.is_symlink():
                    raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_FILE_MISSING')
                if expected.stat().st_size != row['size_bytes']:
                    raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_DIGEST_MISMATCH')
                data = expected.read_bytes()
                if _sha(data) != row['sha256'] or len(data) != row['size_bytes']:
                    raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_DIGEST_MISMATCH')
                proof = self._one('rc7_evidence', evidence_id=row['evidence_id'])
                canonical = self._one('evidence', id=row['evidence_id'])
                if (proof.get('content_hash') != row['sha256'] or proof.get('content_ref') != row['content_ref']
                        or proof.get('mission_id') != plan['mission_id']
                        or proof.get('evidence_requirement') != row['requirement']
                        or proof.get('subject_refs') != [current['attempt_id'], current['case_id']]
                        or canonical.get('attempt_id') != current['attempt_id'] or canonical.get('ref') != row['content_ref']):
                    raise EvidenceReviewError('N7_CAPTURED_EVIDENCE_TRUTH_MISMATCH')
        return bundle

    def request_review(self, bundle_id):
        bundle = self.assert_current(bundle_id)
        node = self.runtime.node_by_type(bundle['mission_id'], AutonomousMissionNode.N7_EXECUTION)
        delivery_id = 'N7DEL-' + _hash([bundle_id, bundle['bundle_sha256']])[:24]
        evidence_refs = sorted({ref for case in bundle['case_results'] for ref in
            case['observation_evidence_refs'] + [case['cleanup_evidence_ref']] +
            [row['evidence_id'] for row in case['captured_evidence']]})
        expected = dict(mission_id=bundle['mission_id'], mission_node_id=node['mission_node_id'],
            node_type=AutonomousMissionNode.N7_EXECUTION.value, producer_ref='runtime://signed-n7-evidence',
            artifact_refs=[bundle_id], evidence_refs=evidence_refs, known_gaps=bundle['known_gaps'],
            created_by_workitems=sorted(case['workitem_id'] for case in bundle['case_results']), input_refs=[bundle['plan_id']])
        deliveries = self.truth.query('rc72_node_delivery', delivery_id=delivery_id)
        if deliveries:
            if len(deliveries) != 1 or any(deliveries[0].get(k) != v for k, v in expected.items()):
                raise EvidenceReviewError('N7_REVIEW_DELIVERY_CONFLICT')
            delivery = deliveries[0]
            if node['state'] == 'RUNNING':
                # Recover a crash after delivery append, before node projection.
                self.runtime._persist_node_state(node, MissionNodeState.REVIEW_PENDING,
                    reason='resume persisted N7 evidence delivery', active_delivery_version=delivery['version'],
                    delivery_refs=list(dict.fromkeys(node['delivery_refs'] + [delivery_id])))
            elif node.get('active_delivery_version') != delivery['version'] or delivery_id not in node['delivery_refs']:
                raise EvidenceReviewError('N7_REVIEW_DELIVERY_NOT_ACTIVE')
        else:
            if node['state'] != 'RUNNING':
                raise EvidenceReviewError('N7_REVIEW_REQUIRES_RUNNING_NODE')
            prior = self.truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
            delivery = NodeDelivery(delivery_id=delivery_id, version=max([r['version'] for r in prior] + [0]) + 1, **expected)
            self.runtime.submit_delivery(delivery)
            delivery = self._one('rc72_node_delivery', delivery_id=delivery_id)
        reviewers = self.truth.query('rc72_reviewer_assignment', delivery_id=delivery_id)
        excluded = {case['session_id'] for case in bundle['case_results']}
        excluded_workers = {case['worker_id'] for case in bundle['case_results']}
        if reviewers:
            if (len(reviewers) != 1 or reviewers[0]['session_id'] in excluded
                    or reviewers[0]['worker_id'] in excluded_workers
                    or reviewers[0].get('criteria') != _CRITERIA or reviewers[0].get('evidence_refs') != evidence_refs):
                raise EvidenceReviewError('N7_INDEPENDENT_REVIEWER_CONFLICT')
            reviewer = reviewers[0]
        else:
            sessions = self.truth.query('rc72_worker_session', delivery_id=delivery_id, purpose='REVIEW')
            if sessions:
                if (len(sessions) != 1 or sessions[0]['session_id'] in excluded
                        or sessions[0]['worker_id'] in excluded_workers or sessions[0]['state'] != 'ACTIVE'):
                    raise EvidenceReviewError('N7_INDEPENDENT_REVIEWER_CONFLICT')
                session = sessions[0]
                if (session['context_bundle'].get('criteria') != _CRITERIA
                        or session['context_bundle'].get('evidence_refs') != evidence_refs):
                    raise EvidenceReviewError('N7_REVIEW_SESSION_CONTEXT_CONFLICT')
                reviewer = dict(review_id='N7REV-' + _hash([delivery_id, session['session_id']])[:24],
                    mission_id=bundle['mission_id'], release_id=bundle['release_id'], worker_id=session['worker_id'],
                    session_id=session['session_id'], team_id=session['team_id'], mission_node_id=node['mission_node_id'],
                    delivery_id=delivery_id, criteria=_CRITERIA, evidence_refs=evidence_refs,
                    context_bundle=session['context_bundle'], created_at=session['created_at'], artifact_version=1)
                self.truth.append_atomic('RC72_REVIEWER_ASSIGNMENT_UPSERTED', reviewer)
            else:
                assignment = self.preparation.lifecycle.assign_fresh_reviewer(mission_id=bundle['mission_id'],
                    team_id='TEAM-' + bundle['mission_id'], mission_node_id=node['mission_node_id'], delivery_id=delivery_id,
                    criteria=_CRITERIA, evidence_refs=evidence_refs, excluded_session_ids=list(excluded))
                reviewer = self._one('rc72_reviewer_assignment', review_id=assignment.review_id)
        session = self._one('rc72_worker_session', session_id=reviewer['session_id'])
        expected_context = dict(mission_id=bundle['mission_id'], team_id='TEAM-' + bundle['mission_id'],
            mission_node_id=node['mission_node_id'], delivery_id=delivery_id, criteria=_CRITERIA, evidence_refs=evidence_refs)
        if (session.get('purpose') != 'REVIEW' or session.get('worker_id') != reviewer['worker_id']
                or session.get('mission_id') != bundle['mission_id'] or session.get('delivery_id') != delivery_id
                or session.get('mission_node_id') != node['mission_node_id']
                or session.get('role') != 'quality-reviewer'
                or session.get('context_bundle') != expected_context or reviewer.get('context_bundle') != expected_context):
            raise EvidenceReviewError('N7_INDEPENDENT_REVIEWER_SESSION_INVALID')
        return dict(bundle_id=bundle_id, delivery_id=delivery_id, review_id=reviewer['review_id'],
                    reviewer_worker_id=reviewer['worker_id'], reviewer_session_id=reviewer['session_id'],
                    state='REVIEW_PENDING', known_gaps=bundle['known_gaps'])


install_rc72_n7_evidence_review_overlay()
