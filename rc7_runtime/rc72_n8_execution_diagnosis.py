"""Actual independent diagnostic process and evidence review for N7 failures.

Directly verified data/tool gaps and complete frozen-contract discrepancies
are routed automatically; a discrepancy is not product causality. Unknown
causality stays BLOCKED; callers cannot supply a classification or approval flag.
"""
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys

from rc6_runtime import contracts, truth as registry
from rc6_runtime.process_environment import scoped_process_environment
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState, NodeDelivery, NodeGate, NodeGateDecision
from .rc72_state_machine import RC72StateMachine, FailureClass
from .rc72_diagnosis_orchestration import DiagnosisOrchestrator
from .rc72_n7_execution_evidence import ExecutionEvidenceService
from .rc72_n7_execution_admission import _hash
from .rc72_formal_runner import preparation_check_specs

_KIND = 'rc72_n8_process_diagnosis'
_EVENT = 'RC72_N8_PROCESS_DIAGNOSIS_UPSERTED'
_CRITERIA = ['EXACT_FAILURE_SCOPE', 'SIGNED_LIVE_FACTS', 'INDEPENDENT_PROCESSES', 'EVIDENCE_BYTES', 'CAUSAL_LIMITS']


def _validate(payload):
    out = deepcopy(payload)
    for key in ('diagnosis_id', 'release_id', 'source_commit', 'preparation_id', 'input_sha256', 'signature'):
        contracts._require_str(out, key)
    if out.get('purpose') != 'N8_ACTUAL_PROCESS_DIAGNOSIS':
        raise contracts.DomainValidationError('N8_PROCESS_PURPOSE_INVALID')
    if any(key in out for key in ('field_verified', 'bank_final', 'delivery_authorized')):
        raise contracts.DomainValidationError('N8_PROCESS_FIELD_CLAIM_FORBIDDEN')
    out.update(artifact_type=_KIND, artifact_version=contracts._artifact_version(out))
    return out


def install_rc72_n8_execution_diagnosis_overlay():
    registry.EVENT_TYPES[_EVENT] = (_KIND, 'diagnosis_id')
    registry.BUCKETS[_KIND] = 'rc72_n8_process_diagnoses'
    registry.IDENTITY_FIELDS[_KIND] = 'diagnosis_id'
    contracts.VALIDATORS[_KIND] = _validate


class ExecutionDiagnosisService:
    def __init__(self, preparation, *, evidence_root, timeout_seconds=30, failure_evidence=None):
        install_rc72_n8_execution_diagnosis_overlay()
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
            raise ContractError('N8_PROCESS_TIMEOUT_INVALID')
        self.preparation, self.truth = preparation, preparation.truth
        if failure_evidence is not None:
            from .rc72_conclusive_failure_evidence import ConclusiveAssertionFailureEvidence
            if (not isinstance(failure_evidence,ConclusiveAssertionFailureEvidence)
                    or failure_evidence.preparation is not preparation):
                raise ContractError('N8_NATIVE_FAILURE_EVIDENCE_REQUIRED')
        self.failure_evidence = failure_evidence
        self.root, self.timeout = Path(evidence_root).resolve(), timeout_seconds
        self.runtime = RC72StateMachine(self.truth, release_id=preparation.release_id)
        self.evidence = ExecutionEvidenceService(preparation)
        self.orchestrator = DiagnosisOrchestrator(self.truth, release_id=preparation.release_id,
            state_machine=self.runtime, worker_lifecycle=preparation.lifecycle)

    def _one(self, kind, **filters):
        return self.preparation._one(kind, **filters)

    def _facts(self, preparation_id):
        p, c, binding, admission, dispatch, oracle = self.evidence.observation(preparation_id)
        attempt = self._one('execution_attempt', attempt_id=p['attempt_id'])
        if attempt['status'] != 'BLOCKED' or attempt['reason'] == 'CLEANUP_AND_EVIDENCE_CLOSURE_REQUIRED':
            raise ContractError('N8_ACTUAL_FAILED_ATTEMPT_REQUIRED')
        checks = []
        expected = preparation_check_specs(c) + [(kind, dict(tool_id=c['tool_route']['tool'])) for kind in ('TOOL_PROBE', 'TOOL_UNAVAILABLE')]
        for evidence_id in attempt['evidence_refs']:
            row = self._one('rc7_evidence', evidence_id=evidence_id)
            if row['kind'] not in {'N7_FORMAL_PRECONDITION', 'N7_FORMAL_DATA_RECHECK', 'N7_FORMAL_TOOL_PROBE', 'N7_FORMAL_TOOL_UNAVAILABLE'}:
                continue
            check = dict(kind=row['kind'][len('N7_FORMAL_'):], spec=row['check_spec'], success=row['check_success'],
                evidence_id=row['evidence_id'], captured_ref=row['content_ref'], sha256=row['content_hash'])
            signed = dict(purpose='N7_LIVE_PREPARATION_CHECK', attempt_id=p['attempt_id'], **check)
            if (not hmac.compare_digest(row.get('check_runtime_signature', ''), self.preparation.authority._sign(signed))
                    or (check['kind'], check['spec']) not in expected
                    or row.get('subject_refs') != [p['attempt_id'], p['case_id']]):
                raise ContractError('N8_LIVE_CHECK_SIGNATURE_OR_SCOPE_INVALID')
            path = Path(check['captured_ref'][len('file://'):])
            if not check['captured_ref'].startswith('file://') or not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != check['sha256']:
                raise ContractError('N8_LIVE_CHECK_BYTES_CHANGED')
            checks.append(check)
        from .rc72_formal_runner import verified_formal_receipt
        verified_formal_receipt(self.preparation, p, c, dispatch.get('raw_result') or {})
        facts = dict(attempt_id=p['attempt_id'], workitem_id=p['workitem_id'], case_id=p['case_id'],
            mission_id=p['mission_id'], contract_id=c['contract_id'], contract_sha256=c['contract_sha256'],
            dispatch_sha256=_hash(dispatch), reason=attempt['reason'], checks=sorted(checks, key=lambda row: row['evidence_id']),
            evidence_refs=attempt['evidence_refs'])
        if self.failure_evidence is not None and self.failure_evidence.rows(preparation_id):
            admitted = self.failure_evidence.audit(preparation_id)
            facts['conclusive_assertion_failure'] = admitted
            facts['evidence_refs'] = list(dict.fromkeys(facts['evidence_refs'] + [admitted['evidence_id'],
                admitted['proof']['case_snapshot']['cleanup_evidence_ref']] +
                [r['evidence_id'] for r in admitted['proof']['captured_evidence']]))
        return p,facts

    def _process(self, request, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(request, sort_keys=True, ensure_ascii=False)
        path.write_text(data, encoding='utf-8')
        child = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('rc72_diagnosis_worker.py')), str(path)],
            cwd=str(path.parent), env=scoped_process_environment(home=path.parent / 'process-home'),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = child.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            raise ContractError('N8_DIAGNOSIS_PROCESS_TIMEOUT')
        out, err = path.with_suffix('.stdout.json'), path.with_suffix('.stderr.log')
        out.write_text(stdout, encoding='utf-8')
        err.write_text(stderr, encoding='utf-8')
        if child.returncode != 0:
            raise ContractError('N8_DIAGNOSIS_PROCESS_FAILED')
        result = json.loads(stdout)
        return result, dict(pid=child.pid, exit_code=child.returncode, request_sha256=hashlib.sha256(data.encode()).hexdigest(),
            stdout_ref='file://' + str(out), stdout_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
            stderr_ref='file://' + str(err), stderr_sha256=hashlib.sha256(err.read_bytes()).hexdigest())

    def _verify(self, receipt):
        signed = {key: value for key, value in receipt.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
        if not hmac.compare_digest(receipt['signature'], self.preparation.authority._sign(signed)):
            raise ContractError('N8_PROCESS_RECEIPT_SIGNATURE_INVALID')
        for process in (receipt['diagnostic_process'], receipt['review_process']):
            for stream in ('stdout', 'stderr'):
                path = Path(process[stream + '_ref'][len('file://'):])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != process[stream + '_sha256']:
                    raise ContractError('N8_PROCESS_EVIDENCE_CHANGED')
        return receipt

    def run(self, preparation_id):
        prepared = self._one('rc72_n7_execution_preparation', preparation_id=preparation_id)
        if not self.truth.query('execution_attempt', attempt_id=prepared['attempt_id']):
            self.evidence.record(preparation_id)
        p, facts = self._facts(preparation_id)
        cases = self.truth.query('rc72_diagnosis_case', source_binding_id=p['binding_id'])
        if not cases:
            if facts.get('conclusive_assertion_failure'):
                self.orchestrator.begin_failure_diagnosis(mission_id=p['mission_id'],team_id='TEAM-'+p['mission_id'],
                    source_binding_id=p['binding_id'],failure_evidence_refs=facts['evidence_refs'],
                    executable_contract_refs=[p['contract_id']],reason=facts['reason'])
            else:
                self.evidence.begin_diagnosis(preparation_id)
        case = self._one('rc72_diagnosis_case', source_binding_id=p['binding_id'])
        if case['failure_evidence_refs'] != facts['evidence_refs'] or case['executable_contract_refs'] != [p['contract_id']]:
            raise ContractError('N8_DIAGNOSIS_INPUT_SCOPE_CHANGED')
        diagnosis_id = case['diagnosis_id']
        digest = _hash(facts)
        receipts = self.truth.query(_KIND, diagnosis_id=diagnosis_id)
        if receipts:
            receipt = self._verify(self._one(_KIND, diagnosis_id=diagnosis_id))
            if receipt['input_sha256'] != digest or receipt['preparation_id'] != preparation_id:
                raise ContractError('N8_DIAGNOSIS_INPUT_CHANGED')
        else:
            session = self._one('rc72_worker_session', session_id=case['diagnosis_session_id'])
            if (session['state'] != 'ACTIVE' or session['purpose'] != 'DIAGNOSIS'
                    or session['worker_id'] == p['worker_id'] or session['session_id'] == p['session_id']
                    or session['source_attempt_id'] != p['attempt_id']):
                raise ContractError('N8_FRESH_DIAGNOSIS_WORKER_REQUIRED')
            request = dict(diagnosis_id=diagnosis_id, input_sha256=digest, facts=facts,
                actor=dict(worker_id=case['diagnosis_worker_id'], session_id=case['diagnosis_session_id']))
            result, process = self._process(request, self.root / diagnosis_id / 'diagnosis.json')
            # The quality actor is assigned against the actual N8 output identity.
            node = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
            delivery_id = 'N8DEL-' + _hash([diagnosis_id, digest])[:24]
            deliveries = self.truth.query('rc72_node_delivery', delivery_id=delivery_id)
            if not deliveries:
                if node['state'] == 'READY':
                    self.runtime.transition_state(node['mission_node_id'], MissionNodeState.RUNNING, reason='actual independent diagnosis output')
                prior = self.truth.query('rc72_node_delivery', mission_node_id=node['mission_node_id'])
                self.runtime.submit_delivery(NodeDelivery(delivery_id=delivery_id, mission_id=p['mission_id'],
                    mission_node_id=node['mission_node_id'], node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
                    version=max([row['version'] for row in prior] + [0]) + 1, producer_ref=case['diagnosis_worker_id'],
                    input_refs=[p['contract_id']], artifact_refs=[diagnosis_id], evidence_refs=facts['evidence_refs']))
            elif node['state'] == 'RUNNING':
                self.runtime._persist_node_state(node, MissionNodeState.REVIEW_PENDING, reason='resume diagnostic delivery',
                    active_delivery_version=deliveries[0]['version'], delivery_refs=list(dict.fromkeys(node['delivery_refs'] + [delivery_id])))
            assignments = self.truth.query('rc72_reviewer_assignment', delivery_id=delivery_id)
            if not assignments:
                self.preparation.lifecycle.assign_fresh_reviewer(mission_id=p['mission_id'], team_id=case['team_id'],
                    mission_node_id=node['mission_node_id'], delivery_id=delivery_id, criteria=_CRITERIA,
                    evidence_refs=facts['evidence_refs'], excluded_session_ids=[p['session_id'], case['diagnosis_session_id']])
            reviewer = self._one('rc72_reviewer_assignment', delivery_id=delivery_id)
            review_session = self._one('rc72_worker_session', session_id=reviewer['session_id'])
            expected_context = dict(mission_id=p['mission_id'], team_id=case['team_id'],
                mission_node_id=node['mission_node_id'], delivery_id=delivery_id,
                criteria=_CRITERIA, evidence_refs=facts['evidence_refs'])
            if (reviewer['worker_id'] in {p['worker_id'], case['diagnosis_worker_id']}
                    or reviewer['session_id'] in {p['session_id'], case['diagnosis_session_id']}
                    or review_session['worker_id'] != reviewer['worker_id'] or review_session['state'] != 'ACTIVE'
                    or review_session['purpose'] != 'REVIEW' or review_session['context_bundle'] != expected_context
                    or reviewer['context_bundle'] != expected_context):
                raise ContractError('N8_INDEPENDENT_REVIEWER_REQUIRED')
            review_request = dict(request, mode='REVIEW', candidate=result,
                actor=dict(worker_id=reviewer['worker_id'], session_id=reviewer['session_id']))
            reviewed, review_process = self._process(review_request, self.root / diagnosis_id / 'review.json')
            if reviewed != dict(accepted=True, diagnosis_id=diagnosis_id, input_sha256=digest):
                raise ContractError('N8_INDEPENDENT_REVIEW_REJECTED')
            if self._facts(preparation_id)[1] != facts:
                raise ContractError('N8_DIAGNOSIS_INPUT_CHANGED_DURING_REVIEW')
            receipt = dict(diagnosis_id=diagnosis_id, purpose='N8_ACTUAL_PROCESS_DIAGNOSIS', release_id=p['release_id'],
                source_commit=p['source_commit'], preparation_id=preparation_id, input_sha256=digest,
                result=result, diagnostic_process=process, review_process=review_process, delivery_id=delivery_id,
                diagnosis_worker_id=case['diagnosis_worker_id'], diagnosis_session_id=case['diagnosis_session_id'],
                reviewer_worker_id=reviewer['worker_id'], reviewer_session_id=reviewer['session_id'])
            receipt['signature'] = self.preparation.authority._sign(receipt)
            self.truth.append_atomic(_EVENT, dict(receipt, artifact_version=1))
            receipt = self._verify(self._one(_KIND, diagnosis_id=diagnosis_id))
        return self._accept(p, case, facts, receipt)

    def request_capability_recovery(self, preparation_id, *, broker):
        """Route a proved physical tool absence to the native policy broker.

        A temporary permission cannot install a missing executable. This intake
        supports denial, specialist delegation and external approval requests;
        none of those decisions proves restoration or retries the old Attempt.
        """
        from .rc72_capability_broker import CapabilityBroker, CapabilityDecision
        if (not isinstance(broker, CapabilityBroker) or broker.authority is not self.preparation.authority
                or broker.release_id != self.preparation.release_id
                or Path(broker.truth.store.path).resolve() != Path(self.truth.store.path).resolve()):
            raise ContractError('N8_CAPABILITY_NATIVE_BROKER_SCOPE_REQUIRED')
        outcome = self.run(preparation_id)
        if outcome['failure_class'] != 'CAPABILITY_GAP' or outcome.get('action') != 'CAPABILITY_BROKER':
            raise ContractError('N8_ACCEPTED_CAPABILITY_DIAGNOSIS_REQUIRED')
        p, facts = self._facts(preparation_id)
        receipt = self._verify(self._one(_KIND, diagnosis_id=outcome['diagnosis_id']))
        if receipt['input_sha256'] != _hash(facts):
            raise ContractError('N8_DIAGNOSIS_INPUT_CHANGED')
        tools = sorted({row['spec']['tool_id'] for row in facts['checks']
                        if row['kind'] == 'TOOL_UNAVAILABLE' and row['success'] is False})
        if len(tools) != 1 or receipt['result']['affected_refs'] != tools:
            raise ContractError('N8_CAPABILITY_EXACT_TOOL_REQUIRED')
        rule = broker.policies.get(tools[0])
        if rule and rule.decision == CapabilityDecision.AUTO_GRANT_TEMP_LEASE:
            raise ContractError('N8_CAPABILITY_PHYSICAL_RESTORATION_REQUIRED')
        return broker.request(request_id='N8CAP-' + _hash([outcome['diagnosis_id'], p['attempt_id'], tools[0]])[:24],
            mission_id=p['mission_id'], workitem_id=p['workitem_id'], attempt_id=p['attempt_id'],
            worker_id=p['worker_id'], parent_task_lease_id=p['task_lease']['lease_id'],
            requested_capability=tools[0], reason='accepted physical tool absence ' + outcome['diagnosis_id'])

    def _fresh_data_repair_proofs(self, p, original_gate_id, failed_refs):
        """Every failed DataRef needs a new independent observation, not a label.

        A new whole-N5 Gate is insufficient if some failed bindings still carry
        pre-failure evidence. Read the accepted native anchor bytes again.
        """
        from .rc72_n5_data_verification_anchor import _strict_final_json
        from .rc72_n5_data_verification_finalization import N5DataVerificationFinalizationService
        from .rc72_n5_existing_data_repair_truth import install_rc72_n5_existing_data_repair_overlay
        from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
        install_rc72_n5_existing_data_repair_overlay()
        original = self._one('rc72_n6_executable_contract', contract_id=p['contract_id'])
        affected = [item for item in original['data_refs'] if item['data_ref'] in failed_refs]
        if {item['data_ref'] for item in affected} != set(failed_refs):
            raise ContractError('N8_REPAIR_FAILED_DATA_SCOPE_UNRESOLVED')
        cutoff = next((event['seq'] for event in self.truth.store.iter_raw()
                       if event.get('entity_type') == 'rc72_node_gate' and event.get('entity_id') == original_gate_id), None)
        if cutoff is None:
            raise ContractError('N8_REPAIR_ORIGINAL_GATE_EVIDENCE_REQUIRED')
        for old in affected:
            binding = self._one('rc72_n5_data_binding', data_requirement_id=old['data_requirement_id'])
            if (binding['data_ref'] != old['data_ref'] or binding.get('verification_blocked_by_anchor')
                    or binding['verification_evidence_refs'] == old['verification_evidence_refs']):
                raise ContractError('N8_REPAIR_FRESH_DATA_OBSERVATION_REQUIRED')
            anchor_id = binding.get('reverification_anchor_id')
            existing = self.truth.query('rc72_n5_existing_data_repair', repair_id=anchor_id) if anchor_id else []
            if existing:
                proof = self._one('rc72_n5_existing_data_repair', repair_id=anchor_id)
                value = {key: item for key, item in proof.items() if key not in {'signature', 'artifact_type', 'artifact_version'}}
                if (not hmac.compare_digest(proof['signature'], self.preparation.authority._sign(value))
                        or proof['state'] != 'VERIFIED' or proof['preparation_id'] != p['preparation_id']
                        or proof['original_binding']['binding_id'] != binding['binding_id']
                        or binding['verification_evidence_refs'] != [proof['evidence_ref']]):
                    raise ContractError('N8_REPAIR_INDEPENDENT_DATA_PROOF_INVALID')
                worker_id, assignment_id = proof['identity']['worker_id'], proof['assignment_id']
                producer = proof.get('producer')
                if producer:
                    producer_path = Path(producer['raw_output_ref'][len('file://'):])
                    if (producer.get('state') not in {'PREPARED', 'REPAIR_REQUIRED'}
                            or producer['identity']['worker_id'] == worker_id
                            or producer['dsh_session_id'] == proof['dsh_session_id']
                            or not producer['raw_output_ref'].startswith('file://') or not producer_path.is_file()
                            or 'sha256:' + hashlib.sha256(producer_path.read_bytes()).hexdigest() != producer['raw_output_sha256']):
                        raise ContractError('N8_REPAIR_DATA_PROOF_BYTES_CHANGED')
                expected_status = 'VERIFIED'
                session_id = proof['dsh_session_id']
            else:
                anchors = self.truth.query('rc72_n5_data_verification_evidence_anchor', anchor_id=anchor_id) if anchor_id else []
                if len(anchors) != 1:
                    raise ContractError('N8_REPAIR_FRESH_DATA_ANCHOR_REQUIRED')
                proof = anchors[0]
                worker_id, assignment_id = proof['verifier_worker_id'], proof['runtime_assignment_id']
                expected_status = 'VERIFIED_CANDIDATE'
                session_id = proof['verifier_dsh_session_id']
            if (proof.get('mission_id') != p['mission_id'] or proof.get('release_id') != p['release_id']
                    or proof.get('source_commit') != p['source_commit']
                    or proof.get('data_requirement_id') != old['data_requirement_id']
                    or proof.get('source_case_sha256') != old['source_case_sha256'] or worker_id == p['worker_id']):
                raise ContractError('N8_REPAIR_INDEPENDENT_DATA_PROOF_INVALID')
            path = Path(proof['raw_output_ref'][len('file://'):])
            if (not proof['raw_output_ref'].startswith('file://') or not path.is_file()
                    or 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() != proof['raw_output_sha256']):
                raise ContractError('N8_REPAIR_DATA_PROOF_BYTES_CHANGED')
            parsed = tuple(DshHeadlessWorkerLauncher._parse_json_lines(path.read_text(encoding='utf-8')))
            semantic = _strict_final_json(parsed)
            if semantic.get('status') != expected_status:
                raise ContractError('N8_REPAIR_INDEPENDENT_DATA_PROOF_INVALID')
            if expected_status == 'VERIFIED':
                if semantic != proof['result'] or semantic.get('data_ref') != old['data_ref']:
                    raise ContractError('N8_REPAIR_INDEPENDENT_DATA_PROOF_INVALID')
            elif N5DataVerificationFinalizationService._canonical_data_ref(semantic.get('candidate_ref')) != old['data_ref']:
                raise ContractError('N8_REPAIR_INDEPENDENT_DATA_PROOF_INVALID')
            handoffs = self.truth.query('agent_runtime_event', mission_id=p['mission_id'],
                attempt_id=proof['verification_attempt_id'], event_name='HANDOFF_RETURNED')
            starts = [event['seq'] for event in self.truth.store.iter_raw()
                if event.get('entity_type') == 'agent_runtime_event'
                and event.get('payload', {}).get('attempt_id') == proof['verification_attempt_id']]
            if (not starts or min(starts) <= cutoff or len(handoffs) != 1
                    or handoffs[0]['worker_instance_id'] != worker_id
                    or handoffs[0]['assignment_id'] != assignment_id or handoffs[0]['result'] != 'PASS'
                    or handoffs[0]['dsh_session_id'] != session_id
                    or DshHeadlessWorkerLauncher._session_id(parsed) != session_id
                    or not DshHeadlessWorkerLauncher._tool_calls(parsed)):
                raise ContractError('N8_REPAIR_POST_GATE_INDEPENDENT_OBSERVATION_REQUIRED')
            for evidence_id in binding['verification_evidence_refs']:
                evidence = self._one('rc7_evidence', evidence_id=evidence_id)
                if (evidence['mission_id'] != p['mission_id'] or evidence['content_ref'] != proof['raw_output_ref']
                        or evidence.get('content_hash') != proof['raw_output_sha256']):
                    raise ContractError('N8_REPAIR_CANONICAL_DATA_PROOF_CHANGED')

    def record_accepted_repair(self, preparation_id, *, repair_delivery_id, changed_refs, reason):
        """Admit only a newer, independently accepted upstream data repair.

        Restoring the live adapter or reusing the pre-failure gate is insufficient.
        This never constructs data, releases owned resources or starts a retry.
        """
        p, facts = self._facts(preparation_id)
        case = self._one('rc72_diagnosis_case', source_binding_id=p['binding_id'])
        receipt = self._verify(self._one(_KIND, diagnosis_id=case['diagnosis_id']))
        if receipt['input_sha256'] != _hash(facts) or receipt['result']['failure_class'] != 'TEST_DATA_GAP':
            raise ContractError('N8_ACCEPTED_DATA_DIAGNOSIS_REQUIRED')
        outcome = self._one('rc72_diagnosis_outcome', diagnosis_id=case['diagnosis_id'])
        if outcome['responsible_node'] != 'N5_TEST_DATA' or outcome['action'] != 'SEMANTIC_BACK_EDGE':
            raise ContractError('N8_ACCEPTED_DATA_BACK_EDGE_REQUIRED')
        admission = self._one('rc72_n7_execution_admission', admission_id=p['admission_id'])
        original = next(row for row in admission['upstream_refs'] if row['node_type'] == 'N5_TEST_DATA')
        original_delivery = self._one('rc72_node_delivery', delivery_id=original['delivery_id'])
        delivery = self._one('rc72_node_delivery', delivery_id=repair_delivery_id)
        node = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N5_TEST_DATA)
        gates = [row for row in self.truth.query('rc72_node_gate', delivery_id=repair_delivery_id)
                 if row['gate_id'] in node['gate_refs']]
        if (delivery['mission_id'] != p['mission_id'] or delivery['mission_node_id'] != node['mission_node_id']
                or delivery['node_type'] != 'N5_TEST_DATA' or delivery['known_gaps']
                or delivery['version'] <= original_delivery['version'] or delivery['version'] != node['active_delivery_version']
                or node['state'] != 'PASS' or repair_delivery_id not in node['delivery_refs'] or len(gates) != 1
                or gates[0]['decision'] != 'PASS' or gates[0]['failed'] or not gates[0]['criteria']
                or set(gates[0]['criteria']) != set(gates[0]['passed'])):
            raise ContractError('N8_NEW_ACCEPTED_N5_REPAIR_REQUIRED')
        # Recompute the native N5 machine criteria read-only; a generic PASS gate
        # or a caller's repaired=True cannot certify the canonical data inventory.
        from .rc72_n5_completion import N5DeliveryGateService, _CRITERIA as N5_CRITERIA
        verifier = N5DeliveryGateService(self.truth, release_id=p['release_id'], source_commit=p['source_commit'])
        _, _, _, snapshot, records, parent_delivery, parent_gate = verifier._records(p['release_batch_id'])
        criteria = verifier._criterion_results(records=records, snapshot=snapshot,
            parent_delivery=parent_delivery, parent_gate=parent_gate)
        if (set(gates[0]['criteria']) != set(N5_CRITERIA) or not all(criteria.values())
                or delivery['artifact_refs'] != [row['binding_id'] for row in records]):
            raise ContractError('N8_CANONICAL_N5_REPAIR_PROOF_REQUIRED')
        self._fresh_data_repair_proofs(p, original['gate_id'], receipt['result']['affected_refs'])
        if not set(receipt['result']['affected_refs']).issubset(set(changed_refs)):
            raise ContractError('N8_REPAIR_MUST_COVER_FAILED_DATA_REFS')
        repairs = self.truth.query('rc72_diagnosis_repair', diagnosis_id=case['diagnosis_id'])
        if repairs:
            repair = self._one('rc72_diagnosis_repair', diagnosis_id=case['diagnosis_id'])
            if repair['repair_delivery_id'] != repair_delivery_id or repair['changed_refs'] != list(changed_refs) or repair['reason'] != reason:
                raise ContractError('N8_REPAIR_REPLAY_CONFLICT')
        self.orchestrator.record_upstream_repair(diagnosis_id=case['diagnosis_id'], repair_delivery_id=repair_delivery_id,
            changed_refs=changed_refs, reason=reason)
        return self._one('rc72_diagnosis_repair', diagnosis_id=case['diagnosis_id'])

    def _accept(self, p, case, facts, receipt):
        result = receipt['result']
        node = self.runtime.node_by_type(p['mission_id'], AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
        # A signed process receipt is not authority to reconstruct a missing
        # native N8 NodeDelivery. Refuse cold R1 corruption BEFORE appending
        # Evidence, advancing Node state or issuing repair/back-edge effects.
        recorded = self.truth.query('rc72_node_delivery', delivery_id=receipt['delivery_id'])
        if len(recorded) != 1:
            raise ContractError('N8_ACCEPTED_DELIVERY_NOT_UNIQUE_OR_MISSING')
        original_delivery = recorded[0]
        if (original_delivery.get('mission_id') != p['mission_id']
                or original_delivery.get('mission_node_id') != node['mission_node_id']
                or original_delivery.get('node_type') != 'N8_DIAGNOSIS_RECOVERY'
                or original_delivery.get('producer_ref') != case['diagnosis_worker_id']
                or original_delivery.get('artifact_refs') != [case['diagnosis_id']]
                or original_delivery.get('input_refs') != [p['contract_id']]
                or original_delivery.get('evidence_refs') != facts['evidence_refs']
                or original_delivery.get('known_gaps')):
            raise ContractError('N8_ACCEPTED_DELIVERY_LINEAGE_CHANGED')
        evidence_id = 'N8EV-' + _hash([case['diagnosis_id'], receipt['input_sha256']])[:24]
        # A cold replay cannot first append an Evidence row or mutate the Node
        # and only THEN notice a conflicting accepted Gate/Delivery generation.
        # Inspect all persisted authority facts before the first R1 mutation.
        refs = facts['evidence_refs'] + [evidence_id]
        gate_id = 'N8GATE-' + _hash([case['diagnosis_id'], receipt['input_sha256']])[:24]
        gates = self.truth.query('rc72_node_gate', gate_id=gate_id)
        if result['failure_class'] != 'UNKNOWN':
            # E-QA: a RUNNING node can already own a delivery generation.
            # The old preflight only checked REVIEW_PENDING/PASS and would
            # silently overwrite a conflicting RUNNING active generation
            # before reaching the later check. Refuse conflict before any R1
            # Evidence/transition, but permit a virgin RUNNING node (empty
            # delivery_refs, initial generation zero) to bind this delivery.
            existing_version = node['active_delivery_version']
            existing_refs = list(node['delivery_refs'])
            if node['state'] in {'REVIEW_PENDING', 'PASS'}:
                if (existing_version != original_delivery['version']
                        or receipt['delivery_id'] not in existing_refs):
                    raise ContractError('N8_ACTIVE_DELIVERY_CONFLICT')
            elif node['state'] == 'RUNNING':
                if ((existing_refs and receipt['delivery_id'] not in existing_refs)
                        or (existing_version not in (None, 0, original_delivery['version'])
                            and existing_version != original_delivery['version'])):
                    raise ContractError('N8_ACTIVE_DELIVERY_CONFLICT')
                if (existing_refs and existing_version != original_delivery['version']):
                    raise ContractError('N8_ACTIVE_DELIVERY_CONFLICT')
            if gates and (len(gates) != 1 or gates[0]['decision'] != 'PASS'
                    or gates[0]['delivery_id'] != receipt['delivery_id']
                    or gates[0]['reviewer_worker_id'] != receipt['reviewer_worker_id']
                    or gates[0]['reviewer_session_id'] != receipt['reviewer_session_id']
                    or gates[0]['criteria'] != _CRITERIA or gates[0]['passed'] != _CRITERIA
                    or gates[0]['evidence_refs'] != refs):
                raise ContractError('N8_ACCEPTED_GATE_CONFLICT')
        self.evidence._ensure('rc7_evidence', 'RC7_EVIDENCE_UPSERTED', 'evidence_id', dict(
            evidence_id=evidence_id, release_id=p['release_id'], mission_id=p['mission_id'], kind='N8_PROCESS_DIAGNOSIS',
            source_ref='r1://artifact/' + case['diagnosis_id'], content_ref=receipt['diagnostic_process']['stdout_ref'],
            content_hash=receipt['diagnostic_process']['stdout_sha256'], subject_refs=[p['attempt_id']], artifact_version=1))
        self.evidence._ensure('evidence', 'EVIDENCE_UPSERTED', 'id', dict(
            id=evidence_id, release_id=p['release_id'], kind='N8_PROCESS_DIAGNOSIS',
            ref=receipt['diagnostic_process']['stdout_ref'], source_artifact_ref=case['diagnosis_id'],
            attempt_id=p['attempt_id'], tc_id=p['case_id'], artifact_version=1))
        if result['failure_class'] == 'UNKNOWN':
            if node['state'] in {'READY', 'RUNNING', 'REVIEW_PENDING'}:
                self.runtime.transition_state(node['mission_node_id'], MissionNodeState.BLOCKED, reason=result['rationale'])
            if self._one('rc72_worker_session', session_id=receipt['reviewer_session_id'])['state'] == 'ACTIVE':
                self.preparation.lifecycle.checkpoint_and_close(receipt['reviewer_session_id'], reason='review accepted unknown causality; diagnosis remains blocked')
            return dict(state='BLOCKED', diagnosis_id=case['diagnosis_id'], failure_class='UNKNOWN')
        refs = facts['evidence_refs'] + [evidence_id]
        if node['state'] == 'READY':
            self.runtime.transition_state(node['mission_node_id'], MissionNodeState.RUNNING, reason='actual independent diagnosis ready')
            node = self.runtime.node(node['mission_node_id'])
        if node['state'] == 'RUNNING':
            self.runtime._persist_node_state(node, MissionNodeState.REVIEW_PENDING, reason='resume actual N8 delivery',
                active_delivery_version=original_delivery['version'], delivery_refs=list(dict.fromkeys(node['delivery_refs'] + [receipt['delivery_id']])))
        node = self.runtime.node(node['mission_node_id'])
        delivery = self._one('rc72_node_delivery', delivery_id=receipt['delivery_id'])
        if (delivery['mission_id'] != p['mission_id'] or delivery['producer_ref'] != case['diagnosis_worker_id']
                or delivery['artifact_refs'] != [case['diagnosis_id']] or delivery['input_refs'] != [p['contract_id']]
                or delivery['evidence_refs'] != facts['evidence_refs'] or delivery['known_gaps']
                or delivery['mission_node_id'] != node['mission_node_id']
                or delivery['version'] != node['active_delivery_version'] or delivery['delivery_id'] not in node['delivery_refs']):
            raise ContractError('N8_ACTIVE_DELIVERY_CONFLICT')
        if node['state'] == 'REVIEW_PENDING':
            if gates:
                self.runtime._persist_node_state(node, MissionNodeState.PASS, reason='resume accepted N8 gate',
                    gate_refs=list(dict.fromkeys(node['gate_refs'] + [gate_id])), bypass_direct_transition=True)
            else:
                self.runtime.apply_gate(NodeGate(gate_id=gate_id, mission_id=p['mission_id'], mission_node_id=node['mission_node_id'],
                    node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY, delivery_id=receipt['delivery_id'], decision=NodeGateDecision.PASS,
                    reviewer_worker_id=receipt['reviewer_worker_id'], reviewer_session_id=receipt['reviewer_session_id'],
                    criteria=_CRITERIA, passed=_CRITERIA, evidence_refs=refs, reason='independent process review of signed live failure evidence'))
        outcome = self.orchestrator.accept_classification(diagnosis_id=case['diagnosis_id'],
            failure_class=FailureClass(result['failure_class']), source_delivery_id=receipt['delivery_id'], evidence_refs=refs,
            affected_refs=result['affected_refs'], rationale=result['rationale'])
        for session_id in (receipt['diagnosis_session_id'], receipt['reviewer_session_id']):
            if self._one('rc72_worker_session', session_id=session_id)['state'] == 'ACTIVE':
                self.preparation.lifecycle.checkpoint_and_close(session_id, reason='actual N8 diagnosis and review accepted')
        return dict(state='REPAIR_REQUIRED' if outcome.responsible_node else 'RECOVERY_REQUIRED',
                    diagnosis_id=case['diagnosis_id'], failure_class=result['failure_class'],
                    responsible_node=outcome.responsible_node.value if outcome.responsible_node else None,
                    action=outcome.action, gap_id=outcome.gap_id)


install_rc72_n8_execution_diagnosis_overlay()
