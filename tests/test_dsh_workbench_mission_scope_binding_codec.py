"""Pure compact binding contract; no production authority or runtime integration."""
import copy
import json
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.dsh_workbench.mission_scope_binding_codec import (
    BindingStructureError, ScopeIdentity, parse_scope, parse_mission_json,
    serialize_scope, require_unchanged,
)


def bound():
    return {'mission_id': 'M1', 'release_id': 'RT1', 'project_id': 'P1', 'batch_id': 'B1',
            'scope_binding': {'schema_version': 1, 'mission_id': 'M1', 'project_id': 'P1', 'batch_id': 'B1',
                              'binding_ref': 'bind:1', 'snapshot_ref': 'snapshot:1', 'scope_digest': '0'*64,
                              'release_date': '2026-11-11', 'date_revision': 1, 'relation_revision': 2,
                              'access_scope_revision': 3, 'creation_key_scope': {'formal_authority_ref': 'a1', 'actor_ref': 'alice', 'project_id': 'P1', 'creation_key': 'k1'},
                              'request_digest': '1'*64, 'mapping': {'schema_version': 1, 'formal_authority_ref': 'a1', 'project_id': 'P1', 'batch_id': 'B1', 'runtime_release_id': 'RT1', 'mapping_ref': 'map:1', 'mapping_policy': 'ALLOCATE_NEW_RELEASE_V1'}, 'creation_operation_ref': 'op:1'}}


def objects(value, path=()):
    if type(value) is dict:
        yield path, value
        for key, item in value.items():
            yield from objects(item, path + (key,))


def target(value, path):
    for key in path:
        value = value[key]
    return value


class BindingCodec(unittest.TestCase):
    def error(self, value, code=None):
        original = copy.deepcopy(value)
        with self.assertRaises(BindingStructureError) as caught:
            parse_scope(value)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(value, original)

    def test_roundtrip_deep_immutable_detached_and_no_authority(self):
        value = bound(); original = copy.deepcopy(value)
        scope = parse_scope(value)
        self.assertEqual(scope.classification, 'BOUND_STRUCTURAL_ONLY')
        self.assertEqual(serialize_scope(scope), {k: value[k] for k in ('scope_binding','project_id','batch_id')})
        raw = parse_mission_json(json.dumps(value))
        with self.assertRaises(TypeError): raw.envelope['scope_binding']['mapping']['project_id'] = 'x'
        with self.assertRaises(AttributeError): scope.binding_bytes = b'changed'
        value['scope_binding']['snapshot_ref'] = 'later'
        self.assertEqual(serialize_scope(scope)['scope_binding']['snapshot_ref'], 'snapshot:1')
        fragment = serialize_scope(scope); fragment['scope_binding']['snapshot_ref'] = 'changed'
        self.assertEqual(serialize_scope(scope)['scope_binding']['snapshot_ref'], 'snapshot:1')
        self.assertEqual(original, bound())

    def test_legacy_and_unknown_outer_finite_compatibility(self):
        for token in ('0.5', '1e3'):
            for is_bound in (False, True):
                value = bound() if is_bound else {'mission_id':'M1','release_id':'RT1'}
                baseline = parse_scope(value)
                raw = json.dumps(value)[:-1] + ',"diagnostic_score":' + token + ',"unknown":{"nested":['+token+']}}'
                parsed = parse_mission_json(raw)
                self.assertEqual(parsed.scope, baseline)
                self.assertEqual(parsed.envelope['diagnostic_score'], float(token))
                self.assertEqual(parsed.envelope['unknown']['nested'], (float(token),))
                dto = json.loads(raw); original = copy.deepcopy(dto)
                self.assertEqual(parse_scope(dto), baseline)
                self.assertEqual(dto, original)
                self.assertEqual(serialize_scope(parsed.scope), serialize_scope(baseline))
                self.assertNotIn('diagnostic_score', serialize_scope(parsed.scope))
                if not is_bound: self.assertEqual(serialize_scope(parsed.scope), {})
        # Plain DTO leaves unrelated outer semantics to the old model.
        self.assertEqual(parse_scope({'mission_id':'M','release_id':'R','extra':float('nan')}).classification,'LEGACY_UNBOUND')

    def test_exact_keys_missing_unknown_and_every_field_wrong_type(self):
        for path, obj in objects(bound()['scope_binding'], ('scope_binding',)):
            for key in obj:
                value=bound(); del target(value,path)[key]; self.error(value)
                for wrong in (None, [], {}, True, 1.0, '', '\ud800'):
                    value=bound(); target(value,path)[key]=wrong
                    self.error(value)
            value=bound(); target(value,path)['unexpected']='x'; self.error(value)
        for field in ('mission_id','release_id','project_id','batch_id'):
            for wrong in ([],{},None,True,1.0,'','\ud800'):
                value=bound();value[field]=wrong;self.error(value)

    def test_error_classifications_no_silent_repair(self):
        self.error({'mission_id':'M','release_id':'R','scope_binding':None},'BINDING_EXPLICIT_NULL')
        for fields in ({'project_id':'P'},{'batch_id':None},{'project_id':'P','batch_id':'B'}):
            self.error(dict(mission_id='M',release_id='R',**fields),'BINDING_FLAT_ONLY_UNQUALIFIED')
        value=bound();value['scope_binding']['schema_version']=2;self.error(value,'BINDING_SCHEMA_UNSUPPORTED')
        for field in ('project_id','batch_id'):
            value=bound();del value[field];self.error(value,'BINDING_MIRROR_CONFLICT')
            value=bound();value[field]='other';self.error(value,'BINDING_MIRROR_CONFLICT')
        for path,key in [(('scope_binding',),'mission_id'),(('scope_binding','mapping'),'runtime_release_id'),(('scope_binding','creation_key_scope'),'project_id'),(('scope_binding','mapping'),'formal_authority_ref'),(('scope_binding','mapping'),'batch_id')]:
            value=bound();target(value,path)[key]='other';self.error(value,'BINDING_IDENTITY_CONFLICT')

    def test_numbers_dates_digests_and_utf8(self):
        for field in ('date_revision','relation_revision','access_scope_revision'):
            for wrong in (0,-1,9223372036854775808,True,1.0):
                value=bound();value['scope_binding'][field]=wrong;self.error(value)
            value=bound();value['scope_binding'][field]=9223372036854775807;parse_scope(value)
            for token in ('1e0','1.0','true'):
                raw=json.dumps(bound()).replace('"'+field+'": '+str(bound()['scope_binding'][field]),'"'+field+'": '+token)
                with self.assertRaises(BindingStructureError):parse_mission_json(raw)
        for path in (('scope_binding',), ('scope_binding','mapping')):
            for token in ('1e0','1.0','true'):
                value=bound(); obj=target(value,path)
                raw=json.dumps(value)
                fragment=json.dumps(obj)
                raw=raw.replace(fragment,fragment.replace('"schema_version": 1','"schema_version": '+token,1),1)
                with self.assertRaises(BindingStructureError):parse_mission_json(raw)
        for field in ('scope_digest','request_digest'):
            for bad in ('A'*64,'0'*63,'g'*64):
                value=bound();value['scope_binding'][field]=bad;self.error(value)
        for date in ('2026-02-29','20261111','2026-1-01'):
            value=bound();value['scope_binding']['release_date']=date;self.error(value)
        value=bound();value['scope_binding']['binding_ref']='中文\\"\x01\n'
        self.assertIn('中文'.encode(),parse_scope(value).binding_bytes)
        self.assertIn(b'\\u0001\\n',parse_scope(value).binding_bytes)

    def test_raw_global_duplicate_nonfinite_and_invalid_utf8(self):
        for path,obj in objects(bound()):
            raw=json.dumps(bound()); fragment=json.dumps(obj);key=next(iter(obj))
            duplicate=fragment[:-1]+','+json.dumps(key)+':'+json.dumps(obj[key])+'}'
            with self.assertRaises(BindingStructureError) as caught:parse_mission_json(raw.replace(fragment,duplicate,1))
            self.assertEqual(caught.exception.code,'MISSION_JSON_INVALID')
        for raw in (b'\xff',b'\xef\xbb\xbf{}','{"mission_id":"M","release_id":"R","extra":1e999}', '{"x":NaN}','{"x":Infinity}','{"x":"\\ud800"}','[]','null','{'):
            with self.assertRaises(BindingStructureError):parse_mission_json(raw)

    def test_immutability_every_binding_leaf_and_legacy_identity(self):
        original=bound()
        for path,obj in objects(original['scope_binding'],('scope_binding',)):
            for key,value in obj.items():
                if isinstance(value,dict):continue
                changed=bound()
                target(changed,path)[key] = value+1 if type(value) is int else ('2'*64 if key.endswith('digest') else 'other')
                with self.assertRaises(BindingStructureError):require_unchanged(original,changed)
        self.assertTrue(require_unchanged(original,copy.deepcopy(original)))
        for value in ({'mission_id':'M','release_id':'R'},):
            self.assertTrue(require_unchanged(value,dict(value,diagnostic_score=0.5)))
            for field in ('mission_id','release_id'):
                with self.assertRaises(BindingStructureError) as caught:require_unchanged(value,dict(value,**{field:'changed'}))
                self.assertEqual(caught.exception.code,'BINDING_IMMUTABLE_CONFLICT')
            with self.assertRaises(BindingStructureError):require_unchanged(value,original)
            with self.assertRaises(BindingStructureError):require_unchanged(original,value)
        changed=bound();changed['scope_binding']['creation_operation_ref']='op:2'
        with self.assertRaises(BindingStructureError) as caught:require_unchanged(original,changed)
        self.assertEqual(caught.exception.code,'BINDING_IMMUTABLE_CONFLICT')

    def test_public_tuple_forgery_stable_errors(self):
        for payload in (b'{}',b'[]',b'null',b'{',b'\xff'):
            with self.assertRaises(BindingStructureError):serialize_scope(ScopeIdentity('BOUND_STRUCTURAL_ONLY','M','R',payload))

    def test_no_io_input_unchanged_cold_process_stability(self):
        value=bound();original=copy.deepcopy(value)
        with patch('builtins.open',side_effect=AssertionError('no file IO')),patch('socket.socket',side_effect=AssertionError('no network')):
            scope=parse_scope(value);serialize_scope(scope);require_unchanged(value,value);parse_mission_json(json.dumps(value))
        self.assertEqual(value,original)
        script='import sys; from tools.dsh_workbench.mission_scope_binding_codec import *; print(parse_mission_json(sys.stdin.buffer.read()).scope.binding_bytes.hex())'
        results=[subprocess.check_output([sys.executable,'-c',script],input=json.dumps(value).encode(),cwd=str(pathlib.Path(__file__).resolve().parents[1])) for _ in range(2)]
        self.assertEqual(results[0],results[1]);self.assertEqual(results[0].decode().strip(),scope.binding_bytes.hex())


if __name__=='__main__':unittest.main()
