"""Local characterization of a confirmed integration GAP, not product QA.

Only TemporaryDirectory R1 fixtures are written. Passing means the current
missing binding and lossy typed round-trip were reproduced, not corrected.
Run explicitly; this is deliberately outside the regular W0 test pattern.
"""
from pathlib import Path
import tempfile
import unittest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Mission
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.bank_mission import start_or_resume
from rc7_admin.projection import AdminProjection, AdminProjectionError


class ScopeBindingGap(unittest.TestCase):
    def test_mission_constructor_does_not_accept_typed_binding(self):
        with self.assertRaises(TypeError):
            Mission(mission_id='M1', release_id='R1', goal='local audit',
                    project_id='P1', batch_id='B1')

    def test_official_start_resume_creates_unbound_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'audit-r1.jsonl'
            result = start_or_resume(r1_path=str(path), mission_id='M1',
                                     release_id='R1', goal='local audit', graph_version='v1')
            self.assertEqual(result['status'], 'STARTED')
            row = TruthRuntime(path).query('rc7_mission', mission_id='M1')[0]
            self.assertNotIn('project_id', row)
            self.assertNotIn('batch_id', row)
            resumed = start_or_resume(r1_path=str(path), mission_id='M1',
                                      release_id='R1', goal='local audit', graph_version='v1')
            self.assertEqual(resumed['status'], 'RESUMED')
            with self.assertRaisesRegex(AdminProjectionError, 'R1_MISSION_SCOPE_UNRESOLVED'):
                AdminProjection(TruthRuntime(path)).mission_overview_scoped(
                    mission_id='M1', project_id='P1', batch_id='B1')

    def test_synthetic_extra_binding_is_dropped_by_formal_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            truth = TruthRuntime(Path(tmp) / 'audit-r1.jsonl')
            control = ClosedLoopControlPlane.bootstrap(
                truth, Mission(mission_id='M1', release_id='R1', goal='local audit'))
            row = truth.query('rc7_mission', mission_id='M1')[0]
            row.update(project_id='P1', batch_id='B1', artifact_version=row['artifact_version'] + 1)
            truth.append_atomic('RC7_MISSION_UPSERTED', row)
            before = AdminProjection(truth).mission_overview_scoped(
                mission_id='M1', project_id='P1', batch_id='B1')
            self.assertEqual(before['mission']['batch_id'], 'B1')
            control.refresh_ready()
            after = truth.query('rc7_mission', mission_id='M1')[0]
            self.assertNotIn('project_id', after)
            self.assertNotIn('batch_id', after)
            with self.assertRaisesRegex(AdminProjectionError, 'R1_MISSION_SCOPE_UNRESOLVED'):
                AdminProjection(truth).mission_overview_scoped(
                    mission_id='M1', project_id='P1', batch_id='B1')


if __name__ == '__main__':
    unittest.main()
