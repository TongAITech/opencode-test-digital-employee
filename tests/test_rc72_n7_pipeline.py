"""Concrete process/HTTP/cleanup integration; initial approvals are fixtures."""
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc72_formal_runner_support import formal_setup, LocalHTTPEnvironment
from rc72_n2_test_support import BATCH


def test_n7_pipeline_executes_formal_processes_cleans_and_independently_closes_full_plan(tmp_path,monkeypatch):
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch)
    try:
        output=tmp_path/'actual-output'
        environment=LocalHTTPEnvironment(url,output)
        runner=FormalN7RunnerAdapter(prep,evidence_root=output,environment_adapter=environment,
            execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
        pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured')
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['state']=='N7_PASS'
        assert len(server.calls)==len(plan['items'])
        assert all(lease['state']=='RELEASED' for lease in truth.query('rc72_data_lease'))
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==len(plan['items'])
    finally:
        server.shutdown();server.server_close()


def test_n7_pipeline_cold_resume_after_cleanup_and_before_review_receipt(tmp_path,monkeypatch):
    import pytest
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc7_runtime.rc72_n7_execution_preparation import ExecutionPreparationService
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch)
    output=tmp_path/'actual-output'
    def pipeline(preparation):
        runner=FormalN7RunnerAdapter(preparation,evidence_root=output,
            environment_adapter=LocalHTTPEnvironment(url,output),
            execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
        return N7PipelineService(preparation,runner=runner,capture_root=tmp_path/'captured')
    first=pipeline(prep)
    cleanup=first.cleanup.run
    def interrupt_after_cleanup(preparation_id):
        cleanup(preparation_id)
        raise KeyboardInterrupt('interrupted after durable cleanup')
    monkeypatch.setattr(first.cleanup,'run',interrupt_after_cleanup)
    try:
        with pytest.raises(KeyboardInterrupt):
            first.complete(release_batch_id=BATCH)
        assert len(server.calls)==1
        # A separate service graph and authority must consume durable receipts,
        # without restoring old business leases or repeating the first POST.
        cold=ExecutionPreparationService(truth,release_id=prep.release_id,source_commit=prep.source_commit,
            authority=RC72AuthorityRuntime(prep.authority._key),tool_registry=prep.tool_registry)
        second=pipeline(cold)
        def interrupt_before_review(bundle,assignment):
            raise KeyboardInterrupt('interrupted after review delivery')
        monkeypatch.setattr(second.finalization,'_run_review',interrupt_before_review)
        with pytest.raises(KeyboardInterrupt):
            second.complete(release_batch_id=BATCH)
        assert len(server.calls)==len(plan['items'])
        third=pipeline(cold)
        assert third.complete(release_batch_id=BATCH)['state']=='N7_PASS'
        assert len(server.calls)==len(plan['items'])
    finally:
        server.shutdown();server.server_close()


def test_n7_pipeline_unknown_external_effect_is_held_without_replay_or_cleanup(tmp_path,monkeypatch):
    import pytest
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch)
    output=tmp_path/'actual-output'
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,
        environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
    pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured')
    def interrupted(*args,**kwargs):
        runner(*args,**kwargs)
        raise KeyboardInterrupt('actual process returned before dispatch receipt persisted')
    pipeline.dispatch.adapters={name:interrupted for name in pipeline.dispatch.adapters}
    try:
        with pytest.raises(KeyboardInterrupt):
            pipeline.complete(release_batch_id=BATCH)
        assert len(server.calls)==1 and server.restored is False
        before=truth.store.path.read_bytes()
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_EXECUTION_DIAGNOSIS_REQUIRED'
        assert truth.store.path.read_bytes()==before
        assert len(server.calls)==1 and server.restored is False
        assert any(r['state']=='ACTIVE' for r in truth.query('rc72_data_lease'))
    finally:
        server.shutdown();server.server_close()


def test_n7_pipeline_rejected_independent_process_returns_hold_without_loop(tmp_path,monkeypatch):
    import sys
    import rc7_runtime.rc72_n7_finalization as finalization
    truth,plan,prep,server,url=formal_setup(tmp_path,monkeypatch)
    output=tmp_path/'actual-output'
    runner=FormalN7RunnerAdapter(prep,evidence_root=output,
        environment_adapter=LocalHTTPEnvironment(url,output),
        execution_env={'RC72_OUTPUT_ROOT':str(output)},timeout_seconds=30)
    pipeline=N7PipelineService(prep,runner=runner,capture_root=tmp_path/'captured')
    original_review=pipeline.finalization._run_review
    original_popen=finalization.subprocess.Popen
    def rejected_review(bundle,assignment):
        def malformed_process(command,**kwargs):
            return original_popen([sys.executable,'-I','-c','print("{}")'],**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(finalization.subprocess,'Popen',malformed_process)
            return original_review(bundle,assignment)
    monkeypatch.setattr(pipeline.finalization,'_run_review',rejected_review)
    try:
        result=pipeline.complete(release_batch_id=BATCH)
        assert result['reason']=='N7_INDEPENDENT_REVIEW_NOT_ACCEPTED'
        assert len(server.calls)==len(plan['items'])
        before=truth.store.path.read_bytes()
        assert pipeline.complete(release_batch_id=BATCH)==result
        assert truth.store.path.read_bytes()==before and len(server.calls)==len(plan['items'])
        assert truth.query('rc72_mission_node',node_type='N7_EXECUTION')[0]['state']=='REVIEW_PENDING'
    finally:
        server.shutdown();server.server_close()
