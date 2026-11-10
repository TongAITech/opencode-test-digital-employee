import dataclasses
import hashlib
import json
import unittest
from tools.dsh_workbench import project_metadata_codec as c


def body(**overrides):
    value = dict(request_id='rename:1', expected_metadata_revision='1',
                 expected_access_scope_revision='2', changes={'name': ' 项目A '},
                 reason='批准改名')
    value.update(overrides)
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


class MetadataCodecTests(unittest.TestCase):
    def parse(self, raw=None):
        return c.parse_rename_request(body() if raw is None else raw, 'p1')

    def bad(self, code, raw):
        with self.assertRaises(c.MetadataProtocolError) as caught:
            c.parse_rename_request(raw, 'p1')
        self.assertEqual(code, caught.exception.code)
        self.assertEqual(code, str(caught.exception))

    def test_valid_name_key(self):
        request = self.parse()
        self.assertEqual('项目A', request.name)
        self.assertEqual('项目A'.encode(), request.name_key)
        self.assertEqual('1', request.expected_metadata_revision)

    def test_name_is_exact_not_casefold_or_nfc(self):
        for left, right in [('Alpha', 'alpha'), ('é', 'e\u0301')]:
            self.assertNotEqual(c.normalize_name(left), c.normalize_name(right))

    def test_only_ascii_space_trim(self):
        self.assertEqual('\u00a0A\u00a0', c.normalize_name(' \u00a0A\u00a0 '))
        self.assertEqual('\u3000', c.normalize_name('\u3000'))

    def test_all_c0_and_del_rejected_even_edges(self):
        for point in list(range(32)) + [127]:
            with self.subTest(point=point):
                self.bad('NAME_CONTROL_FORBIDDEN', body(changes={'name': chr(point) + 'A'}))

    def test_empty_and_scalar_limit(self):
        for name in ['', '  ', 'a' * 129, '😀' * 129]:
            self.bad('NAME_SCALAR_LIMIT', body(changes={'name': name}))

    def test_exact_scalar_and_utf8_boundary(self):
        request = self.parse(body(changes={'name': '😀' * 128}))
        self.assertEqual(512, len(request.name_key))
        self.assertEqual(128, len(request.name))
        self.assertEqual('a' * 128, c.normalize_name('a' * 128))
        # UTF8 maximum is 4 bytes/scalar, so the byte limit is defensive/redundant.

    def test_name_wrong_types(self):
        for name in [None, True, [], {}]:
            self.bad('NAME_INVALID_UTF8_OR_TYPE', body(changes={'name': name}))

    def test_name_python_surrogate(self):
        with self.assertRaises(c.MetadataProtocolError) as caught:
            c.normalize_name('\ud800')
        self.assertEqual('NAME_INVALID_UTF8_OR_TYPE', caught.exception.code)

    def test_revision_boundaries(self):
        for value in ['1', str(c.MAX_REVISION)]:
            self.assertEqual(value, c.parse_revision(value))
        for value in ['0', '-1', '+1', '01', '1 ', ' 1', '1.0', '1e3',
                      '١', str(c.MAX_REVISION + 1), '1' * 100, 1, True, None]:
            with self.subTest(value=value), self.assertRaises(c.MetadataProtocolError):
                c.parse_revision(value)

    def test_both_expected_revisions_checked(self):
        for field in ['expected_metadata_revision', 'expected_access_scope_revision']:
            self.bad('REVISION_INVALID', body(**{field: '01'}))

    def test_request_id_boundaries(self):
        self.parse(body(request_id='a' * 128))
        for value in ['', 'a' * 129, '中文', 'a b', 'x\n', None, True]:
            self.bad('REQUEST_ID_INVALID', body(request_id=value))

    def test_reason_utf8_boundary_and_exact_preservation(self):
        request = self.parse(body(reason='😀' * 512))
        self.assertEqual(2048, len(request.reason.encode()))
        self.bad('REASON_BYTE_LIMIT', body(reason='😀' * 512 + 'a'))
        self.assertEqual(' \n ', self.parse(body(reason=' \n ')).reason)
        self.assertEqual('', self.parse(body(reason='')).reason)
        for value in [None, [], True]:
            self.bad('REASON_INVALID_UTF8_OR_TYPE', body(reason=value))

    def test_raw_body_bytes_required(self):
        for raw in [body().decode(), bytearray(body()), None]:
            self.bad('BODY_BYTES_REQUIRED', raw)

    def test_raw_byte_budget_before_parse(self):
        raw = body()
        self.parse(raw + b' ' * (16384 - len(raw)))
        self.bad('BODY_BYTE_LIMIT', raw + b' ' * (16385 - len(raw)))
        escaped = body(changes={'name': 'A'}).replace(b'"A"', b'"' + b'\\u0041' * 128 + b'"')
        self.assertEqual('A' * 128, self.parse(escaped).name)

    def test_malformed_json_utf8_and_bom(self):
        self.bad('JSON_INVALID_UTF8', b'\xff')
        for raw in [b'', b'{', b'{} trailing', b'\xef\xbb\xbf{}']:
            self.bad('JSON_INVALID', raw)

    def test_escaped_surrogate_vs_valid_surrogate_pair(self):
        for raw in [body().replace('项目A'.encode(), b'\\ud800'),
                    body(reason='x').replace(b'"x"', b'"\\udfff"'),
                    body()[:-1] + b',"\\ud800":"x"}']:
            self.bad('JSON_INVALID_UNICODE', raw)
        self.assertEqual('😀', self.parse(body(changes={'name': 'x'}).replace(b'"x"', b'"\\ud83d\\ude00"')).name)

    def test_duplicate_keys_at_all_depths(self):
        for raw in [body()[:-1] + b',"request_id":"other"}',
                    body().replace(b'{"name":', b'{"name":"x","name":'),
                    body()[:-1] + b',"extra":{"x":true,"x":false}}',
                    body()[:-1] + b',"request\\u005fid":"other"}']:
            self.bad('JSON_DUPLICATE_KEY', raw)

    def test_numbers_never_revision_or_exponent(self):
        for token in [b'1', b'0.5', b'1e3', b'NaN', b'Infinity', b'-Infinity']:
            self.bad('JSON_NUMBER_FORBIDDEN', body().replace(b'"1"', token))

    def test_unknown_missing_and_non_object_fields(self):
        for raw in [b'[]', b'null', b'true', b'{}', body(principal='alice'),
                    body(namespace_ref='org'), body(action='other')]:
            self.bad('REQUEST_FIELDS_INVALID', raw)
        value = json.loads(body())
        for key in list(value):
            reduced = dict(value)
            del reduced[key]
            self.bad('REQUEST_FIELDS_INVALID', json.dumps(reduced).encode())

    def test_changes_allowlist(self):
        for value in [None, [], {}, {'name': 'A', 'owner': 'alice'}]:
            self.bad('CHANGES_FIELDS_INVALID', body(changes=value))

    def test_path_target_not_authority(self):
        for target in ['', None, '\ud800']:
            with self.assertRaises(c.MetadataProtocolError) as caught:
                c.parse_rename_request(body(), target)
            self.assertEqual('PROJECT_TARGET_INVALID', caught.exception.code)
        self.assertNotEqual(self.parse().payload_digest,
                            c.parse_rename_request(body(), 'p2').payload_digest)

    def test_deep_immutable(self):
        request = self.parse()
        for field in dataclasses.fields(request):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                setattr(request, field.name, 'tamper')
        self.assertTrue(all(type(getattr(request, field.name)) is str
                            for field in dataclasses.fields(request)))
        self.assertIs(type(request.canonical_bytes), bytes)
        self.assertFalse(hasattr(request, '__dict__'))
        with self.assertRaises(c.MetadataProtocolError):
            dataclasses.replace(request, reason=[])
        with self.assertRaises(c.MetadataProtocolError):
            dataclasses.replace(request, name=' A ')

    def test_canonical_replay_ignores_json_order_whitespace_escaping(self):
        original = self.parse()
        parsed = json.loads(body())
        parsed['changes']['name'] = '项目A'
        replay = self.parse(json.dumps(dict(reversed(list(parsed.items()))),
                                      ensure_ascii=True, indent=2).encode())
        self.assertEqual(original, replay)
        self.assertEqual(original.canonical_bytes, replay.canonical_bytes)
        self.assertEqual(original.payload_digest, replay.payload_digest)
        self.assertEqual(hashlib.sha256(original.canonical_bytes).hexdigest(), original.payload_digest)

    def test_fixed_golden_canonical_vector(self):
        request = self.parse(body(request_id='r1', changes={'name': ' A '}, reason=''))
        expected = ('{"action":"project.metadata.update/v1","changes":{"name":"A"},'
                    '"expected_access_scope_revision":"2","expected_metadata_revision":"1",'
                    '"name_policy":"project-name/utf8-exact-v1","project_id":"p1",'
                    '"reason":"","request_id":"r1",'
                    '"schema":"dsh-workbench/project-metadata-request/v1"}')
        self.assertEqual(expected.encode(), request.canonical_bytes)
        self.assertEqual('8bb996f25ca9a73b9ea2f64bcebcf87b77afdee6614124ba62a2d5104e01e969',
                         request.payload_digest)

    def test_digest_domain_separation(self):
        request = self.parse()
        for kwargs in [dict(expected_metadata_revision='2'),
                       dict(expected_access_scope_revision='3'), dict(reason='other'),
                       dict(changes={'name': '项目B'}), dict(request_id='rename:2')]:
            self.assertNotEqual(request.payload_digest, self.parse(body(**kwargs)).payload_digest)
        self.assertNotEqual(request.canonical_bytes, c._canonical(request, 'asset.update/v1'))

    def test_error_does_not_reflect_request_and_next_parse_recovers(self):
        before = self.parse()
        for unused in range(3):
            self.bad('CHANGES_FIELDS_INVALID', body(changes={'secret-sentinel': 'secret'}))
            self.assertEqual(before, self.parse())
            self.assertEqual(before.canonical_bytes, self.parse().canonical_bytes)

    def test_deep_json_fails_with_stable_error(self):
        self.bad('JSON_INVALID', b'[' * 4000 + b']' * 4000)

    def test_no_business_outcome_or_authority_fields(self):
        request = self.parse()
        for field in ['principal', 'namespace', 'admission', 'no_change', 'authorized', 'committed']:
            self.assertFalse(hasattr(request, field))


if __name__ == '__main__':
    unittest.main()
