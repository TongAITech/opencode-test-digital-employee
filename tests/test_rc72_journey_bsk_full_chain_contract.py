"""BSK-first canonical C09 end-to-end engineering composition.

Uses simulated B signer/Human verifier and fake BSK CLI for deterministic
CI. This proves design wiring only; NOT real Field approval or bank SUT.
"""
import time
from pathlib import Path

from rc7_runtime.models import Task
from rc7_runtime.rc72_browser_resources import BrowserAccessMode
from rc7_runtime.rc72_domain import ExecutionTaskUnit
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_journey_bsk_field import (
    JourneyBSKCertifiedFieldAdapter, bsk_field_scope_digest)
from rc7_runtime.rc72_journey_bsk_import import BSKJourneyTeachingImporter
from rc7_runtime.rc72_journey_benchmark import JourneyBenchmarkService, JourneyBenchmarkPolicy
from rc7_runtime.rc72_journey_compiler import JourneyCompiler
from rc7_runtime.rc72_journey_promotion import (
    JourneyPromotionService, approval_scope_digest)
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
from rc7_runtime.truth_overlay import append_entity

from test_rc72_journey_bsk_import import _fixture, _invoke
from test_rc72_journey_bsk_native_adapter import TestBSK


class FakeBankHumanVerifier:
    verifier_kind = "SIMULATED_HUMAN_BANK_GATE_NOT_FIELD"

    def __init__(self, truth):
        self.truth = truth

    def resolve(self, ref):
        candidate = self.truth.query("rc72_journey_candidate", candidate_id="JC-ALL")[0]
        benchmark = self.truth.query("rc72_journey_benchmark", benchmark_id="JB-ALL")[0]
        return {
            "attestation_ref": ref,
            "actor_type": "HUMAN", "field_verified": True,
            "decision": "APPROVED",
            "human_actor_ref": "test://simulated-human-not-bank",
            "rationale": "engineering contract validation only",
            "evidence_refs": ["evidence://mock-human-signer"],
            "issued_at": int(time.time()),
            "candidate_id": "JC-ALL", "benchmark_id": "JB-ALL",
            "candidate_artifact_version": candidate["artifact_version"],
            "benchmark_artifact_version": benchmark["artifact_version"],
            "release_batch_id": candidate["release_batch_id"],
            "requirement_id": candidate["requirement_id"],
            "sst_id": candidate["sst_id"],
            "obligation_id": candidate["obligation_id"],
            "case_id": candidate["case_id"],
            "scope_digest": approval_scope_digest(candidate, benchmark),
        }


def _start_attempt(truth, pool, *, item, attempt, worker, session,
                   artifact, purpose):
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    append_entity(truth, Task(
        task_id=item, mission_id="M-1",
        node="N7_EXECUTION" if purpose == "OFFICIAL_JOURNEY_EXECUTION" else "N6_EXECUTABLE_READINESS",
        task_type="OFFICIAL_JOURNEY_EXECUTION" if purpose == "OFFICIAL_JOURNEY_EXECUTION" else "JOURNEY_REPLAY",
        objective="BSK full chain contract", required_capabilities=["browser:write"],
        input_artifact_refs=["ETU-1", artifact],
        acceptance_criteria=["real evidence references required"]),
        release_id="RC7.2")
    repo.persist(WorkItemAttemptBinding(
        binding_id="BIND-" + item, mission_id="M-1",
        etu_id="ETU-1", workitem_id=item, case_id="TC-1",
        attempt_id=attempt, worker_id=worker, session_id=session,
        task_lease_ref="TASKLEASE-" + item, state=WorkItemAttemptState.RUNNING))
    return pool.acquire(
        mission_id="M-1", workitem_id=item, attempt_id=attempt,
        worker_id=worker, access_mode=BrowserAccessMode.WRITE,
        purpose=purpose, ttl_seconds=300)


def _bsk_field_adapter(truth, pool, tmp_path):
    runner = TestBSK()

    def owned(ctx, browser):
        return {
            "bsk_session_id": "BSK-OWNED-" + ctx["attempt_id"],
            "tab_id": 37, "state": "ACTIVE",
            "source_receipt_ref": "r1://B-SESSION-" + ctx["attempt_id"],
            "browser_instance_id": browser["browser_instance_id"],
            "profile_dir": browser["profile_dir"],
            "bsk_endpoint": browser["bsk_endpoint"],
            "auth_asset_ref": browser["auth_asset_ref"],
            "browser_lease_id": ctx["browser_lease_id"],
            "mission_id": ctx["mission_id"],
            "workitem_id": ctx["workitem_id"],
            "attempt_id": ctx["attempt_id"], "worker_id": ctx["worker_id"],
            "dsh_session_id": ctx["session_id"],
        }

    def resolve(ref, kind, ctx):
        if kind == "oracle" and ref == "oracle://save-confirmed":
            return {"type": "text_equals", "element_ref": "css:#toast",
                    "expected": "Saved"}
        return None

    def signer(scope):
        now = int(time.time())
        instance_id = pool.lease(scope["browser_lease_id"])["browser_instance_id"]
        instance = truth.query(
            "rc72_browser_instance", browser_instance_id=instance_id)[0]
        session = owned(scope, instance)
        return {
            "verifier_kind": "SIMULATED_B_SIGNER_NOT_FIELD",
            "attestation_kind": "BANK_BSK_FIELD_SESSION",
            "signature_verified": True, "field_verified": True,
            "attestation_ref": "test://mock-B-proof",
            "evidence_refs": ["evidence://mock-B-session"],
            "issued_at": now - 1, "expires_at": now + 300,
            "scope_digest": bsk_field_scope_digest(scope),
            "bsk_session_id": session["bsk_session_id"],
            "tab_id": session["tab_id"],
            "browser_instance_id": instance_id,
            "auth_asset_ref": instance["auth_asset_ref"],
            "browser_lease_id": scope["browser_lease_id"],
            "attempt_id": scope["attempt_id"],
            "case_id": scope["case_id"],
        }

    adapter = JourneyBSKCertifiedFieldAdapter(
        browser_pool=pool, evidence_root=tmp_path / "all-bsk-receipts",
        bsk_executable=tmp_path / "bsk.exe", runner=runner,
        session_resolver=owned, reference_resolver=resolve,
        field_attestation_verifier=signer,
        trusted_verifier_kinds=("SIMULATED_B_SIGNER_NOT_FIELD",))
    return adapter, runner


def test_bsk_candidate_two_independent_field_contracts_human_and_official(tmp_path):
    truth, importer, doc, exported, args, mapping = _fixture(tmp_path)
    _invoke(importer, exported, args, mapping, assertions=[
        {"source_operation_id": "operation-2",
         "locator_ref": "css:#toast",
         "oracle_ref": "oracle://save-confirmed"}])
    JourneyCompiler(truth, release_id="RC7.2").compile(
        candidate_id="JC-ALL", recording_id="JR-BSK-1")
    pool = importer.teaching.browser_pool
    original_lease_id = args["browser_lease_id"]
    pool.release(original_lease_id, reason="teaching completed")
    for index in (1, 2):
        item = "WI-BSK-R-%d" % index
        attempt = "ATT-BSK-R-%d" % index
        worker = "WORKER-BSK-R-%d" % index
        session = "SESSION-BSK-R-%d" % index
        lease = _start_attempt(
            truth, pool, item=item, attempt=attempt,
            worker=worker, session=session,
            artifact="JC-ALL", purpose="JOURNEY_REPLAY")
        adapter, runner = _bsk_field_adapter(truth, pool, tmp_path)
        replay = JourneyReplayService(
            truth, release_id="RC7.2", browser_pool=pool, adapter=adapter,
            trusted_field_adapter_kinds=("BROWSERSKILL_FIELD_ATTESTED",))
        result = replay.replay(
            replay_id="JRP-BSK-%d" % index, candidate_id="JC-ALL",
            workitem_id=item, attempt_id=attempt, worker_id=worker,
            session_id=session, browser_lease_id=lease.browser_lease_id)
        assert result.state.value == "PASSED"
        assert truth.query(
            "rc72_journey_replay", replay_id="JRP-BSK-%d" % index)[0]["field_verified"]
        assert any("step" in cmd for cmd in runner.calls)
        adapter.close()
        pool.release(lease.browser_lease_id, reason="separate benchmark Attempt")

    benchmark = JourneyBenchmarkService(
        truth, release_id="RC7.2").evaluate(
        benchmark_id="JB-ALL", candidate_id="JC-ALL",
        replay_ids=["JRP-BSK-1", "JRP-BSK-2"],
        policy=JourneyBenchmarkPolicy(
            min_replays=2, min_field_verified_replays=2))
    assert benchmark.state.value == "PASSED"
    assert truth.query("rc72_journey_benchmark", benchmark_id="JB-ALL")[0][
        "field_benchmark_verified"] is True

    promotion = JourneyPromotionService(
        truth, release_id="RC7.2",
        approval_verifier=FakeBankHumanVerifier(truth),
        trusted_field_verifier_kinds=("SIMULATED_HUMAN_BANK_GATE_NOT_FIELD",))
    official = promotion.review_and_promote(
        review_id="REV-ALL", official_asset_id="OJ-BSK-ALL",
        candidate_id="JC-ALL", benchmark_id="JB-ALL",
        attestation_ref="test://simulated-human-signature")
    assert official.official_asset_id == "OJ-BSK-ALL"
    asset = truth.query(
        "rc72_official_journey_asset", official_asset_id="OJ-BSK-ALL")[0]
    assert asset["official"] is True and asset["executable"] is True
    assert asset["case_id"] == "TC-1"
    assert asset["field_benchmark_verified"] is True

    item = "WI-OJ-BSK"
    attempt = "ATT-OJ-BSK"
    worker = "WORKER-OJ-BSK"
    session = "SESSION-OJ-BSK"
    lease = _start_attempt(
        truth, pool, item=item, attempt=attempt,
        worker=worker, session=session,
        artifact="OJ-BSK-ALL", purpose="OFFICIAL_JOURNEY_EXECUTION")
    adapter, runner = _bsk_field_adapter(truth, pool, tmp_path)
    service = OfficialJourneyExecutionService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter,
        trusted_field_adapter_kinds=("BROWSERSKILL_FIELD_ATTESTED",))
    result = service.execute(
        execution_id="OJ-BSK-EXEC", official_asset_id="OJ-BSK-ALL",
        workitem_id=item, attempt_id=attempt,
        worker_id=worker, session_id=session,
        browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "PASSED"
    execution = truth.query(
        "rc72_official_journey_execution", execution_id="OJ-BSK-EXEC")[0]
    assert execution["field_verified"] is True
    assert len(truth.query(
        "rc72_official_journey_execution_step", execution_id="OJ-BSK-EXEC")) == 3
    assert any("step" in cmd for cmd in runner.calls)
