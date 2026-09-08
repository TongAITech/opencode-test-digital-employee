"""Bounded business journeys shared by dynamic G4 execution and pytest assets.

Only a frozen StandardTestCase supplies actions/oracles. Responses stay local;
step receipts contain hashes and assertion outcomes, never response bodies.
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
    if isinstance(value, list): return [template(v,variables,depth=depth+1) for v in value]
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


def run_journey(executor, case, request):
    from .r3_3.contracts import StandardTestCase
    standard=StandardTestCase.from_dict(case); standard.validate_for_execution()
    journey=standard.execution_profile.get('api_journey')
    if not isinstance(journey,dict): fail('JOURNEY_REQUIRED')
    steps=journey.get('steps')
    if not isinstance(steps,(list,tuple)) or not 1<=len(steps)<=32: fail('STEP_BUDGET')
    if len(json.dumps(journey,ensure_ascii=False).encode())>65536: fail('JOURNEY_BUDGET')
    variables=dict(journey.get('variables') or {})
    receipts=[]; deadline=time.monotonic()+120
    for index,step in enumerate(steps):
        if time.monotonic()>deadline: fail('TIME_BUDGET')
        if not isinstance(step,dict) or not step.get('assertions'): fail('ASSERTIONS_REQUIRED')
        if not isinstance(step.get('status_code'),int) or isinstance(step['status_code'],bool): fail('STATUS_ORACLE_REQUIRED')
        sent={**request,'url':template(step['url'],variables,url=True),'method':step.get('method','GET'),
              'json':template(step.get('json'),variables),'headers':template(step.get('headers',{}),variables)}
        code,headers,raw=executor._http(sent)
        body=json.loads(raw)
        checks={'http_status':code==step['status_code']}
        # Previous values remain available for state/cross-field comparisons.
        for name,path in (step.get('extract') or {}).items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',name): fail('VARIABLE_NAME')
            v=path_get(body,path)
            if len(json.dumps(v).encode())>8192: fail('EXTRACTION_BUDGET')
            variables[name]=v
        for ordinal,check in enumerate(step['assertions']):
            try: checks['assert_'+str(ordinal)]=assertion(check,body,variables)
            except (RuntimeError,KeyError,TypeError,ValueError): checks['assert_'+str(ordinal)]=False
        for check in step.get('cross_channel',[]):
            channel=check['channel']; provider=executor.oracle_providers.get(channel)
            if provider is None: fail('CROSS_CHANNEL_BINDING_REQUIRED')
            # Bound read-only adapter owns auth; model supplies a configured query ID.
            observed=provider.read(check['binding_query_id'],template(check.get('parameters',{}),variables))
            checks['channel_'+channel]=assertion(check['assertion'],observed,variables)
        if step.get('idempotency'):
            if not sent['headers'].get('Idempotency-Key'): fail('IDEMPOTENCY_KEY_REQUIRED')
            code2,_,raw2=executor._http(sent)
            body2=json.loads(raw2)
            checks['idempotency_status']=code2==code
            paths=step['idempotency'].get('paths')
            if not paths: fail('IDEMPOTENCY_ORACLE_REQUIRED')
            checks['idempotency_fields']=all(path_get(body,p)==path_get(body2,p) for p in paths)
        receipt={'step_id':str(step.get('step_id',index+1)), 'status_code':code,
                 'response_sha256':hashlib.sha256(raw).hexdigest(),'response_bytes':len(raw),
                 'checks':checks,'case_version_id':standard.case_version_id}
        receipt['evidence_digest']=canonical_sha256(receipt); receipts.append(receipt)
        if not all(checks.values()): break  # no side effects after a failed prerequisite
    return {'runner':'G4_HTTPX_BUSINESS_JOURNEY','tc_id':standard.tc_id,
            'case_version_id':standard.case_version_id,'case_digest':canonical_sha256(case),
            'steps':receipts,'complete':len(receipts)==len(steps)}, len(receipts)==len(steps) and all(all(x['checks'].values()) for x in receipts)


def pytest_asset(case):
    """The pytest fixture resolves this exact durable case and invokes G4.

    No copied request/oracle model and no arbitrary shell are embedded in assets.
    """
    identity={'tc_id':case['tc_id'],'case_version_id':case['case_version_id'],'case_digest':canonical_sha256(case)}
    return 'import json\npytest_plugins = ["aitest_runtime.recovery_pytest"]\nIDENTITY = json.loads(' + repr(json.dumps(identity)) + ')\n\ndef test_business_journey(aitest_governed_case_runner):\n    result = aitest_governed_case_runner(IDENTITY)\n    assert result["oracle_result"] == "PASS"\n'
