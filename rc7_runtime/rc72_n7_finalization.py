"""Actual independent reviewer process -> evidence-backed N7 completion.

Only signed formal Runner proof and a complete current evidence bundle can enter
this surface. No caller supplies a verdict. Partial writes resume without another
business execution, reviewer process, WorkItem or Attempt.
"""
from copy import deepcopy
from dataclasses import fields
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys

from rc6_runtime import contracts, truth as registry
from rc6_runtime.process_environment import scoped_process_environment
from .models import Artifact, Evaluation, EvaluationResult, Evidence, TaskStatus, ContractError
from .control_plane import WorkerOutput
from .closed_loop_control import ClosedLoopControlPlane
from .rc72_domain import AutonomousMissionNode, MissionNodeState, NodeGate, NodeGateDecision
from .rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from .rc72_n7_evidence_review import _CRITERIA
from .rc72_n7_execution_admission import _hash
from .truth_overlay import install_rc7_truth_overlay

_KIND = 'rc72_n7_execution_review'
_EVENT = 'RC72_N7_EXECUTION_REVIEW_UPSERTED'


class ExecutionFinalizationError(ContractError):
    pass


def _validate(payload):
    out = deepcopy(payload)
    for key in ('review_result_id', 'release_id', 'source_commit', 'bundle_id', 'bundle_sha256',
                'delivery_id', 'review_id', 'reviewer_worker_id', 'reviewer_session_id', 'signature'):
        contracts._require_str(out, key)
    if out.get('purpose') != 'N7_INDEPENDENT_PROCESS_REVIEW' or out.get('verdict') not in {'PASS', 'BLOCKED'}:
        raise contracts.DomainValidationError('N7_PROCESS_REVIEW_RESULT_INVALID')
    if not isinstance(out.get('pid'), int) or out['pid'] <= 0:
        raise contracts.DomainValidationError('N7_PROCESS_REVIEW_PID_REQUIRED')
    for key in ('field_verified', 'bank_final', 'delivery_authorized'):
        if key in out:
            raise contracts.DomainValidationError('N7_PROCESS_REVIEW_FIELD_CLAIM_FORBIDDEN')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n7_finalization_overlay():
    install_rc7_truth_overlay()
    contracts.VALIDATORS[_KIND] = _validate
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'review_result_id')
    registry.BUCKETS[_KIND] = 'rc72_n7_execution_reviews'
    registry.IDENTITY_FIELDS[_KIND] = 'review_result_id'


class ExecutionFinalizationService:
    def __init__(self, evidence_review, *, timeout_seconds=30):
        install_rc72_n7_finalization_overlay()
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
            raise ExecutionFinalizationError('N7_REVIEW_TIMEOUT_INVALID')
        self.review = evidence_review
        self.preparation, self.truth = evidence_review.preparation, evidence_review.truth
        self.timeout = timeout_seconds

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _verify(self, receipt):
        signed = {k: v for k, v in receipt.items() if k not in {'signature', 'artifact_version', 'artifact_type'}}
        if not hmac.compare_digest(receipt['signature'], self.preparation.authority._sign(signed)):
            raise ExecutionFinalizationError('N7_REVIEW_SIGNATURE_INVALID')
        # P1-6: a valid signature and digest are necessary but not enough.
        # The signed review must bind the exact isolated reviewer process
        # output, never an unrelated (even byte-identical) file:// reference.
        # Keep the legacy RC7.2 on-disk URI spelling for cold R1 receipts.
        for key, name in (('stdout', 'stdout.json'), ('stderr', 'stderr.log')):
            path = self.review.capture_root / 'reviews' / receipt['review_id'] / name
            if receipt.get(key + '_ref') != 'file://' + str(path):
                raise ExecutionFinalizationError('N7_REVIEW_PROCESS_EVIDENCE_SCOPE_CHANGED')
            if path.is_symlink() or path.parent.is_symlink():
                raise ExecutionFinalizationError('N7_REVIEW_PROCESS_EVIDENCE_SYMLINK_FORBIDDEN')
            try:
                path.resolve().relative_to(self.review.capture_root.resolve())
            except ValueError:
                raise ExecutionFinalizationError('N7_REVIEW_PROCESS_EVIDENCE_OUTSIDE_CAPTURE')
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt[key + '_sha256']:
                raise ExecutionFinalizationError('N7_REVIEW_PROCESS_EVIDENCE_CHANGED')
        return receipt

    def _run_review(self, bundle, assignment):
        root = self.review.capture_root / 'reviews' / assignment['review_id']
        root.mkdir(parents=True, exist_ok=True)
        request = dict(bundle=bundle, **{key: assignment[key] for key in
            ('review_id', 'reviewer_worker_id', 'reviewer_session_id')})
        data = json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
        input_path = root / (hashlib.sha256(data).hexdigest() + '.json')
        self.review._capture(input_path, data, hashlib.sha256(data).hexdigest())
        command = [sys.executable, '-I', str(Path(__file__).with_name('rc72_review_worker.py')), str(input_path)]
        env = scoped_process_environment(home=root / 'process-home')
        child = subprocess.Popen(command, cwd=str(root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = child.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            stderr += '\nREVIEW_PROCESS_TIMEOUT'
        stdout_path, stderr_path = root / 'stdout.json', root / 'stderr.log'
        stdout_path.write_text(stdout, encoding='utf-8')
        stderr_path.write_text(stderr, encoding='utf-8')
        try:
            result = json.loads(stdout)
        except (ValueError, TypeError):
            result = {}
        expected = dict(bundle_id=bundle['bundle_id'], bundle_sha256=bundle['bundle_sha256'],
            review_id=assignment['review_id'], reviewer_worker_id=assignment['reviewer_worker_id'],
            reviewer_session_id=assignment['reviewer_session_id'], passed=True, failures=[],
            observed_files=sorted(row['evidence_id'] for case in bundle['case_results'] for row in case['captured_evidence']))
        passing = child.returncode == 0 and result == expected
        # Recheck all live source/identity/receipt/file facts after the child exits.
        self.review.assert_current(bundle['bundle_id'])
        receipt = dict(review_result_id='N7REVIEW-' + _hash([bundle['bundle_id'], assignment['review_id']])[:24],
            purpose='N7_INDEPENDENT_PROCESS_REVIEW', release_id=bundle['release_id'], source_commit=bundle['source_commit'],
            bundle_id=bundle['bundle_id'], bundle_sha256=bundle['bundle_sha256'], delivery_id=assignment['delivery_id'],
            review_id=assignment['review_id'], reviewer_worker_id=assignment['reviewer_worker_id'],
            reviewer_session_id=assignment['reviewer_session_id'], pid=child.pid, exit_code=child.returncode,
            verdict='PASS' if passing else 'BLOCKED', process_result=result,
            input_sha256=hashlib.sha256(data).hexdigest(), command=command,
            stdout_ref='file://' + str(stdout_path), stderr_ref='file://' + str(stderr_path),
            stdout_sha256=hashlib.sha256(stdout_path.read_bytes()).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr_path.read_bytes()).hexdigest())
        receipt['signature'] = self.preparation.authority._sign(receipt)
        receipt['artifact_version'] = 1
        self.truth.append_atomic(_EVENT, receipt)
        return self._one(_KIND, review_result_id=receipt['review_result_id'])

    def audit(self, bundle_id):
        """Verify completed native acceptance without repairing or writing it."""
        receipt = self._verify(self._one(_KIND, bundle_id=bundle_id))
        bundle = self.review.assert_current(bundle_id, allow_finalized=True)
        if (receipt['verdict'] != 'PASS' or bundle['known_gaps']
                or receipt['release_id'] != bundle['release_id']
                or receipt['source_commit'] != bundle['source_commit']
                or receipt['bundle_sha256'] != bundle['bundle_sha256']):
            raise ExecutionFinalizationError('N7_ACCEPTED_REVIEW_REQUIRED')
        gate_id = 'N7GATE-' + _hash([receipt['review_result_id'], bundle_id])[:24]
        gate = self._one('rc72_node_gate', gate_id=gate_id)
        node = self.review.runtime.node_by_type(bundle['mission_id'], AutonomousMissionNode.N7_EXECUTION)
        delivery = self._one('rc72_node_delivery', delivery_id=receipt['delivery_id'])
        evidence_id = 'N7REVIEW-EV-' + _hash([receipt['review_result_id'], receipt['stdout_sha256']])[:24]
        if (node['state'] != 'PASS' or gate_id not in node['gate_refs']
                or gate['decision'] != 'PASS' or gate['delivery_id'] != receipt['delivery_id']
                or gate['reviewer_worker_id'] != receipt['reviewer_worker_id']
                or gate['reviewer_session_id'] != receipt['reviewer_session_id']
                or gate['criteria'] != _CRITERIA or gate['passed'] != _CRITERIA
                or gate['evidence_refs'] != [evidence_id]
                or delivery['delivery_id'] not in node['delivery_refs']
                or delivery['version'] != node['active_delivery_version']
                or delivery['artifact_refs'] != [bundle_id]):
            raise ExecutionFinalizationError('N7_ACCEPTED_GATE_REQUIRED')
        review_evidence = self._one('rc7_evidence', evidence_id=evidence_id)
        canonical_evidence = self._one('evidence', id=evidence_id)
        expected_delivery = dict(mission_id=bundle['mission_id'], mission_node_id=node['mission_node_id'],
            node_type='N7_EXECUTION', producer_ref='runtime://signed-n7-evidence',
            artifact_refs=[bundle_id], input_refs=[bundle['plan_id']], known_gaps=[],
            created_by_workitems=sorted(c['workitem_id'] for c in bundle['case_results']),
            evidence_refs=sorted({ref for c in bundle['case_results'] for ref in
                c['observation_evidence_refs'] + [c['cleanup_evidence_ref']] +
                [r['evidence_id'] for r in c['captured_evidence']]}))
        if (any(delivery.get(k) != v for k, v in expected_delivery.items())
                or gate['mission_id'] != bundle['mission_id'] or gate['mission_node_id'] != node['mission_node_id']
                or gate['node_type'] != 'N7_EXECUTION'
                or review_evidence.get('mission_id') != bundle['mission_id']
                or review_evidence.get('kind') != 'N7_INDEPENDENT_PROCESS_REVIEW'
                or review_evidence.get('source_ref') != 'r1://artifact/' + receipt['review_result_id']
                or review_evidence.get('content_ref') != receipt['stdout_ref']
                or review_evidence.get('content_hash') != receipt['stdout_sha256']
                or review_evidence.get('subject_refs') != [bundle_id]
                or canonical_evidence.get('kind') != 'N7_INDEPENDENT_PROCESS_REVIEW'
                or canonical_evidence.get('ref') != receipt['stdout_ref']
                or canonical_evidence.get('source_artifact_ref') != receipt['review_result_id']):
            raise ExecutionFinalizationError('N7_ACCEPTED_DELIVERY_OR_REVIEW_EVIDENCE_CHANGED')
        for case in bundle['case_results']:
            refs = list(dict.fromkeys(case['observation_evidence_refs'] + [case['cleanup_evidence_ref'], evidence_id]
                       + [row['evidence_id'] for row in case['captured_evidence']]))
            attempt = self._one('execution_attempt', attempt_id=case['attempt_id'])
            p = self._one('rc72_n7_execution_preparation', preparation_id=case['preparation_id'])
            binding = self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
            task = self._one('rc7_task', task_id=case['workitem_id'])
            evaluation_id = 'N7EVAL-' + _hash([receipt['review_result_id'], case['workitem_id']])[:24]
            evaluation = self._one('rc7_evaluation', evaluation_id=evaluation_id)
            artifact_id = 'N7OUT-' + _hash([bundle_id, case['attempt_id']])[:24]
            artifact = self._one('rc7_artifact', artifact_id=artifact_id)
            if (attempt['status'] != 'PASS' or attempt.get('final_review_result_id') != receipt['review_result_id']
                    or attempt.get('evidence_refs') != refs or binding['state'] != 'COMPLETED'
                    or task['state'] != 'PASS' or task.get('evaluation_id') != evaluation_id
                    or evaluation['result'] != 'PASS' or evaluation['evaluator_ref'] != receipt['reviewer_worker_id']
                    or evaluation['artifact_refs'] != [artifact_id] or evaluation['evidence_refs'] != refs
                    or artifact_id not in task['output_artifact_refs']
                    or artifact['producer_task_id'] != task['task_id']
                    or artifact['content_ref'] != 'r1://artifact/' + bundle_id
                    or artifact['content_hash'] != bundle['bundle_sha256'] or artifact['evidence_refs'] != refs
                    or self._one('rc72_worker_session', session_id=case['session_id'])['state'] != 'CLOSED'):
                raise ExecutionFinalizationError('N7_ACCEPTED_CASE_FINALIZATION_REQUIRED')
        reviewer = self._one('rc72_worker_session', session_id=receipt['reviewer_session_id'])
        if any(reviewer.get(k) != v for k, v in dict(state='CLOSED', purpose='REVIEW',
                role='quality-reviewer', worker_id=receipt['reviewer_worker_id'], mission_id=bundle['mission_id'],
                mission_node_id=node['mission_node_id'], delivery_id=receipt['delivery_id']).items()):
            raise ExecutionFinalizationError('N7_ACCEPTED_REVIEWER_CLOSURE_REQUIRED')
        return dict(state='N7_PASS', gate_id=gate_id, review_result_id=receipt['review_result_id'],
                    bundle_id=bundle_id, attempt_ids=[case['attempt_id'] for case in bundle['case_results']])

    def finalize(self, bundle_id):
        existing = self.truth.query(_KIND, bundle_id=bundle_id)
        if len(existing) > 1:
            raise ExecutionFinalizationError('N7_REVIEW_RESULT_NOT_UNIQUE')
        receipt = self._verify(existing[0]) if existing else None
        bundle = self.review.assert_current(bundle_id, allow_finalized=receipt is not None)
        if bundle['known_gaps']:
            raise ExecutionFinalizationError('N7_FORMAL_TARGET_OR_RUNNER_PROOF_REQUIRED')
        if receipt is None:
            assignment = self.review.request_review(bundle_id)
            receipt = self._run_review(bundle, assignment)
        if receipt['verdict'] != 'PASS':
            return dict(state='BLOCKED', review_result_id=receipt['review_result_id'])
        if (receipt['release_id'] != bundle['release_id'] or receipt['source_commit'] != bundle['source_commit']
                or receipt['bundle_sha256'] != bundle['bundle_sha256']):
            raise ExecutionFinalizationError('N7_REVIEW_BUNDLE_BINDING_MISMATCH')
        evidence_id = 'N7REVIEW-EV-' + _hash([receipt['review_result_id'], receipt['stdout_sha256']])[:24]
        self.review.evidence._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
            evidence_id=evidence_id, release_id=bundle['release_id'], mission_id=bundle['mission_id'],
            kind='N7_INDEPENDENT_PROCESS_REVIEW', source_ref='r1://artifact/' + receipt['review_result_id'],
            content_ref=receipt['stdout_ref'], content_hash=receipt['stdout_sha256'], subject_refs=[bundle_id], artifact_version=1))
        self.review.evidence._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(
            id=evidence_id, release_id=bundle['release_id'], kind='N7_INDEPENDENT_PROCESS_REVIEW',
            ref=receipt['stdout_ref'], source_artifact_ref=receipt['review_result_id'], artifact_version=1))
        control = ClosedLoopControlPlane(self.truth, bundle['release_id'], bundle['mission_id'])
        for case in bundle['case_results']:
            attempt = self._one('execution_attempt', attempt_id=case['attempt_id'])
            refs = list(dict.fromkeys(case['observation_evidence_refs'] + [case['cleanup_evidence_ref'], evidence_id]
                       + [row['evidence_id'] for row in case['captured_evidence']]))
            if attempt.get('final_review_result_id') != receipt['review_result_id']:
                if attempt['status'] != 'BLOCKED':
                    raise ExecutionFinalizationError('N7_ATTEMPT_FINALIZATION_CONFLICT')
                updated = dict(attempt, status='PASS', reason='INDEPENDENT_EVIDENCE_REVIEW_PASSED',
                    observation_evidence_refs=case['observation_evidence_refs'], evidence_refs=refs,
                    final_review_result_id=receipt['review_result_id'], artifact_version=attempt['artifact_version'] + 1)
                self.truth.append_atomic('EXECUTION_ATTEMPT_UPSERTED', updated)
            else:
                if attempt['status'] != 'PASS' or attempt.get('evidence_refs') != refs:
                    raise ExecutionFinalizationError('N7_FINALIZED_ATTEMPT_EVIDENCE_CONFLICT')
            p = self._one('rc72_n7_execution_preparation', preparation_id=case['preparation_id'])
            binding = self._one('rc72_workitem_attempt_binding', binding_id=p['binding_id'])
            if binding['state'] != 'COMPLETED':
                entity = WorkItemAttemptBinding(**{field.name: binding[field.name] for field in fields(WorkItemAttemptBinding) if field.name in binding})
                entity.state = WorkItemAttemptState.COMPLETED
                self.preparation.lifecycle.repository.persist(entity, artifact_version=binding['artifact_version'] + 1)
            task = self._one('rc7_task', task_id=case['workitem_id'])
            artifact_id = 'N7OUT-' + _hash([bundle_id, case['attempt_id']])[:24]
            if task['state'] == 'RUNNING':
                prior = self.truth.query('rc7_artifact', artifact_id=artifact_id)
                kwargs = dict(created_at=prior[0]['created_at']) if prior else {}
                artifact = Artifact(artifact_id=artifact_id, mission_id=bundle['mission_id'], artifact_type='RC72_EXECUTION_RESULT',
                    producer_task_id=task['task_id'], content_ref='r1://artifact/' + bundle_id,
                    content_hash=bundle['bundle_sha256'], parent_refs=task['input_artifact_refs'], evidence_refs=refs, **kwargs)
                control.submit_worker_output(WorkerOutput(task_id=task['task_id'], worker_ref=case['worker_id'], artifacts=(artifact,)))
                task = self._one('rc7_task', task_id=case['workitem_id'])
            evaluation_id = 'N7EVAL-' + _hash([receipt['review_result_id'], case['workitem_id']])[:24]
            if task['state'] == 'OUTPUT_PRODUCED':
                previous = self.truth.query('rc7_evaluation', evaluation_id=evaluation_id)
                kwargs = dict(created_at=previous[0]['created_at']) if previous else {}
                evaluation = Evaluation(evaluation_id=evaluation_id, mission_id=bundle['mission_id'], node='EXECUTION',
                    artifact_refs=[artifact_id], result=EvaluationResult.PASS, evaluator_ref=receipt['reviewer_worker_id'],
                    dimensions=dict(review_result_id=receipt['review_result_id'], formal_runner_receipt_ref=case['formal_runner_receipt_ref']),
                    evidence_refs=refs, **kwargs)
                control.accept_evaluation(task['task_id'], evaluation=evaluation)
            current = self._one('rc7_task', task_id=case['workitem_id'])
            if current['state'] != 'PASS' or current.get('evaluation_id') != evaluation_id:
                raise ExecutionFinalizationError('N7_WORKITEM_FINALIZATION_CONFLICT')
            accepted = self._one('rc7_evaluation', evaluation_id=evaluation_id)
            if (accepted.get('evaluator_ref') != receipt['reviewer_worker_id'] or accepted.get('result') != 'PASS'
                    or accepted.get('artifact_refs') != [artifact_id] or accepted.get('evidence_refs') != refs):
                raise ExecutionFinalizationError('N7_FINALIZED_WORKITEM_REVIEW_CONFLICT')
            session = self._one('rc72_worker_session', session_id=case['session_id'])
            if session['state'] == 'ACTIVE':
                self.preparation.lifecycle.checkpoint_and_close(case['session_id'], reason='N7 independent review completed')
            self.preparation.authority.revoke_worker_lease(p['task_lease']['lease_id'])
        gate_id = 'N7GATE-' + _hash([receipt['review_result_id'], bundle_id])[:24]
        node = self.review.runtime.node_by_type(bundle['mission_id'], AutonomousMissionNode.N7_EXECUTION)
        gates = self.truth.query('rc72_node_gate', gate_id=gate_id)
        if gates and (len(gates) != 1 or gates[0].get('decision') != 'PASS'
                or gates[0].get('delivery_id') != receipt['delivery_id']
                or gates[0].get('reviewer_worker_id') != receipt['reviewer_worker_id']
                or gates[0].get('reviewer_session_id') != receipt['reviewer_session_id']
                or gates[0].get('passed') != _CRITERIA):
            raise ExecutionFinalizationError('N7_FINALIZED_NODE_GATE_CONFLICT')
        if node['state'] == 'REVIEW_PENDING':
            if gates:
                self.review.runtime._persist_node_state(node, MissionNodeState.PASS, reason='resume accepted N7 review gate',
                    gate_refs=list(dict.fromkeys(node['gate_refs'] + [gate_id])), exited_at=gates[0]['created_at'], bypass_direct_transition=True)
            else:
                self.review.runtime.apply_gate(NodeGate(gate_id=gate_id, mission_id=bundle['mission_id'],
                    mission_node_id=node['mission_node_id'], node_type=AutonomousMissionNode.N7_EXECUTION,
                    delivery_id=receipt['delivery_id'], decision=NodeGateDecision.PASS,
                    reviewer_worker_id=receipt['reviewer_worker_id'], reviewer_session_id=receipt['reviewer_session_id'],
                    criteria=list(_CRITERIA), passed=list(_CRITERIA), evidence_refs=[evidence_id],
                    reason='actual independent process verified complete formal execution evidence'))
        elif node['state'] != 'PASS' or gate_id not in node['gate_refs'] or not gates:
            raise ExecutionFinalizationError('N7_NODE_FINALIZATION_CONFLICT')
        reviewer = self._one('rc72_worker_session', session_id=receipt['reviewer_session_id'])
        if reviewer['state'] == 'ACTIVE':
            self.preparation.lifecycle.checkpoint_and_close(receipt['reviewer_session_id'], reason='independent N7 gate review completed')
        transitions = self.truth.query('rc72_node_transition', source_gate_id=gate_id)
        if not transitions:
            self.review.runtime.forward(AutonomousMissionNode.N7_EXECUTION, AutonomousMissionNode.N9_DEFECT,
                source_gate_id=gate_id, mission_id=bundle['mission_id'])
        return dict(state='N7_PASS', gate_id=gate_id, review_result_id=receipt['review_result_id'],
                    attempt_ids=[case['attempt_id'] for case in bundle['case_results']],
                    next_node='N9_DEFECT', field_verified=False, bank_final=False)


install_rc72_n7_finalization_overlay()
