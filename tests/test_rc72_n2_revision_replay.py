from rc7_runtime.rc72_n2_completion import N2DeliveryGateService
from rc7_runtime.rc72_n2_revision import N2RevisionDispatchService

from rc72_n2_test_support import BATCH, COMMIT, REQUIREMENTS
from test_rc72_n2_completion import _seed_reviewed_requirements
from test_rc72_n2_revision import _drive_repair_to_evidence_pending


def test_same_failed_gate_replays_same_n2_revision_generation_worker_and_task(tmp_path):
    affected = REQUIREMENTS[0]
    truth, _ = _seed_reviewed_requirements(tmp_path, repair_requirement=affected)
    N2DeliveryGateService(truth, source_commit=COMMIT).complete(release_batch_id=BATCH)
    _drive_repair_to_evidence_pending(truth, affected)

    service = N2RevisionDispatchService(truth, source_commit=COMMIT)
    first = service.plan_and_assign(release_batch_id=BATCH)
    second = service.plan_and_assign(release_batch_id=BATCH)

    assert first["status"] == "ASSIGNED"
    assert second["status"] == "RESUMED"
    assert len(first["revisions"]) == 1
    assert len(second["revisions"]) == 1
    a = first["revisions"][0]
    b = second["revisions"][0]
    assert a["revision_id"] == b["revision_id"]
    assert a["revision_generation"] == b["revision_generation"] == 2
    assert a["revision_workitem_id"] == b["revision_workitem_id"]
    assert a["revision_worker_instance_id"] == b["revision_worker_instance_id"]
    assert len(truth.query("rc72_n2_revision_receipt", release_batch_id=BATCH)) == 1
