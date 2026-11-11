"""Pure comparison of the nine-field descriptor and the 15/4/7 binding."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from test_dsh_workbench_mission_scope_binding_codec import bound
from tools.dsh_workbench.mission_scope_binding_codec import BindingStructureError, parse_scope
from tools.dsh_workbench.runtime_batch_mapping import parse_runtime_batch_mapping


def descriptor():
    return {
        'schema_version': 1,
        'formal_authority_ref': 'a1',
        'mapping_ref': 'map:1',
        'project_id': 'P1',
        'batch_id': 'B1',
        'runtime_release_id': 'RT1',
        'runtime_release_batch_id': 'RUN-BATCH1',
        'mission_id': 'M1',
        'creation_operation_ref': 'op:1',
    }


class RuntimeBatchMappingTest(unittest.TestCase):
    def setUp(self):
        self.scope = parse_scope(bound())

    def check_error(self, code, candidate, scope=None):
        with self.assertRaises(BindingStructureError) as result:
            parse_runtime_batch_mapping(candidate, self.scope if scope is None else scope)
        self.assertEqual(result.exception.code, code)

    def test_independent_ids_detachment_and_binding_wire(self):
        candidate = descriptor()
        result = parse_runtime_batch_mapping(candidate, self.scope)
        self.assertEqual((result.batch_id, result.runtime_release_id, result.runtime_release_batch_id),
                         ('B1', 'RT1', 'RUN-BATCH1'))
        self.assertEqual(result._asdict(), candidate)
        candidate['runtime_release_batch_id'] = 'different'
        self.assertEqual(result.runtime_release_batch_id, 'RUN-BATCH1')
        self.assertEqual(self.scope, parse_scope(bound()))

    def test_missing_extra_and_invalid_fields(self):
        invalid = 'RUNTIME_BATCH_MAPPING_INVALID'
        for field in descriptor():
            with self.subTest(field=field):
                candidate = descriptor()
                del candidate[field]
                self.check_error(invalid, candidate)
                for value in (None, True, [], {}):
                    self.check_error(invalid, dict(descriptor(), **{field: value}))
                if field != 'schema_version':
                    for value in ('', ' ', '\ud800', 1):
                        self.check_error(invalid, dict(descriptor(), **{field: value}))
        self.check_error(invalid, dict(descriptor(), request_digest='1' * 64))
        self.check_error(invalid, dict(descriptor(), schema_version=1.0))
        self.check_error('RUNTIME_BATCH_MAPPING_UNSUPPORTED', dict(descriptor(), schema_version=2))
        self.check_error(invalid, {**descriptor(), 0: 'extra'})
        self.check_error(invalid, None)

    def test_every_shared_identity_must_match_without_normalization(self):
        for field in descriptor().keys() - {'schema_version', 'runtime_release_batch_id'}:
            with self.subTest(field=field):
                candidate = descriptor()
                candidate[field] += ' '
                self.check_error('RUNTIME_BATCH_MAPPING_CONFLICT', candidate)
        self.check_error('RUNTIME_BATCH_MAPPING_REQUIRES_BOUND_SCOPE', descriptor(),
                         parse_scope({'mission_id': 'M1', 'release_id': 'RT1'}))

    def test_runtime_batch_is_structural_until_source_verification(self):
        for runtime_batch_id in ('RUN-BATCH1', 'RUN-BATCH2', '运行批次'):
            candidate = dict(descriptor(), runtime_release_batch_id=runtime_batch_id)
            self.assertEqual(parse_runtime_batch_mapping(candidate, self.scope).runtime_release_batch_id,
                             runtime_batch_id)
