"""Independent deterministic N10 snapshot reviewer process.

This process holds no execution leases or credentials and does no business
operations. It checks the complete frozen result/denominator consistency from
the separately re-audited R1 snapshot received from the production controller.
The controller must re-audit original signed sources both before and after
the process, and may never treat this process alone as bank Field proof.
"""
import hashlib
import json
from pathlib import Path
import sys

_REQUIRED_TRUE = (
    'requirement_completion', 'sst_completion', 'obligation_completion',
    'required_l1_l7_completion', 'high_risk_completion',
    'incremental_coverage_met', 'critical_defects_closed',
    'no_blocked_workitems', 'no_unresolved_gaps', 'evidence_complete',
    'runtime_integrity',
)
_REQUIRED_FALSE = ('human_gate_required', 'runtime_blocked')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')


def review(request):
    snapshot=request['snapshot']
    facts=snapshot['facts']
    actual_hash=hashlib.sha256(canonical(snapshot)).hexdigest()
    valid=(
        snapshot['result']=='CONVERGED'
        and snapshot['snapshot_id']==request['snapshot_id']
        and actual_hash==request['snapshot_sha256']
        and not snapshot['blockers']
        and not snapshot['unproven_obligation_ids']
        and bool(snapshot['proven_obligation_ids'])
        and bool(snapshot['coverage_observation_ids'])
        and bool(request['criteria'])
        and all(facts.get(name) is True for name in _REQUIRED_TRUE)
        and all(facts.get(name) is False for name in _REQUIRED_FALSE)
        and set(facts)==set(_REQUIRED_TRUE+_REQUIRED_FALSE)
    )
    return dict(snapshot_id=request['snapshot_id'],
        snapshot_sha256=request['snapshot_sha256'],review_id=request['review_id'],
        reviewer_worker_id=request['reviewer_worker_id'],
        reviewer_session_id=request['reviewer_session_id'],
        criteria=request['criteria'],accepted=valid)


if __name__=='__main__':
    payload=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    print(json.dumps(review(payload),sort_keys=True))
