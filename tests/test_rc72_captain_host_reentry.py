"""Real R1 Captain reentry/host signing contract; no mocked bank/DSH PASS."""
from dataclasses import replace
import time

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_captain_dispatch_fencing import CaptainDispatchFencer
from rc7_runtime.rc72_mission_factory import create_mission_driver
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_release.rc72_captain_host_reentry import (
    ObservedDshCaptain, reenter_host_captain,
)
from rc72_n2_test_support import build_truth, start_n1, COMMIT, RELEASE, MISSION, BATCH
from test_rc72_mission_factory import _setup


def _fixture(tmp_path):
    truth = build_truth(tmp_path)
    start_n1(truth)
    host_key = RC72AuthorityRuntime(b"test-isolated-live-host-captain-observer")
    lease = CaptainDispatchFencer(truth, release_id=RELEASE).acquire_initial(
        mission_id=MISSION, team_id="REAL-HOST-TEAM",
        captain_session_id="DSH-AGENTTEAMS-CAPTAIN-A", ttl_seconds=300)
    return truth, host_key, lease


def _signed(host_key, lease, *, release_batch_id=BATCH, **changes):
    values = dict(
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=release_batch_id,
        mission_id=MISSION, team_id=lease["team_id"],
        captain_session_id=lease["captain_session_id"],
        captain_lease_id=lease["lease_id"],
        captain_generation=lease["generation"],
        dsh_session_ref="dsh://agent-teams/observed-captain-session",
        observed_at=int(time.time()), state="ACTIVE", signature="pending",
    )
    values.update(changes)
    unsigned = ObservedDshCaptain(**values)
    return replace(unsigned, signature=host_key._sign(unsigned.signed_fields()))


def _reenter(truth, key, ticket, **kwargs):
    params = dict(
        release_id=RELEASE, source_commit=COMMIT, release_batch_id=BATCH,
        observed=ticket, host_authority=key,
        role_profiles={"L3_EXECUTE": ("api_http",),
                       "N9_QUALIFY": ("defect_analysis",)},
        approved_capabilities=("api_http", "defect_analysis"))
    params.update(kwargs)
    return reenter_host_captain(truth, **params)


def test_cold_verified_host_reenters_actual_product_factory_without_r1_or_dsh_effect(tmp_path):
    truth, key, lease = _fixture(tmp_path)
    old = truth.store.path.read_bytes()
    ticket = _signed(key, lease)
    cold = TruthRuntime(truth.store.path)
    binding = _reenter(cold, key, ticket)
    assert binding.captain_lease_id == lease["lease_id"]
    assert binding.captain_session_id == lease["captain_session_id"]
    assert binding.scheduler.fencer.assert_owner(
        mission_id=MISSION, lease_id=lease["lease_id"],
        captain_session_id=lease["captain_session_id"])["generation"] == 1
    _, options = _setup(tmp_path, cold)
    options["captain_binding"] = binding
    driver = create_mission_driver(cold, **options)
    assert driver.n7_pipeline.captain_scheduler is binding.scheduler
    assert driver.n7_pipeline.captain_session_id == ticket.captain_session_id
    assert driver._assert_captain_product_entry(MISSION) is None
    assert truth.store.path.read_bytes() == old
    assert cold.query("rc72_captain_etu_admission") == []
    assert cold.query("execution_attempt") == []


@pytest.mark.parametrize("mutation,reason", [
    ("unsigned_dict", "SIGNED_OBSERVATION_REQUIRED"),
    ("foreign_signer", "OBSERVATION_SIGNATURE_INVALID"),
    ("wrong_signature", "OBSERVATION_SIGNATURE_INVALID"),
    ("other_lease", "ACTIVE_CAPTAIN_GENERATION_REQUIRED"),
    ("other_session", "ACTIVE_CAPTAIN_GENERATION_REQUIRED"),
    ("other_team", "ACTIVE_CAPTAIN_GENERATION_REQUIRED"),
    ("other_generation", "ACTIVE_CAPTAIN_GENERATION_REQUIRED"),
    ("wrong_batch", "BATCH_MISSION_SCOPE_MISMATCH"),
    ("wrong_source", "OBSERVED_SESSION_SCOPE_CHANGED"),
    ("inactive", "OBSERVED_SESSION_SCOPE_CHANGED"),
    ("stale_observation", "SESSION_OBSERVATION_STALE"),
    ("future_observation", "SESSION_OBSERVATION_STALE"),
    ("profile_escalation", "ROLE_OUTSIDE_APPROVED_CAPABILITIES"),
    ("all_access", "FULL_ACCESS_FORBIDDEN"),
])
def test_host_reentry_rejects_wrong_signed_identity_and_unapproved_role(
        tmp_path, mutation, reason):
    truth, key, lease = _fixture(tmp_path)
    ticket = _signed(key, lease)
    other_key = key
    params = {}
    if mutation == "unsigned_dict":
        ticket = {"session_id": ticket.captain_session_id}
    elif mutation == "foreign_signer":
        other_key = RC72AuthorityRuntime(b"unrelated-untrusted-host-authority")
    elif mutation == "wrong_signature":
        ticket = replace(ticket, signature="invalid")
    elif mutation == "other_lease":
        ticket = _signed(key, lease, captain_lease_id="CAPF-OTHER")
    elif mutation == "other_session":
        ticket = _signed(key, lease, captain_session_id="DSH-OTHER")
    elif mutation == "other_team":
        ticket = _signed(key, lease, team_id="TEAM-OTHER")
    elif mutation == "other_generation":
        ticket = _signed(key, lease, captain_generation=2)
    elif mutation == "wrong_batch":
        ticket = _signed(key, lease, release_batch_id="RB-OTHER")
        params["release_batch_id"] = "RB-OTHER"
    elif mutation == "wrong_source":
        ticket = _signed(key, lease, source_commit="f"*40)
    elif mutation == "inactive":
        ticket = _signed(key, lease, state="IDLE")
    elif mutation == "stale_observation":
        ticket = _signed(key, lease, observed_at=int(time.time())-100)
    elif mutation == "future_observation":
        ticket = _signed(key, lease, observed_at=int(time.time())+100)
    elif mutation == "profile_escalation":
        params["role_profiles"] = {"L3_EXECUTE": ("production_db_write",)}
    elif mutation == "all_access":
        params["approved_capabilities"] = ("full_access",)
        params["role_profiles"] = {"L3_EXECUTE": ("full_access",)}
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="C07_HOST_" + reason
                       if mutation != "all_access" else "CAPTAIN_SCHEDULER_FULL_ACCESS_FORBIDDEN"):
        _reenter(truth, other_key, ticket, **params)
    assert truth.store.path.read_bytes() == before
    assert not truth.query("rc72_captain_etu_admission")


def test_quiesced_old_captain_cannot_reenter_but_signed_new_generation_can(tmp_path):
    truth, key, old_lease = _fixture(tmp_path)
    fencer = CaptainDispatchFencer(truth, release_id=RELEASE)
    lifecycle = WorkerLifecycleService(truth, release_id=RELEASE)
    checkpoint = fencer.prepare_handoff(
        mission_id=MISSION, team_id=old_lease["team_id"],
        lease_id=old_lease["lease_id"],
        captain_session_id=old_lease["captain_session_id"],
        lifecycle=lifecycle, current_node_refs=["N1_REALITY"],
        latest_delivery_refs=[], latest_gate_refs=[],
        next_workitem_ids=[])
    old_ticket = _signed(key, old_lease)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="C07_HOST_ACTIVE_CAPTAIN_GENERATION_REQUIRED"):
        _reenter(truth, key, old_ticket)
    assert truth.store.path.read_bytes() == before
    successor = fencer.takeover(
        mission_id=MISSION, team_id=old_lease["team_id"],
        checkpoint_id=checkpoint.checkpoint_id,
        new_captain_session_id="DSH-AGENTTEAMS-CAPTAIN-B",
        lifecycle=lifecycle)
    resumed = TruthRuntime(truth.store.path)
    ticket = _signed(key, successor)
    before = truth.store.path.read_bytes()
    binding = _reenter(resumed, key, ticket)
    assert binding.captain_session_id == "DSH-AGENTTEAMS-CAPTAIN-B"
    assert binding.scheduler.fencer.assert_owner(
        mission_id=MISSION, lease_id=successor["lease_id"],
        captain_session_id=successor["captain_session_id"])["generation"] == 2
    with pytest.raises(ContractError, match="C07_HOST_ACTIVE_CAPTAIN_GENERATION_REQUIRED"):
        _reenter(resumed, key, old_ticket)
    assert truth.store.path.read_bytes() == before


def test_expired_lease_does_not_mark_expired_until_authoritative_dispatch(tmp_path, monkeypatch):
    truth, key, lease = _fixture(tmp_path)
    ticket = _signed(key, lease, observed_at=lease["expires_at"])
    monkeypatch.setattr("rc7_release.rc72_captain_host_reentry._now",
                        lambda: lease["expires_at"])
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="C07_HOST_ACTIVE_CAPTAIN_GENERATION_REQUIRED"):
        _reenter(truth, key, ticket)
    # Read-only binding is safe before Field Q7 and soft token admission.
    assert truth.store.path.read_bytes() == before
    assert truth.query("rc72_captain_dispatch_lease", lease_id=lease["lease_id"])[0]["state"] == "ACTIVE"
