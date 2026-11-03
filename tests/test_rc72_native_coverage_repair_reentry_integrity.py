"""Cold coverage-repair reentry must re-audit the frozen accepted proof."""

import pytest

from rc72_n2_test_support import BATCH
from test_rc72_native_coverage_diagnosis import _diagnosis
from test_rc72_native_coverage_repair import _accept_task
from rc7_runtime.models import ContractError, Evidence
from rc7_runtime.rc72_native_coverage_repair import NativeCoverageRepairService
from rc7_runtime.truth_overlay import append_entity


def test_reentry_and_convergence_reject_changed_repair_evidence_without_replay(tmp_path, monkeypatch):
    truth, plan, pipeline, business, server, diagnosis, gap = _diagnosis(tmp_path, monkeypatch)
    try:
        diagnosed = diagnosis.run(release_batch_id=BATCH, application_id=server.app, gap_id=gap)
        repair = NativeCoverageRepairService(diagnosis)
        _accept_task(
            truth,
            pipeline.release_id,
            diagnosed['investigation_workitem_id'],
            'coverage_path_investigation',
        )
        prepared = repair.prepare(release_batch_id=BATCH, application_id=server.app, gap_id=gap)
        _accept_task(
            truth,
            pipeline.release_id,
            prepared['repair_workitem_id'],
            'coverage_path_repair',
        )
        activated = repair.activate(release_batch_id=BATCH, application_id=server.app, gap_id=gap)
        assert activated['status'] == 'FRESH_N7_REQUIRED'

        boundary = truth.query('rc72_native_coverage_repair', repair_id=activated['repair_id'])[0]
        evidence_id = boundary['repair_evidence_refs'][0]
        current = truth.query('rc7_evidence', evidence_id=evidence_id)[0]
        append_entity(
            truth,
            Evidence(
                evidence_id=current['evidence_id'],
                mission_id=current['mission_id'],
                kind=current['kind'],
                source_ref=current['source_ref'],
                content_ref=current['content_ref'] + '/changed-after-acceptance',
                content_hash='c' * 64,
                subject_refs=list(current['subject_refs']),
            ),
            release_id=pipeline.release_id,
            artifact_version=current['artifact_version'] + 1,
        )

        before = truth.store.path.read_bytes()
        server_calls = len(server.calls)
        business_calls = len(business.calls)
        actions = (
            lambda: repair.activate(release_batch_id=BATCH, application_id=server.app, gap_id=gap),
            lambda: repair.reconcile_application(release_batch_id=BATCH, application_id=server.app),
        )
        for action in actions:
            with pytest.raises(ContractError, match='NATIVE_COVERAGE_REPAIR_BOUNDARY_PROOF_CHANGED'):
                action()
            assert truth.store.path.read_bytes() == before
            assert len(server.calls) == server_calls
            assert len(business.calls) == business_calls
    finally:
        server.shutdown()
        server.server_close()
        business.shutdown()
        business.server_close()
