"""Pure V3 structural tests: no provenance/authority or product acceptance claim."""
import copy
import hashlib
import json
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.dsh_workbench.scope_snapshot_codec import (
    ScopeStructureError, canonical_scope_bytes, scope_digest, parse_snapshot_json,
    creation_key, unavailable_host_admission,
)


def snapshot():
    return {'schema_version': 1, 'project_id': 'P', 'batch_id': 'B',
            'release_date': '2026-11-11', 'date_revision': 1, 'relation_revision': 2,
            'access_scope_revision': 3,
            'filters': {'requirement_ids': [], 'version_ids': [], 'sst_ids': []},
            'edges': [{'requirement_id': 'R', 'system_id': 'S', 'version_id': 'V', 'sst_id': None,
                       'requirement_source': {'kind': 'REQUIREMENT_IDENTITY', 'source_system': 'x', 'source_namespace': 'n', 'source_object_id': 'r', 'source_revision': '1', 'source_ref': 'ref:r'},
                       'version_source': {'kind': 'SYSTEM_VERSION_IDENTITY', 'source_system': 'x', 'source_namespace': 'n', 'source_object_id': 'v', 'source_revision': '1'},
                       'brv_source': {'kind': 'VERIFIED_REQUIREMENT_VERSION', 'source_link_ref': 'ref:rv', 'source_revision': '1'}, 'sst_source': None, 'brvs_source': None}]}


GOLDEN = b'{"access_scope_revision":3,"batch_id":"B","date_revision":1,"edges":[{"brv_source":{"kind":"VERIFIED_REQUIREMENT_VERSION","source_link_ref":"ref:rv","source_revision":"1"},"brvs_source":null,"requirement_id":"R","requirement_source":{"kind":"REQUIREMENT_IDENTITY","source_namespace":"n","source_object_id":"r","source_ref":"ref:r","source_revision":"1","source_system":"x"},"sst_id":null,"sst_source":null,"system_id":"S","version_id":"V","version_source":{"kind":"SYSTEM_VERSION_IDENTITY","source_namespace":"n","source_object_id":"v","source_revision":"1","source_system":"x"}}],"filters":{"requirement_ids":[],"sst_ids":[],"version_ids":[]},"project_id":"P","relation_revision":2,"release_date":"2026-11-11","schema_version":1}'


class Codec(unittest.TestCase):
    def reject(self, value):
        with self.assertRaises(ScopeStructureError):
            canonical_scope_bytes(value)

    def test_full_golden_and_detached_roundtrip(self):
        value = snapshot()
        self.assertEqual(canonical_scope_bytes(value), GOLDEN)
        self.assertEqual(scope_digest(value), '86048f9023f4d38a02b0a90c748630d78aa3aae33af78895d3e00874ce6e0e99')
        self.assertEqual(canonical_scope_bytes(parse_snapshot_json(GOLDEN)), GOLDEN)
        parsed = parse_snapshot_json(GOLDEN)
        parsed['edges'][0]['requirement_id'] = 'changed'
        self.assertEqual(canonical_scope_bytes(value), GOLDEN)

    def test_unknown_missing_each_key_and_duplicate_json_keys(self):
        def walk(obj, path=()):
            if isinstance(obj, dict):
                yield path, obj
                for key, value in obj.items():
                    yield from walk(value, path + (key,))
            elif isinstance(obj, list):
                for i, value in enumerate(obj):
                    yield from walk(value, path + (i,))
        for path, obj in walk(snapshot()):
            for key in list(obj) + ['unknown']:
                value = snapshot()
                target = value
                for part in path:
                    target = target[part]
                if key == 'unknown':
                    target[key] = 'x'
                else:
                    del target[key]
                with self.subTest(path=path, key=key):
                    self.reject(value)
            # Exercise the strict parser at every object depth.
            value = snapshot()
            target = value
            for part in path:
                target = target[part]
            key = next(iter(target))
            encoded = json.dumps(value)
            fragment = json.dumps(target)
            duplicate = fragment[:-1] + ',' + json.dumps(key) + ':' + json.dumps(target[key]) + '}'
            with self.assertRaises(ScopeStructureError):
                parse_snapshot_json(encoded.replace(fragment, duplicate, 1))

    def test_numbers_and_dates(self):
        for field in ('schema_version', 'date_revision', 'relation_revision', 'access_scope_revision'):
            for number in (True, False, 1.0, 0, -1, 9223372036854775808):
                value = snapshot(); value[field] = number
                self.reject(value)
        value = snapshot(); value['date_revision'] = 9223372036854775807
        canonical_scope_bytes(value)
        for token in ('1e0', '1.0', 'NaN', 'Infinity'):
            with self.assertRaises(ScopeStructureError):
                parse_snapshot_json(GOLDEN.replace(b'"date_revision":1', ('"date_revision":' + token).encode()))
        for date in ('2026-02-29', '20261111', '2026-1-01', None):
            value = snapshot(); value['release_date'] = date; self.reject(value)

    def test_unicode_and_escaping(self):
        value = snapshot(); value['project_id'] = '中文\\"\x01\b\t\n\f\r/\u2028'
        encoded = canonical_scope_bytes(value)
        self.assertIn('中文'.encode(), encoded)
        self.assertIn(b'\\\\\\"\\u0001\\b\\t\\n\\f\\r/', encoded)
        self.assertIn('\u2028'.encode(), encoded)
        for bad in ('\ud800', '\udfff', ' ', ''):
            value = snapshot(); value['project_id'] = bad; self.reject(value)
        for raw in (b'\xff', b'\xef\xbb\xbf{}'):
            with self.assertRaises(ScopeStructureError): parse_snapshot_json(raw)

    def test_multiple_requirements_shared_version_distinct_sst_and_order(self):
        value = snapshot(); first = value['edges'][0]
        first['sst_id'] = 'T1'
        first['sst_source'] = dict(first['requirement_source'], kind='SST_IDENTITY', source_object_id='t1')
        first['brvs_source'] = {'kind': 'VERIFIED_SST_LINK', 'source_link_ref': 'ref:t1', 'verified_source_revision': 'r1'}
        second = copy.deepcopy(first)
        second.update(requirement_id='R2', sst_id='T2')
        second['requirement_source']['source_object_id'] = 'r2'
        second['sst_source']['source_object_id'] = 't2'
        second['brvs_source']['source_link_ref'] = 'ref:t2'
        value['edges'].append(second)
        expected = canonical_scope_bytes(value)
        value['edges'].reverse()
        self.assertEqual(canonical_scope_bytes(value), expected)
        changed = copy.deepcopy(value); changed['edges'][0]['sst_id'] = 'T3'
        self.assertNotEqual(scope_digest(value), scope_digest(changed))
        for field in ('requirement_ids', 'version_ids', 'sst_ids'):
            bad = copy.deepcopy(value); bad['filters'][field] = ['missing']; self.reject(bad)
        duplicate = copy.deepcopy(value); duplicate['edges'].append(copy.deepcopy(value['edges'][0])); self.reject(duplicate)

    def test_source_conflict_and_unsplit_rules(self):
        value = snapshot(); other = copy.deepcopy(value['edges'][0]); other['system_id'] = 'S2'
        value['edges'].append(other); self.reject(value)
        value = snapshot(); other = copy.deepcopy(value['edges'][0]); other['version_id'] = 'V2'
        other['requirement_source']['source_revision'] = '2'; value['edges'].append(other); self.reject(value)
        for field in ('sst_source', 'brvs_source'):
            value = snapshot(); value['edges'][0][field] = {}; self.reject(value)
        value = snapshot(); value['edges'][0]['brv_source']['kind'] = 'VERIFIED_SST_LINK'; self.reject(value)
        value = snapshot(); value['edges'] = []; self.reject(value)
        value = snapshot(); value['filters']['requirement_ids'] = ['R', 'R']; self.reject(value)

    def test_split_source_every_key_and_duplicate_parser(self):
        value = snapshot(); edge = value['edges'][0]
        edge['sst_id'] = 'T'
        edge['sst_source'] = dict(edge['requirement_source'], kind='SST_IDENTITY')
        edge['brvs_source'] = {'kind': 'VERIFIED_SST_LINK', 'source_link_ref': 'link', 'verified_source_revision': '1'}
        canonical_scope_bytes(value)
        for field in ('sst_source', 'brvs_source'):
            for key in list(edge[field]) + ['unknown']:
                bad = copy.deepcopy(value)
                if key == 'unknown': bad['edges'][0][field][key] = 'x'
                else: del bad['edges'][0][field][key]
                self.reject(bad)
            raw = json.dumps(value)
            fragment = json.dumps(edge[field])
            duplicate = fragment[:-1] + ',"kind":' + json.dumps(edge[field]['kind']) + '}'
            with self.assertRaises(ScopeStructureError):
                parse_snapshot_json(raw.replace(fragment, duplicate, 1))
        bad = copy.deepcopy(value)
        other = copy.deepcopy(edge); other['version_id'] = 'V2'
        bad['edges'].append(other)
        self.reject(bad)  # wb.sst_identity UNIQUE(project_id,sst_id)
        bad = copy.deepcopy(value)
        other = copy.deepcopy(edge); other['sst_id'] = None
        other['sst_source'] = other['brvs_source'] = None
        bad['edges'].append(other)
        self.reject(bad)  # split and UNSPLIT cannot coexist for a BRV

    def test_unhashable_id_and_nullable_inputs_stable_rejection_unchanged(self):
        for field in ('project_id', 'batch_id'):
            for malformed in ([], {}, [1], {'x': 1}, None, True):
                value = snapshot(); value[field] = malformed
                original = copy.deepcopy(value)
                with self.subTest(field=field, malformed=malformed):
                    self.reject(value)
                    self.assertEqual(value, original)
        for field in ('requirement_id', 'system_id', 'version_id', 'sst_id',
                      'requirement_source', 'version_source', 'brv_source',
                      'sst_source', 'brvs_source'):
            for malformed in ([], {}, [1], {'x': 1}, True):
                value = snapshot(); value['edges'][0][field] = malformed
                original = copy.deepcopy(value)
                with self.subTest(field=field, malformed=malformed):
                    self.reject(value)
                    self.assertEqual(value, original)
        for field in ('requirement_ids', 'version_ids', 'sst_ids'):
            for malformed in ([], {}, [1], {'x': 1}, None, True):
                value = snapshot(); value['filters'][field] = [malformed]
                original = copy.deepcopy(value)
                with self.subTest(field=field, malformed=malformed):
                    self.reject(value)
                    self.assertEqual(value, original)
        for malformed in ([], {}, [1], {'x': 1}, None, True):
            with self.assertRaises(ScopeStructureError):
                creation_key('a', malformed, 'p', 'k')

    def test_sst_filter_rejects_extra_unsplit_raw_and_parse(self):
        value = snapshot(); split = value['edges'][0]
        split['sst_id'] = 'SST1'
        split['sst_source'] = dict(split['requirement_source'], kind='SST_IDENTITY')
        split['brvs_source'] = {'kind': 'VERIFIED_SST_LINK', 'source_link_ref': 'link', 'verified_source_revision': '1'}
        unsplit = snapshot()['edges'][0]
        unsplit['requirement_id'] = 'R2'
        unsplit['requirement_source']['source_object_id'] = 'r2'
        value['edges'].append(unsplit)
        # With no SST filter, a split requirement and a different unsplit
        # requirement sharing the version are structurally legitimate.
        original = copy.deepcopy(value)
        canonical_scope_bytes(value)
        parse_snapshot_json(json.dumps(value))
        self.assertEqual(value, original)
        value['filters']['sst_ids'] = ['SST1']
        original = copy.deepcopy(value)
        self.reject(value)
        with self.assertRaises(ScopeStructureError):
            parse_snapshot_json(json.dumps(value))
        self.assertEqual(value, original)
        # The filter selects only split edges; all requested IDs remain covered.
        value['edges'].pop()
        original = copy.deepcopy(value)
        canonical_scope_bytes(value)
        parse_snapshot_json(json.dumps(value))
        self.assertEqual(value, original)
        value['filters']['sst_ids'].append('SST2')
        original = copy.deepcopy(value)
        self.reject(value)
        with self.assertRaises(ScopeStructureError):
            parse_snapshot_json(json.dumps(value))
        self.assertEqual(value, original)

    def test_immutable_key_and_default_hold(self):
        key = creation_key('authority', 'alice', 'P', 'key')
        self.assertEqual(tuple(key), ('authority', 'alice', 'P', 'key'))
        with self.assertRaises(AttributeError): key.actor_ref = 'bob'
        for value in ('', '\ud800', None, True):
            with self.assertRaises(ScopeStructureError): creation_key('a', value, 'p', 'k')
        self.assertEqual(unavailable_host_admission(), ('HOLD', 'HOST_CAPABILITY_UNAVAILABLE'))

    def test_input_unchanged_no_io_and_cross_process(self):
        value = snapshot(); original = copy.deepcopy(value)
        with patch('builtins.open', side_effect=AssertionError('IO forbidden')), patch('socket.socket', side_effect=AssertionError('network forbidden')):
            canonical_scope_bytes(value); scope_digest(value); creation_key('a','b','c','d'); unavailable_host_admission()
        self.assertEqual(value, original)
        program = 'import sys; from tools.dsh_workbench.scope_snapshot_codec import *; print(scope_digest(parse_snapshot_json(sys.stdin.buffer.read())))'
        results = [subprocess.check_output([sys.executable, '-c', program], input=GOLDEN, cwd=str(pathlib.Path(__file__).resolve().parents[1])) for _ in range(2)]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0].decode().strip(), scope_digest(value))


if __name__ == '__main__': unittest.main()
