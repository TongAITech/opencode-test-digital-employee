"""Native N10 must consume original policy proof, never a fitted manifest."""
import json,subprocess,sys
from pathlib import Path
import pytest

from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
from rc7_runtime.rc72_expected_scope_input import ExpectedScopeInputService
from rc7_runtime.rc72_n1_strict_pipeline import N1StrictPipelineService
from rc7_runtime.rc72_native_n1_launcher import NativeN1ReadDshLauncher
from rc7_runtime.rc72_native_n1_read_gate import N1ReadResource,TOOL
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc72_n2_test_support import BATCH,MISSION,COMMIT,RELEASE
from test_rc72_expected_scope_input import CHILD
from test_rc72_n9_accepted_scope import _accepted
from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service


def test_native_n1_original_policy_is_consumed_after_real_n7_and_cannot_be_reduced(tmp_path,monkeypatch):
    import rc72_integrated_test_support as support
    import rc72_n2_test_support as base
    import test_rc72_n1_executable_binding as binding_fixture
    from rc7_runtime.rc72_mission_node_assignment import N1AgentTeamsAssignmentService
    original_install=support.install_execution_sources
    providers=[];workers=[]
    def install(directory,mp):
        original_install(directory,mp)
        def native_n1(truth):
            base.start_n1(truth)
            N1AgentTeamsAssignmentService(truth,source_commit=COMMIT).assign(release_batch_id=BATCH)
            runtime=binding_fixture._binding()
            runtime.update(release_id=RELEASE,mission_id=MISSION,release_batch_id=BATCH,source_commit=COMMIT)
            runtime['tool_route']['family']='API'
            candidate=dict(status='CANDIDATE',facts=dict(release_id=RELEASE,release_batch_id=BATCH,source_commit=COMMIT,
                deployment_records=[dict(application_id='BLOAN',environment='FAT1',deployment_id='DEP-FIXTURE')],
                environment_checks=[dict(name='config-api',status='REACHABLE')],
                capability_checks=[dict(name='field-probe',status='AVAILABLE')],executable_bindings=[runtime]),unknowns=[],gaps=[])
            batch=truth.query('rc72_release_batch')[0]
            policy=dict(schema='RC72_EXPECTED_RELEASE_SCOPE_V1',release_id=RELEASE,release_batch_id=BATCH,
                mission_id=MISSION,source_commit=COMMIT,application_ids=batch['application_ids'],version_ids=batch.get('version_ids',[]),
                requirement_ssts={r:['SST-'+r] for r in batch['requirement_ids']},
                required_levels_by_sst={'SST-'+r:['L1','L2','L3','L4','L5','L6','L7'] for r in batch['requirement_ids']},
                source_refs=['catalog://independent-original-release-policy/v1'])
            source=directory/'original-policy.json';source.write_text(json.dumps(policy))
            fixture=directory/'n1-candidate.json';fixture.write_text(json.dumps(candidate))
            script=directory/'n1-native-policy.py'
            script.write_text(CHILD.replace('import json,os,subprocess,sys','import json,os,subprocess,sys\nfrom pathlib import Path')
                .replace("candidate=json.loads(values[1]['text'])","candidate=json.loads(Path(sys.argv[3]).read_text())"))
            patch=directory/'native-patch.json';patch.write_text('{}')
            def runner(command,**kwargs):
                workers.append(1)
                return subprocess.run([sys.executable,str(script),str(Path(__file__).resolve().parents[1]),
                    json.dumps(['release-batch://'+BATCH]),str(fixture)],**kwargs)
            launcher=NativeN1ReadDshLauncher(resources=[N1ReadResource('release-batch://'+BATCH,source)],
                dsh_bin=sys.executable,patch_path=str(patch),cwd=str(directory),truth=truth,
                authority=RC72AuthorityRuntime(b'n10-original-policy-key'),coordinator_instance_id='controller',release_id=RELEASE,
                state_root=str(directory/'native-state'),command_runner=runner)
            pipeline=N1StrictPipelineService(truth,source_commit=COMMIT,launcher=launcher,allowed_tools=[TOOL])
            provider=ExpectedScopeInputService(pipeline);providers.append(provider)
            result=pipeline.complete(release_batch_id=BATCH)
            provider.freeze(release_batch_id=BATCH)
            return result
        mp.setattr(base,'complete_n1',native_n1)
    monkeypatch.setattr(support,'install_execution_sources',install)
    truth,plan,pipeline,server=_accepted(tmp_path,monkeypatch)
    try:
        pipeline.complete(release_batch_id=BATCH)
        AcceptedScopeN9Service(pipeline).complete(release_batch_id=BATCH)
        assert len(providers)==len(workers)==1
        aggregator=ReleaseConvergenceAggregator(truth,release_id=RELEASE,runtime=RC72StateMachine(truth,release_id=RELEASE),
            execution_proof=AcceptedObligationExecutionProof(pipeline),expected_scope=providers[0])
        result=aggregator.aggregate(mission_id=MISSION)
        assert 'scope:EXPECTED_INPUT_PROOF_REQUIRED' not in result.blockers
        assert any(b.startswith('scope:missing-level:') for b in result.blockers)
        assert result.facts.required_l1_l7_completion is False and result.result.value=='NOT_CONVERGED'
        assert len(server.calls)==len(plan['items']) and len(workers)==1
        legacy=ReleaseConvergenceAggregator(truth,release_id=RELEASE,runtime=RC72StateMachine(truth,release_id=RELEASE))
        unverified=legacy.aggregate(mission_id=MISSION)
        assert 'scope:EXPECTED_INPUT_PROOF_REQUIRED' in unverified.blockers
        assert 'execution:NATIVE_ACCEPTED_PROOF_REQUIRED' in unverified.blockers
        assert unverified.facts.requirement_completion is False
        row=truth.query('rc72_release_scope_manifest')[0]
        row['required_levels_by_sst']={k:['L3'] for k in row['required_levels_by_sst']}
        row['artifact_version']+=1;truth.append_atomic('RC72_RELEASE_SCOPE_MANIFEST_UPSERTED',row)
        before=truth.store.path.read_bytes()
        with pytest.raises(Exception,match='FROZEN_MANIFEST_CHANGED'):aggregator.aggregate(mission_id=MISSION)
        assert truth.store.path.read_bytes()==before and len(server.calls)==len(plan['items']) and len(workers)==1
    finally:server.shutdown();server.server_close()


def test_declared_callbacks_cannot_replace_native_convergence_inputs(tmp_path):
    from types import SimpleNamespace
    from rc6_runtime.truth import TruthRuntime
    truth=TruthRuntime(tmp_path/'r1.jsonl')
    runtime=RC72StateMachine(truth,release_id=RELEASE)
    before=truth.store.path.read_bytes() if truth.store.path.exists() else b''
    with pytest.raises(Exception,match='NATIVE_RUNTIME_REQUIRED'):
        ReleaseConvergenceAggregator(truth,release_id=RELEASE,
            runtime=SimpleNamespace(truth=truth,release_id=RELEASE,evaluate_convergence=lambda value:'CONVERGED'))
    aggregator=ReleaseConvergenceAggregator(truth,release_id=RELEASE,runtime=runtime)
    aggregator.execution_proof=SimpleNamespace(truth=truth,release_id=RELEASE,audit=lambda **kwargs:{'verified_obligation_ids':[]})
    with pytest.raises(Exception,match='NATIVE_EXECUTION_PROOF_SCOPE_REQUIRED'):
        aggregator.aggregate(mission_id=MISSION)
    aggregator.execution_proof=None
    aggregator.expected_scope=SimpleNamespace(truth=truth,source_commit=COMMIT,freeze=lambda **kwargs:{'manifest_id':'fake'})
    with pytest.raises(Exception,match='EXPECTED_SCOPE_PROVIDER_REQUIRED'):
        aggregator.aggregate(mission_id=MISSION)
    assert (truth.store.path.read_bytes() if truth.store.path.exists() else b'')==before
