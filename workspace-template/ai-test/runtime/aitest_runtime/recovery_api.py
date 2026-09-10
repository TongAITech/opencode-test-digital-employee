"""Bounded business journeys shared by dynamic G4 execution and pytest assets.

Only a frozen StandardTestCase supplies actions/oracles. Receipts retain bounded,
redacted assertion values and differences, never whole response bodies.
"""
from __future__ import annotations
import ast
import hashlib
import json
import math
import operator
import re
import time
from urllib.parse import quote
from .durable_core import RuntimeError, canonical_sha256


def fail(code):
    raise RuntimeError('API_BUSINESS_' + code, 'Frozen business journey validation failed')


def path_get(value, path):
    if not isinstance(path, str) or len(path) > 256 or not path.startswith('$'):
        fail('PATH_INVALID')
    tokens = re.findall(r'\.([A-Za-z_][\w-]*)|\[(\d+)\]', path[1:])
    rebuilt = '$' + ''.join('.' + key if key else '[' + index + ']' for key, index in tokens)
    if rebuilt != path or len(tokens) > 16: fail('PATH_INVALID')
    try:
        for key, index in tokens: value = value[key] if key else value[int(index)]
    except (KeyError, IndexError, TypeError): fail('PATH_MISSING')
    return value


def expression(source, variables):
    """A tiny numeric/boolean AST interpreter: no eval, calls or attributes."""
    if not isinstance(source, str) or len(source) > 1024: fail('EXPRESSION_BUDGET')
    try: tree = ast.parse(source, mode='eval')
    except (SyntaxError, RecursionError): fail('EXPRESSION_INVALID')
    if sum(1 for _ in ast.walk(tree)) > 100: fail('EXPRESSION_BUDGET')
    binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Mod: operator.mod}
    compare = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
               ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
               ast.In: lambda a,b: a in b, ast.NotIn: lambda a,b: a not in b}
    def read(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool, type(None))): result = node.value
        elif isinstance(node, ast.Name) and node.id in variables: result = variables[node.id]
        elif isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) <= 32: result = [read(x) for x in node.elts]
        elif isinstance(node, ast.BinOp) and type(node.op) in binary:
            a,b=read(node.left),read(node.right)
            if any(isinstance(x,bool) or not isinstance(x,(int,float)) for x in (a,b)): fail('NUMERIC_OPERANDS_REQUIRED')
            result = binary[type(node.op)](a,b)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub, ast.UAdd)):
            v=read(node.operand)
            if isinstance(node.op, ast.Not): result=not v
            elif isinstance(v,(int,float)) and not isinstance(v,bool): result=-v if isinstance(node.op,ast.USub) else v
            else: fail('EXPRESSION_INVALID')
        elif isinstance(node, ast.BoolOp) and isinstance(node.op,(ast.And,ast.Or)):
            result = all(read(x) for x in node.values) if isinstance(node.op,ast.And) else any(read(x) for x in node.values)
        elif isinstance(node, ast.Compare):
            a=read(node.left); result=True
            for op,right in zip(node.ops,node.comparators):
                if type(op) not in compare: fail('EXPRESSION_INVALID')
                b=read(right); result=result and compare[type(op)](a,b); a=b
        else: fail('EXPRESSION_INVALID')
        if isinstance(result,(int,float)) and (not math.isfinite(result) or abs(result)>1e18): fail('NUMERIC_BUDGET')
        if isinstance(result,(dict,list,tuple,str)) and len(result)>4096: fail('VALUE_BUDGET')
        return result
    try: return read(tree.body)
    except (ZeroDivisionError, OverflowError, TypeError, ValueError): fail('EXPRESSION_FAILED')


def template(value, variables, *, url=False, depth=0):
    if depth > 16: fail('TEMPLATE_BUDGET')
    if isinstance(value, dict): return {k:template(v,variables,depth=depth+1) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [template(v,variables,depth=depth+1) for v in value]
    if not isinstance(value,str): return value
    def replace(match):
        name=match.group(1)
        if name not in variables: fail('VARIABLE_MISSING')
        v=variables[name]
        if isinstance(v,(dict,list)): fail('SCALAR_TEMPLATE_REQUIRED')
        return quote(str(v),safe='') if url else str(v)
    pattern=r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}'
    full=re.fullmatch(pattern,value)
    if full and not url:
        if full[1] not in variables: fail('VARIABLE_MISSING')
        return variables[full[1]]
    return re.sub(pattern,replace,value)


def schema_matches(value, schema, depth=0):
    """Explicit supported JSON-schema subset; unknown keywords fail closed."""
    if depth > 12 or not isinstance(schema,dict) or set(schema)-{'type','required','properties','items','enum','minimum','maximum'}: fail('SCHEMA_UNSUPPORTED')
    kinds={'object':dict,'array':list,'string':str,'number':(int,float),'integer':int,'boolean':bool,'null':type(None)}
    kind=schema.get('type')
    if kind not in kinds: fail('SCHEMA_TYPE_REQUIRED')
    if not isinstance(value,kinds[kind]) or kind in ('number','integer') and isinstance(value,bool): return False
    if 'enum' in schema and value not in schema['enum']: return False
    if kind in ('number','integer'):
        if 'minimum' in schema and value < schema['minimum']: return False
        if 'maximum' in schema and value > schema['maximum']: return False
    if kind=='object':
        if any(k not in value for k in schema.get('required',[])): return False
        return all(k not in value or schema_matches(value[k],v,depth+1) for k,v in schema.get('properties',{}).items())
    if kind=='array' and 'items' in schema: return len(value)<=4096 and all(schema_matches(v,schema['items'],depth+1) for v in value)
    return True


def assertion(check, body, variables):
    op=check.get('op')
    if op=='expression': return expression(check.get('expression'),variables) is True
    value=path_get(body,check.get('path'))
    expected=template(check.get('value'),variables)
    if op=='eq': return value==expected
    if op=='not_null': return value is not None
    if op=='range': return isinstance(value,(int,float)) and not isinstance(value,bool) and check['min']<=value<=check['max']
    if op=='in': return value in check['values']
    if op=='schema': return schema_matches(value,check['schema'])
    if op=='transition': return variables.get(check['previous'])==check['from'] and value==check['to']
    fail('ASSERTION_UNSUPPORTED')


MAX_ORACLES = 128
MAX_DIAGNOSTIC_BYTES = 1024
SENSITIVE = re.compile(r'password|passwd|secret|token|authorization|cookie|credential|otp|mfa|private.?key|account|card|email|phone|(^|\.)id$', re.I)


def expected_api_step(step):
    """Shape authors must freeze independently in expected_results[].api.

    This is a projection, not an approval or automatic Case migration. Execution
    compares the independently stored expectation with its executable profile.
    """
    return {key: step.get(key, default) for key, default in (
        ('status_code', None), ('assertions', []), ('cross_channel', []),
        ('extract', {}), ('idempotency', None))}


def validate_journey_contract(standard):
    """Compile unique Oracle identities and reject drift before any HTTP send."""
    journey = standard.execution_profile.get('api_journey')
    if not isinstance(journey, dict): fail('JOURNEY_REQUIRED')
    steps = journey.get('steps')
    if not isinstance(steps, (list, tuple)) or not 1 <= len(steps) <= 32: fail('STEP_BUDGET')
    if len(json.dumps(journey, ensure_ascii=False).encode()) > 65536: fail('JOURNEY_BUDGET')
    variables = journey.get('variables', {})
    if not isinstance(variables, dict): fail('VARIABLES_INVALID')
    version = standard.oracle_contract.get('api_oracle_version')
    if type(version) is not int or version != 1 or canonical_sha256(standard.oracle_contract.get('api_variables')) != canonical_sha256(variables):
        fail('FROZEN_ORACLE_BINDING_REQUIRED')
    if len(standard.expected_results) != len(steps) or len(standard.steps) != len(steps): fail('EXPECTED_STEP_MISMATCH')
    catalog = []; step_ids = set(); oracle_ids = set()
    def add(step_id, kind, ordinal, check, *, channel='API', mandatory=True, **extra):
        if not isinstance(mandatory, bool): fail('MANDATORY_FLAG_INVALID')
        identity = {'case_version_id': standard.case_version_id, 'step_id': step_id, 'kind': kind, 'channel': channel, 'ordinal': ordinal}
        oracle_id = 'api-oracle:' + canonical_sha256(identity)[:32]
        if oracle_id in oracle_ids: fail('DUPLICATE_ORACLE_ID')
        oracle_ids.add(oracle_id)
        catalog.append({**identity, 'oracle_id': oracle_id, 'mandatory': mandatory,
                        'check': check, 'declaration_sha256': canonical_sha256({'check': check, 'mandatory': mandatory, **extra}), **extra})
        if len(catalog) > MAX_ORACLES: fail('ORACLE_BUDGET')
    for index, step in enumerate(steps):
        if not isinstance(step, dict): fail('STEP_INVALID')
        step_id = step.get('step_id')
        if not isinstance(step_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}', step_id) or step_id in step_ids:
            fail('STEP_ID_INVALID_OR_DUPLICATE')
        step_ids.add(step_id)
        expected = standard.expected_results[index]
        if expected.get('step_id') != step_id or standard.steps[index].get('step_id') != step_id:
            fail('EXPECTED_STEP_MISMATCH')
        if canonical_sha256(expected.get('api')) != canonical_sha256(expected_api_step(step)):
            fail('FROZEN_EXPECTED_ASSERTION_MISMATCH')
        if not isinstance(step.get('extract', {}), dict): fail('EXTRACTION_INVALID')
        if not isinstance(step.get('status_code'), int) or isinstance(step['status_code'], bool) or not 100 <= step['status_code'] <= 599:
            fail('STATUS_ORACLE_REQUIRED')
        assertions = step.get('assertions')
        cross = step.get('cross_channel', [])
        if not isinstance(assertions, (list, tuple)) or not assertions or not isinstance(cross, (list, tuple)): fail('ASSERTIONS_REQUIRED')
        add(step_id, 'HTTP_STATUS', 0, {'value': step['status_code']})
        for ordinal, check in enumerate(assertions):
            if not isinstance(check, dict): fail('ASSERTION_INVALID')
            add(step_id, 'ASSERTION', ordinal, check, mandatory=check.get('mandatory', True))
        for ordinal, check in enumerate(cross):
            if not isinstance(check, dict) or not isinstance(check.get('assertion'), dict): fail('CROSS_CHANNEL_ASSERTION_REQUIRED')
            channel = check.get('channel')
            if channel not in {'DB', 'CAT', 'MQ', 'LOG'}: fail('CROSS_CHANNEL_INVALID')
            query_id = check.get('binding_query_id')
            if not isinstance(query_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', query_id): fail('QUERY_ID_REQUIRED')
            if 'mandatory' in check['assertion']: fail('CROSS_CHANNEL_MANDATORY_ON_OUTER_DECLARATION_REQUIRED')
            add(step_id, 'CROSS_CHANNEL', ordinal, check['assertion'], channel=channel,
                mandatory=check.get('mandatory', True), query_id=query_id, parameters=check.get('parameters', {}))
        if not any(x['mandatory'] and x['kind'] in {'ASSERTION', 'CROSS_CHANNEL'} for x in catalog if x['step_id'] == step_id):
            fail('MANDATORY_ASSERTIONS_REQUIRED')
        if step.get('idempotency') is not None:
            paths = step['idempotency'].get('paths') if isinstance(step['idempotency'], dict) else None
            if not isinstance(paths, (list, tuple)) or not paths or any(not isinstance(p, str) for p in paths): fail('IDEMPOTENCY_ORACLE_REQUIRED')
            if 'Idempotency-Key' not in step.get('headers', {}): fail('IDEMPOTENCY_KEY_REQUIRED')
            add(step_id, 'IDEMPOTENCY_STATUS', 0, {})
            for ordinal, path in enumerate(paths): add(step_id, 'IDEMPOTENCY_FIELD', ordinal, {'path': path})
    return journey, catalog


def _safe_value(value, path='', depth=0):
    if SENSITIVE.search(path): return '[redacted]'
    if depth > 3: return '[depth limited]'
    if isinstance(value, dict):
        return {str(k)[:64]: _safe_value(v, str(k), depth+1) for k, v in list(value.items())[:6] if not SENSITIVE.search(str(k))}
    if isinstance(value, (list, tuple)): return [_safe_value(v, path, depth+1) for v in value[:6]]
    if isinstance(value, str):
        value = re.sub(r'(?i)bearer\s+\S+|\beyJ[\w-]+\.[\w-]+\.[\w-]+\b|\b\d{12,19}\b', '[redacted]', value)
        value = re.sub(r'(?i)(password|secret|token|cookie|authorization)\s*[:=]\s*[^\s,;]+', '[redacted]', value)
        return value[:160] + ('[truncated]' if len(value) > 160 else '')
    if value is None or isinstance(value, (bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else '[nonfinite]'
    return '[unsupported]'


def _diagnostic(expected, actual, passed, *, path='', error=None):
    result = {'expected': _safe_value(expected, path), 'actual': _safe_value(actual, path),
              'diff': 'MATCH' if passed else 'OBSERVATION_ERROR' if error else 'VALUE_MISMATCH'}
    if error: result['error'] = _safe_value(error)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_DIAGNOSTIC_BYTES:
        # Keep readable summaries and the mismatch, without an unbounded payload.
        result['expected'] = json.dumps(result['expected'], ensure_ascii=False).encode()[:128].decode('utf-8', errors='ignore')
        result['actual'] = json.dumps(result['actual'], ensure_ascii=False).encode()[:128].decode('utf-8', errors='ignore')
        if 'error' in result: result['error'] = json.dumps(result['error'], ensure_ascii=False).encode()[:128].decode('utf-8', errors='ignore')
        result['truncated'] = True
    return result


def _record(entry, expected, actual, passed=False, *, error=None, path='', status=None):
    result = {key: entry[key] for key in ('oracle_id', 'kind', 'channel', 'ordinal', 'mandatory', 'declaration_sha256')}
    result['status'] = status or ('ERROR' if error else 'PASS' if passed is True else 'FAIL')
    result['diagnostic'] = _diagnostic(expected, actual, passed is True, path=path or entry['check'].get('path', ''), error=error)
    if entry.get('query_id'):
        result['query_id'] = entry['query_id']
        result['parameters_sha256'] = entry.get('parameters_sha256', canonical_sha256(entry['parameters']))
    return result


def _assertion_record(entry, body, variables):
    check = entry['check']; path = check.get('path', '')
    expected = {k: v for k, v in check.items() if k not in {'mandatory', 'path'}}
    actual = None
    try:
        if check.get('op') == 'expression':
            actual = {'result': expression(check.get('expression'), variables),
                      'variables': {name: variables[name] for name in sorted(set(re.findall(r'\b[A-Za-z_]\w*\b', check.get('expression', '')))) if name in variables}}
            expected = {'result': True, 'expression': check.get('expression')}
        else:
            actual = path_get(body, path)
            expected = template(expected, variables)
        passed = assertion(check, body, variables) is True
        return _record(entry, expected, actual, passed, path=path)
    except Exception as exc:
        return _record(entry, expected, actual, path=path,
                       error={'type': type(exc).__name__, 'code': getattr(exc, 'code', 'ASSERTION_OBSERVATION_ERROR')})


def _mandatory_pass(records):
    return all(row['status'] == 'PASS' for row in records if row['mandatory'])


def run_journey(executor, case, request):
    from .r3_3.contracts import StandardTestCase
    standard=StandardTestCase.from_dict(case); standard.validate_for_execution()
    journey, catalog = validate_journey_contract(standard)
    steps = journey['steps']
    variables=dict(journey.get('variables') or {})
    receipts=[]; deadline=time.monotonic()+120
    for index,step in enumerate(steps):
        if time.monotonic()>deadline: fail('TIME_BUDGET')
        entries = [entry for entry in catalog if entry['step_id'] == step['step_id']]
        records = []
        sent={**request,'url':template(step['url'],variables,url=True),'method':step.get('method','GET'),
              'json':template(step.get('json'),variables),'headers':template(step.get('headers',{}),variables)}
        code,headers,raw=executor._http(sent)
        body = None; body_error = None
        try: body = json.loads(raw)
        except (ValueError, TypeError) as exc: body_error = {'type': type(exc).__name__, 'code': 'RESPONSE_JSON_INVALID'}
        records.append(_record(entries[0], step['status_code'], code, code == step['status_code']))
        # Previous values remain available for state/cross-field comparisons.
        try:
            for name,path in (step.get('extract') or {}).items():
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',name): fail('VARIABLE_NAME')
                v=path_get(body,path)
                if len(json.dumps(v).encode())>8192: fail('EXTRACTION_BUDGET')
                variables[name]=v
        except Exception as exc: body_error = {'type': type(exc).__name__, 'code': getattr(exc, 'code', 'EXTRACTION_ERROR')}
        for entry in entries[1:]:
            if entry['kind'] == 'ASSERTION':
                records.append(_record(entry, entry['check'], None, error=body_error) if body_error else _assertion_record(entry, body, variables))
            elif entry['kind'] == 'CROSS_CHANNEL':
                try:
                    if body_error: fail('PREREQUISITE_OBSERVATION_UNAVAILABLE')
                    provider = executor.oracle_providers.get(entry['channel'])
                    if provider is None: fail('CROSS_CHANNEL_BINDING_REQUIRED')
                    parameters = template(entry['parameters'], variables)
                    entry = {**entry, 'parameters_sha256': canonical_sha256(parameters)}
                    observed = provider.read(entry['query_id'], parameters)
                    if observed is None: fail('CROSS_CHANNEL_OBSERVATION_MISSING')
                    records.append(_assertion_record(entry, observed, variables))
                except Exception as exc:
                    records.append(_record(entry, entry['check'], None,
                        error={'type': type(exc).__name__, 'code': getattr(exc, 'code', 'PROVIDER_OBSERVATION_ERROR')}))
        if step.get('idempotency'):
            repeat_entries = [entry for entry in entries if entry['kind'].startswith('IDEMPOTENCY_')]
            if not _mandatory_pass(records):
                records.extend(_record(entry, 'Available prerequisite observations', None,
                    error={'code': 'PREREQUISITE_FAILED'}, status='NOT_RUN') for entry in repeat_entries)
            else:
                try:
                    if not sent['headers'].get('Idempotency-Key'): fail('IDEMPOTENCY_KEY_REQUIRED')
                    code2,_,raw2=executor._http(sent); body2=json.loads(raw2)
                    records.append(_record(repeat_entries[0], code, code2, code2 == code))
                    for entry in repeat_entries[1:]:
                        try:
                            path = entry['check']['path']; before = path_get(body, path); after = path_get(body2, path)
                            records.append(_record(entry, before, after, before == after, path=path))
                        except Exception as exc:
                            records.append(_record(entry, entry['check'], None, error={'type': type(exc).__name__, 'code': getattr(exc, 'code', 'IDEMPOTENCY_OBSERVATION_ERROR')}))
                except Exception as exc:
                    recorded = {row['oracle_id'] for row in records}
                    records.extend(_record(entry, entry['check'], None,
                        error={'type': type(exc).__name__, 'code': getattr(exc, 'code', 'IDEMPOTENCY_OBSERVATION_ERROR')}) for entry in repeat_entries if entry['oracle_id'] not in recorded)
        checks = {row['oracle_id']: row['status'] == 'PASS' for row in records}
        receipt={'step_id':str(step.get('step_id',index+1)), 'status_code':code,
                 'response_sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw),
                 'checks':checks, 'oracles': records, 'case_version_id':standard.case_version_id}
        receipt['evidence_digest']=canonical_sha256(receipt); receipts.append(receipt)
        if not _mandatory_pass(records): break  # no side effects after a failed prerequisite
    observed = [row for receipt in receipts for row in receipt['oracles']]
    required = {entry['oracle_id'] for entry in catalog if entry['mandatory']}
    passed_ids = {row['oracle_id'] for row in observed if row['status'] == 'PASS'}
    passed = len(receipts) == len(steps) and required <= passed_ids and _mandatory_pass(observed)
    return {'runner':'G4_HTTPX_BUSINESS_JOURNEY','tc_id':standard.tc_id,
            'case_version_id':standard.case_version_id,'case_digest':canonical_sha256(case),
            'steps':receipts, 'complete':len(receipts)==len(steps),
            'oracle_summary': {'declared': len(catalog), 'observed': len(observed), 'mandatory': len(required),
                               'mandatory_passed': len(required & passed_ids), 'missing_mandatory_ids': sorted(required - {row['oracle_id'] for row in observed})}}, passed


def pytest_asset(case):
    """The pytest fixture resolves this exact durable case and invokes G4.

    No copied request/oracle model and no arbitrary shell are embedded in assets.
    """
    identity={'tc_id':case['tc_id'],'case_version_id':case['case_version_id'],'case_digest':canonical_sha256(case)}
    return 'import json\npytest_plugins = ["aitest_runtime.recovery_pytest"]\nIDENTITY = json.loads(' + repr(json.dumps(identity)) + ')\n\ndef test_business_journey(aitest_governed_case_runner):\n    result = aitest_governed_case_runner(IDENTITY)\n    assert result["oracle_result"] == "PASS"\n'
