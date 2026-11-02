"""Compose actual N1-N6 runtime services; only external DSH/tool I/O is a fixture.

These checks prove repository integration, never real bank/Field capabilities.
"""
from copy import deepcopy

from rc7_runtime.rc72_mission_node_assignment import N1AgentTeamsAssignmentService
from rc7_runtime.rc72_n1_completion import N1GovernedHandoffService, N1DeliveryGateService
from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE


def install_execution_sources(tmp_path, monkeypatch):
    import rc72_n2_test_support as base
    import test_rc72_n1_completion as n1_fixture
    import test_rc72_n1_executable_binding as n1_binding_fixture
    import test_rc72_n4_test_design_handoff as n4_fixture
    from test_rc72_n6_executable_readiness import _binding
    for key, value in dict(BATCH=BATCH, COMMIT=COMMIT, MISSION=MISSION, RELEASE=RELEASE).items():
        monkeypatch.setattr(n1_fixture, key, value)
    runtime = n1_binding_fixture._binding()
    runtime.update(release_id=RELEASE, mission_id=MISSION, release_batch_id=BATCH, source_commit=COMMIT)

    def complete_n1(truth):
        base.start_n1(truth)
        N1AgentTeamsAssignmentService(truth, source_commit=COMMIT).assign(release_batch_id=BATCH)
        candidate = dict(status='CANDIDATE', facts=dict(
            release_id=RELEASE, release_batch_id=BATCH, source_commit=COMMIT,
            deployment_records=[dict(application_id='BLOAN', environment='FAT1', deployment_id='DEP-FIXTURE')],
            environment_checks=[dict(name='config-api', status='REACHABLE')],
            capability_checks=[dict(name='field-probe', status='AVAILABLE')],
            executable_bindings=[runtime],
        ), unknowns=[], gaps=[])
        launcher = n1_fixture._launcher(tmp_path, truth, candidate)
        N1GovernedHandoffService(truth, source_commit=COMMIT, launcher=launcher,
                                allowed_tools=['field-probe']).handoff(release_batch_id=BATCH)
        return N1DeliveryGateService(truth, source_commit=COMMIT).complete(release_batch_id=BATCH)

    monkeypatch.setattr(base, 'complete_n1', complete_n1)
    original_candidate = n4_fixture._candidate
    spec = _binding()

    def candidate(*args, **kwargs):
        value = original_candidate(*args, **kwargs)
        for case in value['cases']:
            case['execution'] = dict(
                binding_key=runtime['binding_key'], inputs=dict(fixture_input='explicit reviewed input'),
                request=deepcopy(spec['request']), cleanup=deepcopy(spec['cleanup']),
                authoritative_sources=[spec['request']['source_ref'], spec['cleanup']['source_ref']],
            )
        return value

    monkeypatch.setattr(n4_fixture, '_candidate', candidate)
