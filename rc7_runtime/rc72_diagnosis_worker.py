"""Read-only deterministic diagnosis of cryptographically admitted N7 facts.

This worker never labels an unexplained Oracle/process failure a product defect.
"""
import hashlib
import json
from pathlib import Path
import sys


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def verify_conclusive_failure(facts):
    envelope = facts['conclusive_assertion_failure']
    proof = envelope['proof']
    ref = envelope['content_ref']
    path = Path(ref[len('file://'):]) if ref.startswith('file://') else None
    if (path is None or path.is_symlink() or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest()!=envelope['content_sha256']
            or json.loads(path.read_text(encoding='utf-8'))!=proof):
        raise ValueError('CONCLUSIVE_FAILURE_CAPTURED_PROOF_CHANGED')
    core = {k:v for k,v in proof.items() if k not in {'proof_sha256','signature'}}
    if (proof['purpose']!='N7_CONCLUSIVE_ASSERTION_FAILURE' or _hash(core)!=proof['proof_sha256']
            or envelope['evidence_id']!='N7FAILEV-'+proof['proof_sha256'][:24]
            or any(proof[k]!=facts[k] for k in ('attempt_id','workitem_id','case_id','mission_id','contract_id','contract_sha256'))):
        raise ValueError('CONCLUSIVE_FAILURE_PROOF_SCOPE_CHANGED')
    case = proof['case_snapshot']
    required = {r['requirement'] for r in case['evidence_declarations']}
    files = proof['captured_evidence']
    if (case['formal_proof_gaps'] or not case['formal_runner_receipt_ref'] or not case['cleanup_evidence_ref']
            or len(files)!=len(required) or {r['requirement'] for r in files}!=required
            or case['receipt_sha256']!=_hash(proof['actual_result'])
            or proof['case_id'] not in proof['full_plan_case_ids']):
        raise ValueError('CONCLUSIVE_FAILURE_COMPLETE_FORMAL_PROOF_REQUIRED')
    for row in files:
        ref = row['content_ref']
        path = Path(ref[len('file://'):]) if ref.startswith('file://') else None
        if (path is None or path.is_symlink() or not path.is_file()
                or len(path.read_bytes())!=row['size_bytes']
                or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']):
            raise ValueError('CONCLUSIVE_FAILURE_REQUIRED_EVIDENCE_CHANGED')
    context = dict(contract_sha256=facts['contract_sha256'],dispatch_id=case['dispatch_id'],
        attempt_id=facts['attempt_id'],receipt_sha256=case['receipt_sha256'])
    if proof['oracle_context']!=context:
        raise ValueError('CONCLUSIVE_FAILURE_ORACLE_CONTEXT_CHANGED')
    # Trusted sibling source, never the request/CWD, supplies the same frozen
    # deterministic operators. The independent process recomputes every check.
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from oracle_runtime import DeterministicOracleRuntime
    oracle = DeterministicOracleRuntime().evaluate({'checks':proof['oracles']},proof['actual_result'],context)
    if oracle!=proof['oracle_result'] or oracle['passed'] is not False or case['assertion_ref']!='N7ASSERT-'+_hash([facts['attempt_id'],oracle])[:24]:
        raise ValueError('CONCLUSIVE_FAILURE_ORACLE_NOT_REPRODUCIBLE')
    return True


def classify(request):
    facts = request['facts']
    for row in facts['checks']:
        path = Path(row['captured_ref'][len('file://'):])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('DIAGNOSIS_EVIDENCE_BYTES_CHANGED')
    failed_tools = [row for row in facts['checks'] if row['kind'] == 'TOOL_UNAVAILABLE' and row['success'] is False]
    if failed_tools:
        return dict(diagnosis_id=request['diagnosis_id'], input_sha256=request['input_sha256'],
            failure_class='CAPABILITY_GAP', confidence='DIRECT_MACHINE_EVIDENCE',
            affected_refs=sorted(row['spec']['tool_id'] for row in failed_tools),
            rationale='Runtime observed the exact required tool executable absent on disk during a real failed capability probe',
            requested_remediation='CapabilityBroker must restore and re-probe the exact required tool; no automatic business replay')
    failed_data = [row for row in facts['checks'] if row['kind'] == 'DATA_RECHECK' and row['success'] is False]
    if not failed_data and facts.get('conclusive_assertion_failure'):
        verify_conclusive_failure(facts)
        return dict(diagnosis_id=request['diagnosis_id'],input_sha256=request['input_sha256'],
            failure_class='VALID_TEST_FAILURE',confidence='COMPLETE_FROZEN_CONTRACT_DISCREPANCY',
            affected_refs=[facts['case_id']],
            rationale='Actual approved execution and complete captured evidence reproduce a frozen business assertion discrepancy; product causality is not established',
            requested_remediation='N9 independently qualify the discrepancy and RCA with governed reproduction; no automatic business replay')
    proven = bool(failed_data)
    return dict(diagnosis_id=request['diagnosis_id'], input_sha256=request['input_sha256'],
        failure_class='TEST_DATA_GAP' if proven else 'UNKNOWN',
        confidence='DIRECT_MACHINE_EVIDENCE' if proven else 'INSUFFICIENT_CAUSAL_EVIDENCE',
        affected_refs=sorted(row['spec']['data_ref'] for row in failed_data),
        rationale='Exact frozen DataRef failed live verification' if proven else
                  'Observed execution failure does not establish a responsible asset or product defect',
        requested_remediation='N5 reverify or repair the failed DataRefs through a new accepted delivery' if proven else
                              'Collect independent diagnostic evidence; do not retry or relabel as product failure')


if __name__ == '__main__':
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    result = classify(request)
    if request.get('mode') == 'REVIEW':
        result = dict(accepted=result == request['candidate'], diagnosis_id=request['diagnosis_id'],
                      input_sha256=request['input_sha256'])
    print(json.dumps(result, sort_keys=True))
