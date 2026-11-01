from __future__ import annotations

import pytest

from rc8_node.single_node_integration_proof import SingleNodeDurableIntegrationProofRunner


class _Dispatcher:
    supported_stages = ("SCOPE_INTAKE",)

    def run_once(self, *, test_run_id):
        raise AssertionError("dispatcher must not claim work when production preflight is dirty")


class _Truth:
    def __init__(self, *, dirty_attempts=False, dirty_r1=False):
        self.dirty_attempts = dirty_attempts
        self.dirty_r1 = dirty_r1
        self.calls = []

    def assert_no_attempts_for_test_run(self, test_run_id):
        self.calls.append(("attempts", test_run_id))
        if self.dirty_attempts:
            raise RuntimeError("FULL_LOOP_PREEXISTING_ATTEMPT_TRUTH")

    def assert_no_r1_attempt_lifecycle_for_test_run(self, test_run_id):
        self.calls.append(("r1", test_run_id))
        if self.dirty_r1:
            raise RuntimeError("FULL_LOOP_PREEXISTING_R1_ATTEMPT_LIFECYCLE")

    def get_work_item(self, work_item_id):
        return None

    def get_attempt(self, attempt_id):
        return None

    def get_artifact(self, artifact_id):
        return None

    def find_r1_attempt_completed(self, **kwargs):
        return None


def _runner(truth):
    runner = SingleNodeDurableIntegrationProofRunner(
        dispatcher=_Dispatcher(),
        truth_reader=truth,
        required_stages=("SCOPE_INTAKE",),
        require_production_components=False,
    )
    # Unit-test the downstream production preflight ordering without weakening
    # the constructor-established, read-only production identity contract.
    runner._production_components_verified = True
    runner.observer.run = lambda **_: (_ for _ in ()).throw(
        AssertionError("observer must not run before both production preflights pass")
    )
    return runner


def test_invalid_test_run_identity_fails_before_any_durable_truth_access_or_claim():
    truth = _Truth()
    with pytest.raises(RuntimeError, match="FULL_LOOP_TEST_RUN_ID_REQUIRED"):
        _runner(truth).run(test_run_id="   ")
    assert truth.calls == []


def test_preexisting_attempt_truth_fails_before_r1_preflight_and_before_claim():
    truth = _Truth(dirty_attempts=True)
    with pytest.raises(RuntimeError, match="FULL_LOOP_PREEXISTING_ATTEMPT_TRUTH"):
        _runner(truth).run(test_run_id="run-dirty-attempt")
    assert truth.calls == [("attempts", "run-dirty-attempt")]


def test_preexisting_r1_lifecycle_fails_before_first_claim():
    truth = _Truth(dirty_r1=True)
    with pytest.raises(RuntimeError, match="FULL_LOOP_PREEXISTING_R1_ATTEMPT_LIFECYCLE"):
        _runner(truth).run(test_run_id="run-dirty-r1")
    assert truth.calls == [
        ("attempts", "run-dirty-r1"),
        ("r1", "run-dirty-r1"),
    ]
