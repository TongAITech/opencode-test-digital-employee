"""Pinned expected definitions cannot be relaxed through a changed JSON artifact."""
import json
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
