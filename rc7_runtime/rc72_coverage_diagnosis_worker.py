"""Independent captured-evidence diagnosis/review; no product causality claim."""
import json,sys,runpy,hashlib
from pathlib import Path
review=runpy.run_path(str(Path(__file__).with_name('rc72_libra_report_review.py')))['review']


def diagnose(facts):
    measured=review(facts['report_request'])
    captured=Path(facts['report_request']['body_ref'][7:]).read_bytes()
    if hashlib.sha256(captured).hexdigest()!=facts['report_request']['body_sha256']:
        raise ValueError('COVERAGE_DIAGNOSIS_CAPTURE_CHANGED')
    raw=json.loads(captured.decode('utf-8-sig'))
    gap=facts['gap'];units=[u for u in raw['units'] if not u['covered'] and u['code_slice']==gap['code_slice']]
    cases=facts['accepted_cases']
    if not units or len(units)!=gap['uncovered_units'] or not cases:
        raise ValueError('COVERAGE_DIAGNOSIS_ACTUAL_SCOPE_REQUIRED')
    if (len({c['case_id'] for c in cases})!=len(cases) or len({c['attempt_id'] for c in cases})!=len(cases)
            or any(c['status']!='PASS' or not c['source_case_sha256'] for c in cases)):
        raise ValueError('COVERAGE_DIAGNOSIS_ACCEPTED_CASES_REQUIRED')
    return dict(gap_id=gap['gap_id'],measurement_id=measured['measurement_id'],
        obligation_id=gap['obligation_id'],reason='PATH_NOT_REACHED',responsible_nodes=['N8_DIAGNOSIS_RECOVERY'],
        action='DIAGNOSE_PATH',uncovered_units=len(units),
        case_ids=[c['case_id'] for c in cases],attempt_ids=[c['attempt_id'] for c in cases],
        rationale='Accepted original Cases did not cover the measured units of their mapped code slice; investigate path reachability. This does not establish a product defect or its root cause.')


if __name__=='__main__':
    try:
        request=json.loads(Path(sys.argv[1]).read_text())
        result=diagnose(request['facts'])
        if request['mode']=='REVIEW':
            if request['candidate']!=result:raise ValueError('COVERAGE_DIAGNOSIS_INDEPENDENT_REVIEW_REJECTED')
        elif request['mode']!='DIAGNOSE':raise ValueError('COVERAGE_DIAGNOSIS_MODE_INVALID')
        print(json.dumps(dict(valid=True,result=result),sort_keys=True))
    except Exception as exc:
        print(json.dumps(dict(valid=False,error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__),sort_keys=True))
        sys.exit(1)
