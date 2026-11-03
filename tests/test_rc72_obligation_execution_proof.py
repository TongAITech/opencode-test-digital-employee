"""Actual accepted execution covers approved secondary obligations without replay."""
from copy import deepcopy
from pathlib import Path

import pytest
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc7_runtime.rc72_obligation_execution_proof import AcceptedObligationExecutionProof
from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
from rc7_runtime.rc72_state_machine import RC72StateMachine
from rc72_formal_runner_support import formal_setup,LocalHTTPEnvironment
from rc72_n2_test_support import BATCH,RELEASE,MISSION


@pytest.mark.parametrize('tamper',['process','evaluation','obligation','etu'])
def test_actual_accepted_cases_prove_primary_and_secondary_obligations_without_duplicate_attempts(tmp_path,monkeypatch,tamper):
    def approved_secondary(candidate):
        secondary=deepcopy(candidate['obligations'][0])
        secondary['obligation_id'] += '-SECONDARY'
        secondary['business_scope'] += ' approved secondary coverage'
        candidate['obligations'].append(secondary)
        for case in candidate['cases']:
            case['coverage_links'].append(dict(subject_id=secondary['obligation_id'],
                evidence_ref=secondary['evidence_refs'][0]))
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch,design_mutator=approved_secondary)
    try:
        output=tmp_path/'output'
        runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=LocalHTTPEnvironment(url,output),
            execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
        pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'capture')
        proof=AcceptedObligationExecutionProof(pipeline)
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match='ACCEPTED_N7_REQUIRED'):
            proof.audit(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before and not server.calls
        assert pipeline.complete(release_batch_id=BATCH)['state']=='N7_PASS'
        before=truth.store.path.read_bytes()
        audited=proof.audit(release_batch_id=BATCH)
        assert truth.store.path.read_bytes()==before
        assert len(audited['obligations'])==2*len(plan['items'])
        assert audited['case_count']==len(plan['items'])==len(server.calls)
        assert len(audited['attempt_ids'])==len(plan['items'])
        primary={r['case_ids'][0]:r for r in audited['obligations'] if not r['secondary_case_ids']}
        for secondary in (r for r in audited['obligations'] if r['secondary_case_ids']):
            assert secondary['attempt_ids']==primary[secondary['case_ids'][0]]['attempt_ids']
            assert secondary['source_case_sha256s']==primary[secondary['case_ids'][0]]['source_case_sha256s']
        from rc7_runtime.rc72_release_scope import ReleaseScopeService, ReleaseScopeManifest
        from rc7_runtime.rc72_canonical_design import CanonicalDesignService
        design=CanonicalDesignService(truth,release_id=RELEASE,source_commit=prep.source_commit).load(release_batch_id=BATCH)
        pairs={r:sorted({c['sst_id'] for c in design.cases if c['requirement_id']==r})
               for r in design.batch['requirement_ids']}
        ReleaseScopeService(truth,release_id=RELEASE).persist_manifest(ReleaseScopeManifest(
            manifest_id='SCOPE-FORMAL-OBLIGATION-PROOF',mission_id=MISSION,release_batch_id=BATCH,
            requirement_ssts=pairs,required_levels_by_sst={s:['L1','L2','L3','L4','L5','L6','L7']
                for ssts in pairs.values() for s in ssts},source_refs=['engineering://full-scope-policy']))
        aggregator=ReleaseConvergenceAggregator(truth,release_id=RELEASE,
            runtime=RC72StateMachine(truth,release_id=RELEASE),execution_proof=proof)
        snapshot=aggregator.aggregate(mission_id=MISSION)
        assert snapshot.proven_obligation_ids==audited['verified_obligation_ids']
        assert snapshot.unproven_obligation_ids==[]
        assert snapshot.facts.required_l1_l7_completion is False
        assert truth.query('rc7_mission')[0]['state']!='CONVERGED'
        assert len(server.calls)==len(plan['items'])
        # Historical PASS labels cannot hide changed admitted evidence/lineage.
        if tamper=='process':
            review=truth.query('rc72_n7_execution_review',review_result_id=audited['review_result_id'])[0]
            path=Path(review['stdout_ref'][len('file://'):])
            path.write_bytes(path.read_bytes()+b'changed')
            rejection='PROCESS_EVIDENCE_CHANGED'
        elif tamper=='evaluation':
            evaluation=next(r for r in truth.query('rc7_evaluation')
                if r.get('dimensions',{}).get('review_result_id')==audited['review_result_id'])
            evaluation.update(evaluator_ref='executor-masquerading-as-reviewer',artifact_version=evaluation['artifact_version']+1)
            truth.append_atomic('RC7_EVALUATION_UPSERTED',evaluation)
            rejection='CASE_FINALIZATION_REQUIRED'
        elif tamper=='etu':
            etu=truth.query('rc72_etu',etu_id=audited['etus'][0]['etu_id'])[0]
            etu.update(state='BLOCKED',artifact_version=etu['artifact_version']+1)
            truth.append_atomic('RC72_ETU_UPSERTED',etu)
            rejection='ETU_SCOPE_MISMATCH'
        else:
            secondary=next(r for r in audited['obligations'] if r['secondary_case_ids'])
            obligation=truth.query('rc72_test_obligation',obligation_id=secondary['obligation_id'])[0]
            obligation.update(business_rule='changed canonical lineage',artifact_version=obligation['artifact_version']+1)
            truth.append_atomic('RC72_TEST_OBLIGATION_UPSERTED',obligation)
            rejection='CANONICAL_OBLIGATION_CHANGED'
        before=truth.store.path.read_bytes()
        with pytest.raises(ContractError,match=rejection):
            aggregator.aggregate(mission_id=MISSION)
        assert truth.store.path.read_bytes()==before
        assert len(server.calls)==len(plan['items'])
    finally:
        server.shutdown();server.server_close()
