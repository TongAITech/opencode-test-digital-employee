"""C07 genuine Captain Mission must never execute N9 via unfenced DSH lease.

Real localhost SUT failure, actual frozen N8 process/Oracle, canonical R1,
Captain-fenced N9 WorkItem and cold-safe replay. The tested DSH executor is
forbidden to run until independent signed Captain-to-DSH Worker binding exists.
No claim of real bank AgentTeams Field, RCA or product defect.
"""
import sys

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n9_professional_dsh import NativeN9ProfessionalDshAnalysisService
from rc72_n2_test_support import BATCH
from test_rc72_n9_captain_qualification import _setup_fenced_business_failure


def _analyst(truth, pipeline, tmp_path, calls):
    patch = tmp_path / 'n9-patch.json'
    patch.write_text('{}')
    def never_launch(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('Captain N9 cannot bypass a signed AgentTeams Worker binding')
    launcher = DshHeadlessWorkerLauncher(
        dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
        truth=truth, authority=RC72AuthorityRuntime(b'c07-n9-independent-worker-authority'),
        coordinator_instance_id='rc72-n9-independent-professional',
        release_id=pipeline.release_id,
        state_root=str(tmp_path / 'n9-professional-dsh-runtime'),
        command_runner=never_launch)
    return NativeN9ProfessionalDshAnalysisService(
        pipeline, launcher=launcher, allowed_tools=('read_only_diagnostic',))


def test_captain_n9_requires_signed_worker_bridge_without_launch_or_r1_change(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        failure = pipeline.complete(release_batch_id=BATCH)
        assert failure['failure_class'] == 'VALID_TEST_FAILURE'
        assert failure['qualification_admission_id']
        assert len(server.calls) == 1
        calls = []
        analyst = _analyst(truth, pipeline, tmp_path, calls)
        before = truth.store.path.read_bytes()
        for _ in range(2):
            result = analyst.analyze(
                preparation_id=failure['preparation_id'],
                diagnosis_id=failure['diagnosis_id'])
            assert result['status'] == 'HOLD'
            assert result['reason'] == 'N9_DSH_CAPTAIN_SIGNED_WORKER_BINDING_REQUIRED'
            assert result['qualification_admission_id'] == failure['qualification_admission_id']
            assert result['worker_id'] == failure['qualification_worker_id']
            assert result['session_id'] == failure['qualification_session_id']
            assert result['defect_confirmed'] is False
            assert result['reproduction_completed'] is False
            assert result['field_verified'] is False and result['bank_final'] is False
            assert truth.store.path.read_bytes() == before
        assert not calls
        assert len(server.calls) == 1
        assert not truth.query('agent_runtime_event',
                              scope='task:' + failure['qualification_workitem_id'])
        assert not truth.query('rc72_n9_professional_dsh_analysis')
        assert not truth.query('rc7_defect')
        assert not truth.query('rc72_node_gate', node_type='N9_DEFECT')
    finally:
        server.shutdown()
        server.server_close()


def test_captain_owned_n9_cannot_silently_rebuild_as_legacy_dsh(
        tmp_path, monkeypatch):
    truth, plan, prep, server, pipeline, owner = _setup_fenced_business_failure(
        tmp_path, monkeypatch)
    try:
        failure = pipeline.complete(release_batch_id=BATCH)
        calls = []
        analyst = _analyst(truth, pipeline, tmp_path, calls)
        # Simulate a misconfigured cold host missing the original B Captain.
        pipeline.captain_scheduler = None
        before = truth.store.path.read_bytes()
        with pytest.raises(
                ContractError,
                match='N9_DSH_EXISTING_CAPTAIN_UNFENCED_LEGACY_ROUTE'):
            analyst.analyze(
                preparation_id=failure['preparation_id'],
                diagnosis_id=failure['diagnosis_id'])
        assert not calls
        assert len(server.calls) == 1
        assert truth.store.path.read_bytes() == before
        assert not truth.query('rc72_n9_professional_dsh_analysis')
        assert not truth.query('rc7_defect')
    finally:
        server.shutdown()
        server.server_close()
