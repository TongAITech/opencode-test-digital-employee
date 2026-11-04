"""C10 real CLI entry: admit Q7 before binding all native roles for dispatch."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import ClosedLoopControlPlane
from rc7_runtime.models import Mission
from rc7_runtime.rc72_mission_factory import MissionHostBindings, MissionWorkerBinding
from rc7_release import rc72_mission_cli
from rc7_release import rc72_mission_bindings
from rc7_runtime import rc72_mission_factory
from rc7_runtime.rc72_production_economy_ingress import _ROLE_NODE


class _Launcher(DshHeadlessWorkerLauncher):
    def __init__(self, truth, root, role):
        self.truth = truth
        self.release_id = "REL-C10"
        self.state_root = root / role
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.command_runner = lambda command, **kwargs: None

    def execute(self, assignment, prompt):
        raise AssertionError("CLI wiring test must not run the real provider")


def test_canonical_run_entry_binds_all_eleven_real_role_objects_before_factory(tmp_path, monkeypatch, capsys):
    ledger = tmp_path / "r1.jsonl"
    original = TruthRuntime(ledger)
    ClosedLoopControlPlane.bootstrap(
        original, Mission(
            mission_id="M-CLI-C10", release_id="REL-C10", goal="Mission first",
        )
    )
    package = tmp_path / "package"
    package.mkdir()
    source_commit = "a" * 40
    (package / "SOURCE_COMMIT").write_text(source_commit, encoding="utf-8")
    seen = {"factory": False}

    monkeypatch.setattr(
        rc72_mission_cli, "release_batch_status",
        lambda truth, **kwargs: {
            "release_id": "REL-C10", "mission_id": "M-CLI-C10",
            "release_batch_id": "B-C10", "nodes": [], "status": "HOLD",
        },
    )

    def host_bindings(*, truth, release_id, source_commit):
        assert release_id == "REL-C10"
        assert source_commit == "a" * 40
        workers = {
            role: MissionWorkerBinding(_Launcher(truth, tmp_path / "workers", role), ("native-source-read",))
            for role in _ROLE_NODE
        }
        seen["workers"] = workers
        return MissionHostBindings(
            workers=workers, bank_pip_mirror=None,
            execution_authority=None, execution_environment=None,
            tool_registry={},
        )

    monkeypatch.setattr(rc72_mission_bindings, "load_mission_bindings", lambda module, **kwargs: host_bindings(**kwargs))

    # The product must first compose the factory and pass the read-only Q7
    # admission.  This test explicitly substitutes an accepted Field gate;
    # it is not evidence that the real bank mirror was qualified.
    from rc7_runtime import rc72_field_mission_start

    class AcceptedFieldAdmission:
        def __init__(self, truth, *, source_commit, bank_pip_mirror):
            assert source_commit == "a" * 40
            assert bank_pip_mirror.root == package.resolve()
            self.truth = truth

        def _batch(self, release_batch_id):
            assert release_batch_id == "B-C10"
            return {"release_batch_id": release_batch_id}

        def _admission(self, batch):
            assert batch["release_batch_id"] == "B-C10"
            assert self.truth.query("rc72_token_budget", budget_id="M-CLI-C10") == []

    monkeypatch.setattr(rc72_field_mission_start, "ReleaseBatchFieldMissionLauncher", AcceptedFieldAdmission)

    def fake_factory(truth, *, workers, **kwargs):
        assert len(workers) == 11
        # Composition precedes Field admission; budget and wrappers must not
        # exist yet.  Both appear only after the accepted read-only admission.
        assert not any(
            getattr(binding.launcher, "_rc72_production_economy_bound", False)
            for binding in workers.values()
        )
        assert truth.query("rc72_token_budget", budget_id="M-CLI-C10") == []
        seen["factory"] = True
        return SimpleNamespace(
            bank_pip_mirror=SimpleNamespace(root=package.resolve()),
            run=lambda release_batch_id: {
                "status": "HOLD", "reason": "N10_NOT_COMPLETE",
                "release_batch_id": release_batch_id,
            },
        )

    monkeypatch.setattr(rc72_mission_factory, "create_mission_driver", fake_factory)
    exit_code = rc72_mission_cli.main([
        "run", "--ledger", str(ledger), "--source-commit", source_commit,
        "--release-batch", "B-C10", "--release-id", "REL-C10",
        "--bindings-module", "approved_host",
        "--package-root", str(package), "--evidence-root", str(tmp_path / "evidence"),
    ])
    assert exit_code == 37
    output = json.loads(capsys.readouterr().out)
    assert seen["factory"] is True
    assert all(
        getattr(binding.launcher, "_rc72_production_economy_bound", False)
        for binding in seen["workers"].values()
    )
    assert output["status"] == "HOLD"
    assert output["MISSION_COMPLETION_STATUS"] == "HOLD"
    assert output["MODEL_ECONOMY_STATUS"] == "HOLD"
    assert output["MODEL_USAGE_TOTAL_STATUS"] == "NO_CALLS"
    assert output["ACTUAL_TOTAL_TOKENS"] is None
    assert output["LOSSLESS_JSON_COMPACTED_CALLS"] == 0
    assert output["VERIFIED_PROMPT_SERIALIZATION_SAVED_BYTES"] == 0
    assert output["VERIFIED_PROMPT_TOKEN_SAVINGS"] is None
    replay = TruthRuntime(ledger)
    assert len(replay.query("rc72_token_budget", budget_id="M-CLI-C10")) == 1
    assert replay.query("rc72_token_call", mission_id="M-CLI-C10") == []


def test_cli_rejects_economy_config_for_status_and_mirror_without_opening_model(tmp_path):
    # Argument-layer regression: informational/mirror operations must not
    # mutate canonical Mission economy or start a model request.
    import pytest

    with pytest.raises(SystemExit) as e:
        rc72_mission_cli.main([
            "status", "--ledger", str(tmp_path / "does-not-exist.jsonl"),
            "--source-commit", "a" * 40, "--release-batch", "B-C10",
            "--economy-config", str(tmp_path / "untrusted.json"),
        ])
    assert e.value.code == 2



def test_real_cli_status_cold_replays_legacy_unknown_token_usage_without_loss(tmp_path, monkeypatch, capsys):
    from rc7_runtime.rc72_economy_replay_bootstrap import install_rc72_economy_replay_bindings
    from rc7_runtime.rc72_model_economy import TokenEconomyService
    from rc7_runtime.rc72_model_usage import TokenUsageAuditService
    from rc7_runtime.rc72_native_shared_batch import install_native_batch_candidate_overlay
    from rc7_runtime.rc72_native_shared_batch_review import install_native_batch_review_overlay
    from rc6_runtime import truth as _truth

    install_rc72_economy_replay_bindings()
    assert "RC72_NATIVE_BATCH_CANDIDATE_RECORDED" in _truth.EVENT_TYPES
    assert "RC72_NATIVE_BATCH_REVIEW_RECORDED" in _truth.EVENT_TYPES
    assert "RC72_RETRY_CONTEXT_COMPILED" in _truth.EVENT_TYPES
    assert "RC72_TOKEN_USAGE_OBSERVED" in _truth.EVENT_TYPES

    ledger = tmp_path / "r1.jsonl"
    initial = TruthRuntime(ledger)
    economy = TokenEconomyService(initial, release_id="REL-C10")
    economy.configure_budget(
        mission_id="MISSION-C10",
        max_total_tokens=1000, max_model_calls=10,
        max_single_call_tokens=100, max_retry_tokens=500,
        max_retry_calls=10,
    )
    TokenUsageAuditService(initial, release_id="REL-C10").observe(
        mission_id="MISSION-C10", attempt_id="ATT-LEGACY",
        assignment_id="AS-LEGACY",
        raw_output_ref="file:///local/verified-prior-dsh-jsonl",
        events=[{"type": "tool_result", "tool_name": "CAT", "usage": {
            "input_tokens": 9999, "total_tokens": 9999,
        }}],
    )
    checked = []

    def validate_replayed(truth, **kwargs):
        rows = truth.query("rc72_token_usage", mission_id="MISSION-C10")
        assert len(rows) == 1
        assert rows[0]["observation_status"] == "UNKNOWN"
        assert rows[0]["total_tokens"] is None
        assert truth.query("rc72_token_budget", budget_id="MISSION-C10")[0]["max_total_tokens"] == 1000
        checked.append("R1_REPLAYED")
        return {"status": "HOLD", "release_batch_id": "B-C10", "release_id": "REL-C10"}

    monkeypatch.setattr(rc72_mission_cli, "release_batch_status", validate_replayed)
    code = rc72_mission_cli.main([
        "status", "--ledger", str(ledger), "--source-commit", "a" * 40,
        "--release-batch", "B-C10",
    ])
    assert code == 0
    assert checked == ["R1_REPLAYED"]
    assert json.loads(capsys.readouterr().out)["status"] == "HOLD"
