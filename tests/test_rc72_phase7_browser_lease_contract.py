from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_browser_resources import (
    BrowserAccessMode,
    BrowserPool,
    BrowserResourceConflict,
)
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


def _persist_attempt(repo, truth, *, suffix, worker_id, session_id, role, etu_id):
    workitem_id = "WI-%s" % suffix
    attempt_id = "ATT-%s" % suffix
    repo.persist(
        ExecutionTaskUnit(
            etu_id=etu_id,
            mission_id="M-1",
            release_batch_id="RB-1",
            obligation_id="TO-1",
            case_ids=["TC-%s" % suffix],
            primary_goal="browser work %s" % suffix,
            primary_code_slice="Journey#%s" % suffix,
            test_level="L4" if role != "AUTH_KEEPER" else "L5",
            primary_oracle="UI+network",
            data_domain="browser",
            primary_tool_family="browser",
            planning_snapshot_ref="PLAN-1",
            cohesion_score=1.0,
            cohesion_explanation="isolated browser context",
            required_capabilities=["browser:write"],
            estimated_duration_minutes=5,
            estimated_cost=1.0,
        )
    )
    append_entity(
        truth,
        Task(
            task_id=workitem_id,
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="BROWSER_%s" % role,
            objective="browser work %s" % suffix,
            required_capabilities=["browser:write"],
            input_artifact_refs=[etu_id],
            acceptance_criteria=["browser evidence persisted"],
        ),
        release_id="RC7.2",
    )
    repo.persist(
        WorkItemAttemptBinding(
            binding_id="BIND-%s" % suffix,
            mission_id="M-1",
            etu_id=etu_id,
            workitem_id=workitem_id,
            case_id="TC-%s" % suffix,
            attempt_id=attempt_id,
            worker_id=worker_id,
            session_id=session_id,
            task_lease_ref="TASKLEASE-%s" % suffix,
            state=WorkItemAttemptState.RUNNING,
        )
    )
    return workitem_id, attempt_id


def _setup(tmp_path: Path, instance_count=2):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-admin"],
            requirement_ids=["REQ-1"],
        )
    )
    repo.persist(
        TestObligation(
            obligation_id="TO-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_id="REQ-1",
            sst_id="SST-1",
            application_id="cfg-admin",
            business_scenario="4A authenticated journey",
            business_rule="authenticated user can complete journey",
            risk_level="HIGH",
            test_level="L4",
            code_slice_refs=["ui://journey"],
            oracle_refs=["UI", "NETWORK"],
        )
    )
    l4_wi, l4_att = _persist_attempt(
        repo, truth, suffix="L4", worker_id="WORKER-L4", session_id="SESSION-L4", role="L4", etu_id="ETU-L4"
    )
    auth_wi, auth_att = _persist_attempt(
        repo, truth, suffix="AUTH", worker_id="WORKER-AUTH", session_id="SESSION-AUTH", role="AUTH_KEEPER", etu_id="ETU-AUTH"
    )
    l5_wi, l5_att = _persist_attempt(
        repo, truth, suffix="L5", worker_id="WORKER-L5", session_id="SESSION-L5", role="L5", etu_id="ETU-L5"
    )
    pool = BrowserPool(truth, release_id="RC7.2")
    for index in range(instance_count):
        pool.register_instance(
            browser_instance_id="BROWSER-%d" % (index + 1),
            profile_dir="profiles/browser-%d" % (index + 1),
            cdp_endpoint="http://127.0.0.1:%d" % (9222 + index),
            bsk_endpoint="http://127.0.0.1:%d" % (4096 + index),
            auth_asset_ref="auth://shared-4a" if index < 2 else None,
        )
    return truth, pool, {
        "L4": (l4_wi, l4_att, "WORKER-L4"),
        "AUTH": (auth_wi, auth_att, "WORKER-AUTH"),
        "L5": (l5_wi, l5_att, "WORKER-L5"),
    }


def _acquire(pool, ids, *, purpose, access_mode=BrowserAccessMode.WRITE):
    wi, att, worker = ids
    return pool.acquire(
        mission_id="M-1",
        workitem_id=wi,
        attempt_id=att,
        worker_id=worker,
        access_mode=access_mode,
        purpose=purpose,
        ttl_seconds=300,
    )


def test_authkeeper_and_l4_receive_distinct_write_browser_instances(tmp_path: Path):
    truth, pool, ids = _setup(tmp_path, instance_count=2)
    auth = _acquire(pool, ids["AUTH"], purpose="AUTH_KEEPER")
    l4 = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")

    assert auth.browser_instance_id != l4.browser_instance_id
    auth_inst = truth.query("rc72_browser_instance", browser_instance_id=auth.browser_instance_id)[0]
    l4_inst = truth.query("rc72_browser_instance", browser_instance_id=l4.browser_instance_id)[0]
    assert auth_inst["profile_dir"] != l4_inst["profile_dir"]
    assert auth_inst["cdp_endpoint"] != l4_inst["cdp_endpoint"]
    assert auth_inst["bsk_endpoint"] != l4_inst["bsk_endpoint"]
    # Auth asset may be shared; browser control is not.
    assert auth_inst["auth_asset_ref"] == l4_inst["auth_asset_ref"] == "auth://shared-4a"


def test_one_browser_instance_has_only_one_active_write_owner(tmp_path: Path):
    _, pool, ids = _setup(tmp_path, instance_count=1)
    first = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")
    with pytest.raises(BrowserResourceConflict, match="RESOURCE_CONFLICT"):
        _acquire(pool, ids["L5"], purpose="L5_EXECUTION")
    assert first.browser_instance_id == "BROWSER-1"


def test_conflict_does_not_reassign_or_mutate_existing_write_lease(tmp_path: Path):
    truth, pool, ids = _setup(tmp_path, instance_count=1)
    first = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")
    with pytest.raises(BrowserResourceConflict):
        _acquire(pool, ids["AUTH"], purpose="AUTH_KEEPER")
    row = truth.query("rc72_browser_lease", browser_lease_id=first.browser_lease_id)[0]
    assert row["worker_id"] == "WORKER-L4"
    assert row["state"] == "ACTIVE"
    assert row["access_mode"] == "WRITE"


def test_captain_direct_browser_control_is_forbidden(tmp_path: Path):
    _, pool, _ = _setup(tmp_path, instance_count=1)
    with pytest.raises(Exception, match="CAPTAIN_BROWSER_CONTROL_FORBIDDEN"):
        pool.acquire(
            mission_id="M-1",
            workitem_id="WI-CAPTAIN",
            attempt_id="ATT-CAPTAIN",
            worker_id="CAPTAIN",
            access_mode=BrowserAccessMode.WRITE,
            purpose="CAPTAIN",
            ttl_seconds=300,
        )


def test_lease_is_bound_to_canonical_attempt_and_worker(tmp_path: Path):
    _, pool, ids = _setup(tmp_path, instance_count=1)
    lease = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")
    assert pool.assert_usable(
        browser_lease_id=lease.browser_lease_id,
        mission_id="M-1",
        workitem_id="WI-L4",
        attempt_id="ATT-L4",
        worker_id="WORKER-L4",
        access_mode=BrowserAccessMode.WRITE,
    )["state"] == "ACTIVE"
    with pytest.raises(Exception, match="BROWSER_LEASE_ATTEMPT_MISMATCH"):
        pool.assert_usable(
            browser_lease_id=lease.browser_lease_id,
            mission_id="M-1",
            workitem_id="WI-L4",
            attempt_id="ATT-OTHER",
            worker_id="WORKER-L4",
            access_mode=BrowserAccessMode.WRITE,
        )
    with pytest.raises(Exception, match="BROWSER_LEASE_WORKER_MISMATCH"):
        pool.assert_usable(
            browser_lease_id=lease.browser_lease_id,
            mission_id="M-1",
            workitem_id="WI-L4",
            attempt_id="ATT-L4",
            worker_id="WORKER-L5",
            access_mode=BrowserAccessMode.WRITE,
        )


def test_release_makes_instance_reusable_but_never_transfers_same_lease(tmp_path: Path):
    truth, pool, ids = _setup(tmp_path, instance_count=1)
    old = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")
    pool.release(old.browser_lease_id, reason="ETU complete")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        pool.assert_usable(
            browser_lease_id=old.browser_lease_id,
            mission_id="M-1",
            workitem_id="WI-L4",
            attempt_id="ATT-L4",
            worker_id="WORKER-L4",
            access_mode=BrowserAccessMode.WRITE,
        )
    new = _acquire(pool, ids["L5"], purpose="L5_EXECUTION")
    assert new.browser_instance_id == old.browser_instance_id
    assert new.browser_lease_id != old.browser_lease_id
    assert truth.query("rc72_browser_lease", browser_lease_id=old.browser_lease_id)[0]["state"] == "RELEASED"


def test_expired_write_lease_no_longer_authorizes_and_instance_can_be_reclaimed(tmp_path: Path):
    _, pool, ids = _setup(tmp_path, instance_count=1)
    old = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")
    row = pool.lease(old.browser_lease_id)
    with pytest.raises(Exception, match="BROWSER_LEASE_EXPIRED"):
        pool.assert_usable(
            browser_lease_id=old.browser_lease_id,
            mission_id="M-1",
            workitem_id="WI-L4",
            attempt_id="ATT-L4",
            worker_id="WORKER-L4",
            access_mode=BrowserAccessMode.WRITE,
            now=row["expires_at"] + 1,
        )
    reclaimed = pool.acquire(
        mission_id="M-1",
        workitem_id="WI-L5",
        attempt_id="ATT-L5",
        worker_id="WORKER-L5",
        access_mode=BrowserAccessMode.WRITE,
        purpose="L5_EXECUTION",
        ttl_seconds=300,
        now=row["expires_at"] + 1,
    )
    assert reclaimed.browser_instance_id == old.browser_instance_id


def test_registration_rejects_duplicate_profile_cdp_or_bsk_identity(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    pool = BrowserPool(truth, release_id="RC7.2")
    pool.register_instance(
        browser_instance_id="BROWSER-1",
        profile_dir="profiles/1",
        cdp_endpoint="http://127.0.0.1:9222",
        bsk_endpoint="http://127.0.0.1:4096",
    )
    for kwargs in (
        dict(browser_instance_id="BROWSER-2", profile_dir="profiles/1", cdp_endpoint="http://127.0.0.1:9223", bsk_endpoint="http://127.0.0.1:4097"),
        dict(browser_instance_id="BROWSER-3", profile_dir="profiles/3", cdp_endpoint="http://127.0.0.1:9222", bsk_endpoint="http://127.0.0.1:4098"),
        dict(browser_instance_id="BROWSER-4", profile_dir="profiles/4", cdp_endpoint="http://127.0.0.1:9224", bsk_endpoint="http://127.0.0.1:4096"),
    ):
        with pytest.raises(Exception, match="BROWSER_INSTANCE_RESOURCE_IDENTITY_CONFLICT"):
            pool.register_instance(**kwargs)


def test_browser_instance_and_lease_truth_survive_r1_replay(tmp_path: Path):
    truth, pool, ids = _setup(tmp_path, instance_count=2)
    lease = _acquire(pool, ids["L4"], purpose="L4_EXECUTION")
    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    instance = replayed.query("rc72_browser_instance", browser_instance_id=lease.browser_instance_id)[0]
    persisted = replayed.query("rc72_browser_lease", browser_lease_id=lease.browser_lease_id)[0]
    assert instance["profile_dir"].startswith("profiles/")
    assert persisted["mission_id"] == "M-1"
    assert persisted["workitem_id"] == "WI-L4"
    assert persisted["attempt_id"] == "ATT-L4"
    assert persisted["worker_id"] == "WORKER-L4"
    assert persisted["access_mode"] == "WRITE"
