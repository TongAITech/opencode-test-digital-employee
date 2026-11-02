from types import SimpleNamespace

from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner


def test_production_bootstrap_runs_after_clean_preflight_before_first_observer_claim():
    events = []

    class Truth:
        def assert_no_attempts_for_test_run(self, test_run_id):
            events.append(("preflight-attempts", test_run_id))

        def assert_no_r1_attempt_lifecycle_for_test_run(self, test_run_id):
            events.append(("preflight-r1", test_run_id))

        def assert_attempt_ids_match_observed_leases(self, **kwargs):
            events.append(("bind-attempts", kwargs["test_run_id"]))

        def assert_worker_artifact_refs_match_observed_evidence(self, **kwargs):
            events.append(("bind-artifacts", kwargs["test_run_id"]))

        def assert_r1_attempt_lifecycle_matches_observed_leases(self, **kwargs):
            events.append(("bind-r1", kwargs["test_run_id"]))

    class Bootstrap:
        def materialize_initial_ready_work(self, *, test_run_id):
            events.append(("bootstrap", test_run_id))
            return SimpleNamespace(
                test_run_id=test_run_id,
                stage="SCOPE_INTAKE",
                work_item_id="wi-1",
                stage_instance_id="stage-1",
            )

    class Observer:
        def run(self, *, test_run_id):
            events.append(("observer", test_run_id))
            return SimpleNamespace(
                work_item_ids=("wi-1",),
                stage_instance_ids=("stage-1",),
                attempt_ids=("attempt-1",),
                lease_ids=("attempt-1",),
                evidence_refs=("artifact:art-1",),
            )

    class Verifier:
        def verify(self, observed):
            events.append(("verify", "run-1"))
            return SimpleNamespace(
                verified_work_items=observed.work_item_ids,
                verified_attempts=observed.attempt_ids,
                bank_reality_verified=False,
                release_status="HOLD",
            )

    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = True
    runner.expected_node_id = None
    runner.truth_reader = Truth()
    runner.production_bootstrap = Bootstrap()
    runner.observer = Observer()
    runner.verifier = Verifier()

    proof = runner.run(test_run_id="run-1")

    assert events[:4] == [
        ("preflight-attempts", "run-1"),
        ("preflight-r1", "run-1"),
        ("bootstrap", "run-1"),
        ("observer", "run-1"),
    ]
    assert proof.production_components_verified is True
    assert proof.production_causality_verified is False
    assert proof.bank_reality_verified is False
    assert proof.release_status == "HOLD"


def test_bootstrap_identity_mismatch_fails_before_observer_claim():
    events = []

    class Truth:
        def assert_no_attempts_for_test_run(self, test_run_id):
            events.append("preflight-attempts")

        def assert_no_r1_attempt_lifecycle_for_test_run(self, test_run_id):
            events.append("preflight-r1")

    class Bootstrap:
        def materialize_initial_ready_work(self, *, test_run_id):
            events.append("bootstrap")
            return SimpleNamespace(test_run_id="other-run", stage="SCOPE_INTAKE")

    class Observer:
        def run(self, *, test_run_id):
            events.append("observer")
            raise AssertionError("observer must not run")

    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = True
    runner.expected_node_id = None
    runner.truth_reader = Truth()
    runner.production_bootstrap = Bootstrap()
    runner.observer = Observer()
    runner.verifier = object()

    try:
        runner.run(test_run_id="run-1")
    except RuntimeError as exc:
        assert str(exc) == "FULL_LOOP_PRODUCTION_BOOTSTRAP_IDENTITY_MISMATCH"
    else:
        raise AssertionError("bootstrap identity mismatch must fail closed")

    assert events == ["preflight-attempts", "preflight-r1", "bootstrap"]


def test_bootstrap_work_item_must_be_the_first_center_claim():
    class Truth:
        def assert_no_attempts_for_test_run(self, test_run_id):
            return None

        def assert_no_r1_attempt_lifecycle_for_test_run(self, test_run_id):
            return None

    class Bootstrap:
        def materialize_initial_ready_work(self, *, test_run_id):
            return SimpleNamespace(
                test_run_id=test_run_id,
                stage="SCOPE_INTAKE",
                work_item_id="center-created-wi",
                stage_instance_id="center-created-stage",
            )

    class Observer:
        def run(self, *, test_run_id):
            return SimpleNamespace(
                work_item_ids=("other-wi",),
                stage_instance_ids=("center-created-stage",),
                attempt_ids=("attempt-1",),
                lease_ids=("attempt-1",),
                evidence_refs=("artifact:art-1",),
            )

    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = True
    runner.expected_node_id = None
    runner.truth_reader = Truth()
    runner.production_bootstrap = Bootstrap()
    runner.observer = Observer()
    runner.verifier = object()

    try:
        runner.run(test_run_id="run-1")
    except RuntimeError as exc:
        assert str(exc) == "FULL_LOOP_PRODUCTION_BOOTSTRAP_WORK_ITEM_NOT_FIRST_CLAIM"
    else:
        raise AssertionError("a different first claim must not satisfy production bootstrap causality")


def test_bootstrap_stage_instance_must_be_the_first_center_claim_stage():
    class Truth:
        def assert_no_attempts_for_test_run(self, test_run_id):
            return None

        def assert_no_r1_attempt_lifecycle_for_test_run(self, test_run_id):
            return None

    class Bootstrap:
        def materialize_initial_ready_work(self, *, test_run_id):
            return SimpleNamespace(
                test_run_id=test_run_id,
                stage="SCOPE_INTAKE",
                work_item_id="center-created-wi",
                stage_instance_id="center-created-stage",
            )

    class Observer:
        def run(self, *, test_run_id):
            return SimpleNamespace(
                work_item_ids=("center-created-wi",),
                stage_instance_ids=("other-stage",),
                attempt_ids=("attempt-1",),
                lease_ids=("attempt-1",),
                evidence_refs=("artifact:art-1",),
            )

    runner = SingleNodeDurableIntegrationProofRunner.__new__(SingleNodeDurableIntegrationProofRunner)
    runner._production_components_verified = True
    runner.expected_node_id = None
    runner.truth_reader = Truth()
    runner.production_bootstrap = Bootstrap()
    runner.observer = Observer()
    runner.verifier = object()

    try:
        runner.run(test_run_id="run-1")
    except RuntimeError as exc:
        assert str(exc) == "FULL_LOOP_PRODUCTION_BOOTSTRAP_STAGE_INSTANCE_NOT_FIRST_CLAIM"
    else:
        raise AssertionError("a different first Stage instance must not satisfy production bootstrap causality")
