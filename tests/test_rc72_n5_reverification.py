from pathlib import Path

import pytest
from test_rc72_n5_data_verification_finalization import _anchored, _service
from test_rc72_n5_data_resolution import _evidence
from rc72_n2_test_support import BATCH
from rc7_runtime.rc72_n5_data_verification_finalization import N5DataVerificationFinalizationError


def _old_binding(truth, receipt, root):
    from test_rc72_n5_data_verification_handoff import _v2_candidate
    from rc7_runtime.rc72_n5_data_verification_finalization import N5DataVerificationFinalizationService
    from rc72_n2_test_support import RELEASE, MISSION, COMMIT
    service = N5DataVerificationFinalizationService(truth, release_id=RELEASE, mission_id=MISSION,
                                                 source_commit=COMMIT, state_root=str(root))
    candidate = _v2_candidate(truth, receipt)
    ref = service._canonical_data_ref(candidate['candidate_ref'])
    service._ensure_resource(data_ref=ref, candidate=candidate)
    _evidence(truth, 'OLD-DATA-PROOF', [receipt['data_requirement_id']])
    service.resolution.bind_verified(data_requirement_id=receipt['data_requirement_id'], data_ref=ref,
        strategy=candidate['strategy'], source_or_constructor=candidate['source_or_constructor'],
        verification='previous accepted observation', verification_evidence_refs=['OLD-DATA-PROOF'],
        precondition_refs=candidate['precondition_refs'], validity_window=candidate['validity_window'],
        cleanup_policy=candidate['cleanup_policy'])


def _prepared(tmp_path, monkeypatch, **kwargs):
    import test_rc72_n5_data_verification_anchor as fixture
    original = fixture._prepare_promoted
    def prepare(*args, **kwargs):
        truth, receipt, promoted = original(*args, **kwargs)
        _old_binding(truth, receipt, tmp_path)
        return truth, receipt, promoted
    monkeypatch.setattr(fixture, '_prepare_promoted', prepare)
    # The normal verify entry still rejects existing bindings. Reverification
    # explicitly names the binding revision and receives a distinct Attempt.
    original_service = fixture._service
    def service(*args, **kwargs):
        verifier = original_service(*args, **kwargs)
        verifier.verify = lambda **params: verifier.reverify(**params, binding_revision=1)
        return verifier
    monkeypatch.setattr(fixture, '_service', service)
    return _anchored(tmp_path, monkeypatch, **kwargs)


def test_native_fresh_verifier_revises_same_ref_without_rewriting_previous_evidence(tmp_path, monkeypatch):
    truth, receipt, _, verifier, _, _, anchor = _prepared(tmp_path, monkeypatch)
    service = _service(truth, verifier)
    old = truth.query('rc72_n5_data_binding')[0]
    result = service.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    current = truth.query('rc72_n5_data_binding')[0]
    assert result['status'] == 'FINALIZED_VERIFIED'
    assert current['binding_id'] == old['binding_id'] and current['data_ref'] == old['data_ref']
    assert current['artifact_version'] == 2
    assert current['verification_history'][0]['verification_evidence_refs'] == ['OLD-DATA-PROOF']
    assert current['reverification_anchor_id'] == anchor['anchor_id']
    before = list(truth.store.iter_raw())
    assert service.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])['status'] == 'RESUMED'
    assert list(truth.store.iter_raw()) == before
    assert truth.query('rc72_data_lease') == []


def test_old_verification_cannot_be_promoted_to_a_new_observation(tmp_path, monkeypatch):
    truth, receipt, _, verifier, _, _, _ = _anchored(tmp_path, monkeypatch)
    service = _service(truth, verifier)
    service.finalize(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    with pytest.raises(N5DataVerificationFinalizationError, match='FRESH_ANCHOR_REQUIRED'):
        service.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    assert truth.query('rc72_n5_data_binding')[0]['artifact_version'] == 1


def test_reverification_rechecks_raw_hash_before_binding_revision(tmp_path, monkeypatch):
    truth, receipt, _, verifier, _, _, anchor = _prepared(tmp_path, monkeypatch)
    Path(anchor['raw_output_ref'][len('file://'):]).write_bytes(b'changed proof')
    before = list(truth.store.iter_raw())
    with pytest.raises(N5DataVerificationFinalizationError):
        _service(truth, verifier).reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    assert list(truth.store.iter_raw()) == before


def _accept_initial_and_reopen(truth, receipt, resolver):
    from test_rc72_n5_data_discovery_dispatch import _bind_requirement
    from test_rc72_n5_completion import _service as completion
    from rc7_runtime.rc72_state_machine import RC72StateMachine
    from rc7_runtime.rc72_domain import AutonomousMissionNode, MissionNodeState
    from rc72_n2_test_support import RELEASE, MISSION
    for req in truth.query('rc72_n5_data_requirement'):
        if req['data_requirement_id'] != receipt['data_requirement_id']:
            _bind_requirement(truth, resolver, req['data_requirement_id'], 'other-' + req['data_requirement_id'])
    first = completion(truth).complete(release_batch_id=BATCH)
    runtime = RC72StateMachine(truth, release_id=RELEASE)
    # Test boundary fixture: upstream repair has been authorized, downstream is
    # locked. Actual N8 -> repair suspension/cleanup remains a separate consumer.
    for kind, state in ((AutonomousMissionNode.N5_TEST_DATA, MissionNodeState.RUNNING),
                        (AutonomousMissionNode.N6_EXECUTABLE_READINESS, MissionNodeState.NOT_STARTED)):
        runtime._persist_node_state(runtime.node_by_type(MISSION, kind), state,
            reason='governed repair boundary fixture', bypass_direct_transition=True)
    return first


def test_proof_collected_before_previous_gate_cannot_certify_a_repair(tmp_path, monkeypatch):
    truth, receipt, _, verifier, _, _, _ = _prepared(tmp_path, monkeypatch)
    service = _service(truth, verifier)
    _accept_initial_and_reopen(truth, receipt, service.resolution)
    with pytest.raises(N5DataVerificationFinalizationError, match='NEW_OBSERVATION_REQUIRED'):
        service.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    assert truth.query('rc72_n5_data_binding', data_requirement_id=receipt['data_requirement_id'])[0]['artifact_version'] == 1


def test_native_reverification_creates_new_delivery_and_rejects_old_gate(tmp_path, monkeypatch):
    import test_rc72_n5_data_verification_anchor as fixture
    original = fixture._prepare_promoted
    old_delivery = []
    def prepare(*args, **kwargs):
        truth, receipt, promoted = original(*args, **kwargs)
        _old_binding(truth, receipt, tmp_path)
        from rc7_runtime.rc72_n5_data_resolution import N5DataResolutionService
        from rc72_n2_test_support import RELEASE, COMMIT
        resolver = N5DataResolutionService(truth, release_id=RELEASE, source_commit=COMMIT)
        old_delivery.append(_accept_initial_and_reopen(truth, receipt, resolver))
        return truth, receipt, promoted
    monkeypatch.setattr(fixture, '_prepare_promoted', prepare)
    original_service = fixture._service
    def service(*args, **kwargs):
        verifier = original_service(*args, **kwargs)
        verifier.verify = lambda **params: verifier.reverify(**params, binding_revision=1)
        return verifier
    monkeypatch.setattr(fixture, '_service', service)
    truth, receipt, _, verifier, _, _, anchor = _anchored(tmp_path, monkeypatch)
    result = _service(truth, verifier).reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'],
                                            verification_attempt_id=anchor['verification_attempt_id'])
    from test_rc72_n5_completion import _service as completion
    from rc7_runtime.rc72_n5_completion import N5CompletionError
    with pytest.raises(N5CompletionError, match='VERIFICATION_REVISION_STALE'):
        completion(truth).apply_gate(release_batch_id=BATCH)
    renewed = completion(truth).complete(release_batch_id=BATCH)
    assert renewed['gate']['decision'] == 'PASS'
    assert renewed['delivery']['delivery_id'] != old_delivery[0]['delivery']['delivery_id']
    assert len(truth.query('rc72_node_delivery', node_type='N5_TEST_DATA')) == 2
    assert truth.query('rc72_data_lease') == []


def test_failed_native_reverification_suspends_old_binding_and_keeps_n6_locked(tmp_path, monkeypatch):
    truth, receipt, _, verifier, _, _, anchor = _prepared(tmp_path, monkeypatch, repair=True)
    finalizer = _service(truth, verifier)
    result = finalizer.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    assert result['status'] == 'REPAIR_REQUIRED'
    from rc7_runtime.rc72_n5_data_resolution import N5DataResolutionError
    with pytest.raises(N5DataResolutionError, match='REVERIFICATION_REPAIR_REQUIRED'):
        finalizer.resolution.verified_binding(data_requirement_id=receipt['data_requirement_id'])
    current = truth.query('rc72_n5_data_binding')[0]
    assert current['verification_blocked_by_anchor'] == anchor['anchor_id']
    assert current['verification_evidence_refs'] == ['OLD-DATA-PROOF']
    assert truth.query('rc72_mission_node', node_type='N6_EXECUTABLE_READINESS')[0]['state'] == 'NOT_STARTED'
    before = list(truth.store.iter_raw())
    finalizer.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    assert list(truth.store.iter_raw()) == before


def test_failed_reverification_requires_another_fresh_verifier_before_reactivation(tmp_path, monkeypatch):
    truth, receipt, _, failed_verifier, _, _, failed_anchor = _prepared(tmp_path, monkeypatch, repair=True)
    finalizer = _service(truth, failed_verifier)
    finalizer.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    from test_rc72_n5_data_verification_handoff import _service as handoff
    fresh = handoff(tmp_path, truth, receipt, calls={'count': 20}, fixed_session='session-new-verifier-after-failed-recheck')
    observed = fresh.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'], binding_revision=2)
    assert observed['verification_attempt_id'] != failed_anchor['verification_attempt_id']
    finalizer = _service(truth, fresh)
    result = finalizer.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'],
                               verification_attempt_id=observed['verification_attempt_id'])
    assert result['status'] == 'FINALIZED_VERIFIED'
    binding = finalizer.resolution.verified_binding(data_requirement_id=receipt['data_requirement_id'])
    assert binding['artifact_version'] == 3 and 'verification_blocked_by_anchor' not in binding
    assert binding['verification_history'][0]['verification_evidence_refs'] == ['OLD-DATA-PROOF']
    from rc6_runtime.truth import TruthRuntime
    replay = TruthRuntime(truth.store.path)
    restored = _service(replay, fresh)
    before = list(replay.store.iter_raw())
    assert restored.reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'],
                            verification_attempt_id=observed['verification_attempt_id'])['status'] == 'RESUMED'
    assert list(replay.store.iter_raw()) == before


def test_verifier_started_before_gate_cannot_finish_later_and_claim_freshness(tmp_path, monkeypatch):
    import test_rc72_n5_data_verification_anchor as fixture
    original_prepare, original_service = fixture._prepare_promoted, fixture._service
    def prepare(*args, **kwargs):
        truth, receipt, promoted = original_prepare(*args, **kwargs)
        _old_binding(truth, receipt, tmp_path)
        return truth, receipt, promoted
    def service(path, truth, receipt, **kwargs):
        verifier = original_service(path, truth, receipt, **kwargs)
        run = verifier.launcher.command_runner
        def finish_after_gate(*args, **params):
            output = run(*args, **params)
            from rc7_runtime.rc72_n5_data_resolution import N5DataResolutionService
            from rc72_n2_test_support import RELEASE, COMMIT
            _accept_initial_and_reopen(truth, receipt, N5DataResolutionService(truth, release_id=RELEASE, source_commit=COMMIT))
            return output
        verifier.launcher.command_runner = finish_after_gate
        verifier.verify = lambda **params: verifier.reverify(**params, binding_revision=1)
        return verifier
    monkeypatch.setattr(fixture, '_prepare_promoted', prepare)
    monkeypatch.setattr(fixture, '_service', service)
    truth, receipt, _, verifier, _, _, _ = _anchored(tmp_path, monkeypatch)
    with pytest.raises(N5DataVerificationFinalizationError, match='NEW_OBSERVATION_REQUIRED'):
        _service(truth, verifier).reverify(release_batch_id=BATCH, data_requirement_id=receipt['data_requirement_id'])
    assert truth.query('rc72_n5_data_binding', data_requirement_id=receipt['data_requirement_id'])[0]['artifact_version'] == 1
