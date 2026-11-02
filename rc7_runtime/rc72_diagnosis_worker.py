"""Read-only deterministic diagnosis of cryptographically admitted N7 facts.

This worker never labels an unexplained Oracle/process failure a product defect.
"""
import hashlib
import json
from pathlib import Path
import sys


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
