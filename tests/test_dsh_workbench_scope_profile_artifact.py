"""Pinned expected definitions cannot be relaxed through a changed JSON artifact."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.dsh_workbench.scope_source_policy_profile import PROFILE_ID,ReadOnlyScopeSourcePolicyQualification


class ScopeProfileArtifact(unittest.TestCase):
    def test_changed_same_id_profile_is_rejected_before_any_database_call(self):
        class Connection:
            autocommit=True
            def execute(self,*args):raise AssertionError('UNEXPECTED_DATABASE_CALL')
        changed=json.dumps({'profile_id':PROFILE_ID,'definitions':{'tables':{},'allowed_functions':[]}})
        with patch('tools.dsh_workbench.scope_source_policy_profile.Path.read_text',return_value=changed):
            with self.assertRaisesRegex(ValueError,'SCOPE_SOURCE_PROFILE_ARTIFACT_INVALID'):
                ReadOnlyScopeSourcePolicyQualification(Connection())

    def test_guard_parameter_or_ri_expectation_cannot_be_relaxed_with_same_profile_id(self):
        class Connection:
            autocommit=True
            def execute(self,*args):raise AssertionError('UNEXPECTED_DATABASE_CALL')
        path=Path(__file__).resolve().parents[1]/'tools/dsh_workbench/scope_source_profile_pg17.json'
        original=json.loads(path.read_text())
        for change in ('parameter','ri'):
            value=json.loads(json.dumps(original))
            if change=='parameter':value['guard_parameter_policy']['allow_set']=True
            else:value['definitions']['ri_triggers'].pop()
            with patch('tools.dsh_workbench.scope_source_policy_profile.Path.read_text',return_value=json.dumps(value)):
                with self.assertRaisesRegex(ValueError,'SCOPE_SOURCE_PROFILE_ARTIFACT_INVALID'):
                    ReadOnlyScopeSourcePolicyQualification(Connection())
