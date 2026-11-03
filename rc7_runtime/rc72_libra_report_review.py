"""Standalone deterministic reviewer of a captured normalized Libra report.

This is the adapter contract, not a claim about a vendor endpoint's wire schema.
"""
import hashlib,json,sys,time
from pathlib import Path


def _pairs(items):
    result={}
    for key,value in items:
        if key in result:raise ValueError('LIBRA_DUPLICATE_JSON_KEY')
        result[key]=value
    return result


def review(request):
    path=Path(request['body_ref'][7:])
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2097152:raise ValueError('LIBRA_CAPTURE_REQUIRED')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=request['body_sha256']:raise ValueError('LIBRA_CAPTURE_CHANGED')
    row=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=_pairs)
    fields={'schema','measurement_id','application_id','base_revision','target_revision','metric','observed_at','source_ref','units'}
    if not isinstance(row,dict) or set(row)!=fields or row['schema']!='RC72_LIBRA_INCREMENTAL_REPORT_V1':
        raise ValueError('LIBRA_REPORT_SCHEMA_INVALID')
    for key in ('measurement_id','application_id','base_revision','target_revision','metric'):
        if row[key]!=request[key]:raise ValueError('LIBRA_REPORT_SCOPE_MISMATCH')
    if (type(row['observed_at']) is not int or not request['minimum_observed_at']<=row['observed_at']<=request['finished_at']+5
            or not isinstance(row['source_ref'],str) or not row['source_ref'].startswith('libra://')):
        raise ValueError('LIBRA_REPORT_FRESH_SOURCE_REQUIRED')
    units=row['units']
    if not isinstance(units,list) or not units:raise ValueError('LIBRA_REPORT_FULL_DENOMINATOR_REQUIRED')
    ids=set();uncovered=[]
    for unit in units:
        if not isinstance(unit,dict) or set(unit)!={'unit_id','code_slice','covered'} or type(unit['covered']) is not bool:
            raise ValueError('LIBRA_UNIT_INVALID')
        if any(not isinstance(unit[k],str) or not unit[k].strip() for k in ('unit_id','code_slice')) or unit['unit_id'] in ids:
            raise ValueError('LIBRA_UNIT_IDENTITY_INVALID')
        ids.add(unit['unit_id'])
        if not unit['covered']:uncovered.append(unit['code_slice'])
    return dict(measurement_id=row['measurement_id'],application_id=row['application_id'],
        total_units=len(units),covered_units=len(units)-len(uncovered),
        uncovered_code_slices=sorted(set(uncovered)),source_ref=row['source_ref'],observed_at=row['observed_at'])


if __name__=='__main__':
    try:
        request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        print(json.dumps(dict(valid=True,result=review(request)),sort_keys=True))
    except Exception as exc:
        print(json.dumps(dict(valid=False,error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__),sort_keys=True))
        sys.exit(1)
