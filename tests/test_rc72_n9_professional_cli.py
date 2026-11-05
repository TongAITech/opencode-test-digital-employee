"""C04 trusted Mission CLI -> native N9 professional product entry.

These tests exercise the *actual CLI parser and MissionFactory invocation* with
a zero-IO Host driver spy. The independent N8/DSH/HTTP/RCA/R1/NodeGate proof
itself is covered by test_rc72_n9_professional_disposition_gate.py; this file
does not claim an engineering Host stub is a bank professional attestation.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_release import rc72_mission_cli, rc72_mission_bindings
from rc7_runtime import rc72_mission_factory
from rc7_runtime.rc72_mission_factory import MissionHostBindings


SOURCE = "b" * 40
REL = "REL-N9-PROFESSIONAL"
BATCH = "BATCH-N9-PROFESSIONAL"
REQUEST = "N9REPRO-FROZEN-PROVENANCE"
DEFECT = "DEFECT-ACTUAL-FIX-VERIFIED"
REVIEW = "bank-host://signed-independent-professional-review"


class HostSpy:
    def __init__(self, package):
        self.bank_pip_mirror = SimpleNamespace(root=package.resolve())
        self.calls = []

    def review_professional_resolution(self, **kwargs):
        self.calls.append(("review", kwargs))
        return dict(status="HOLD",
                    reason="N9_REVIEW_ACCEPTED_QUALIFICATION_AND_GAP_STILL_PENDING",
                    review_id="N9PROFREVIEW-REAL-R1",
                    n9_gate_pass=False, field_verified=False, bank_final=False)

    def accept_professional_resolution(self, **kwargs):
        self.calls.append(("adjudicate", kwargs))
        return dict(status="ADJUDICATED",
                    original_gap_evaluation_id="N9SOURCEEVAL-REAL-R1",
                    n9_gate_pass=False, field_verified=False, bank_final=False)

    def complete_professional_n9(self, **kwargs):
        self.calls.append(("gate", kwargs))
        return dict(status="PASS", state="N9_PASS",
                    n9_gate_pass=True, field_verified=False, bank_final=False)

    def run(self, **kwargs):
        pytest.fail("N9 professional Host commands must never invoke Mission run")


def _setup(tmp_path, monkeypatch):
    package = tmp_path / "source-pinned-package"
    package.mkdir()
    (package / "SOURCE_COMMIT").write_text(SOURCE, encoding="utf-8")
    ledger = tmp_path / "canonical-r1.jsonl"
    ledger.touch()  # the CLI requires an existing R1 transport, never creates one
    TruthRuntime(ledger)
    host = HostSpy(package)
    wiring = []

    def status(truth, *, source_commit, release_batch_id):
        assert source_commit == SOURCE and release_batch_id == BATCH
        return dict(release_id=REL, mission_id="M-N9-PROFESSIONAL",
                    release_batch_id=BATCH, nodes=[], status="HOLD")

    def host_bindings(module, *, truth, release_id, source_commit, release_batch_id):
        assert module == "trusted_banking_host"
        assert release_id == REL and source_commit == SOURCE
        assert release_batch_id == BATCH
        # The production layer validates the actual strict Host module and
        # its typed professional verifier; this fixture only checks that CLI
        # never switches to a configuration JSON or invokes model/business IO.
        return MissionHostBindings(
            workers={}, bank_pip_mirror=host.bank_pip_mirror,
            execution_authority=None, execution_environment=None,
            tool_registry={})

    def factory(truth, **kwargs):
        wiring.append(kwargs)
        assert kwargs["release_id"] == REL
        assert kwargs["source_commit"] == SOURCE
        assert kwargs["evidence_root"] == (tmp_path / "evidence").resolve()
        return host

    monkeypatch.setattr(rc72_mission_cli, "release_batch_status", status)
    monkeypatch.setattr(rc72_mission_bindings, "load_mission_bindings", host_bindings)
    monkeypatch.setattr(rc72_mission_factory, "create_mission_driver", factory)
    base = ["--ledger", str(ledger), "--source-commit", SOURCE,
            "--release-batch", BATCH, "--release-id", REL,
            "--bindings-module", "trusted_banking_host",
            "--package-root", str(package),
            "--evidence-root", str(tmp_path / "evidence")]
    return ledger, host, wiring, base


@pytest.mark.parametrize("command,extra,name,expected_kwargs", [
    ("review-professional",
     ["--reproduction-request", REQUEST, "--defect-id", DEFECT,
      "--attestation-ref", REVIEW],
     "review",
     {"release_batch_id": BATCH, "request_id": REQUEST,
      "defect_id": DEFECT, "attestation_ref": REVIEW}),
    ("accept-professional-resolution",
     ["--reproduction-request", REQUEST, "--defect-id", DEFECT],
     "adjudicate",
     {"release_batch_id": BATCH, "request_id": REQUEST, "defect_id": DEFECT}),
    ("complete-professional-n9", [], "gate",
     {"release_batch_id": BATCH}),
])
def test_real_cli_uses_only_the_trusted_product_entry_and_no_io(
        tmp_path, monkeypatch, capsys, command, extra, name, expected_kwargs):
    ledger, host, wiring, base = _setup(tmp_path, monkeypatch)
    before = ledger.read_bytes()
    code = rc72_mission_cli.main([command] + base + extra)
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert host.calls == [(name, expected_kwargs)]
    assert len(wiring) == 1
    assert ledger.read_bytes() == before
    assert output["field_verified"] is output["bank_final"] is False
    assert "MISSION_COMPLETION_STATUS" not in output
    assert "MODEL_ECONOMY_STATUS" not in output
    if name == "gate":
        assert output["state"] == "N9_PASS"
        assert output["n9_gate_pass"] is True
    else:
        assert output["n9_gate_pass"] is False
        assert output["status"] != "PASS"


@pytest.mark.parametrize("command,extra", [
    ("review-professional", ["--reproduction-request", REQUEST,
                             "--defect-id", DEFECT]),
    ("review-professional", ["--reproduction-request", REQUEST,
                             "--attestation-ref", REVIEW]),
    ("accept-professional-resolution", ["--reproduction-request", REQUEST,
                                        "--defect-id", DEFECT,
                                        "--attestation-ref", REVIEW]),
    ("complete-professional-n9", ["--defect-id", DEFECT]),
    ("complete-professional-n9", ["--reproduction-request", REQUEST]),
    ("review-reproduction", ["--reproduction-request", REQUEST,
                             "--attestation-ref", REVIEW,
                             "--defect-id", DEFECT]),
    ("run", ["--defect-id", DEFECT]),
])
def test_cli_rejects_untrusted_or_cross_command_professional_options(
        tmp_path, command, extra):
    with pytest.raises(SystemExit) as error:
        rc72_mission_cli.main([command,
            "--ledger", str(tmp_path / "absent-ledger"),
            "--source-commit", SOURCE,
            "--release-batch", BATCH] + extra)
    assert error.value.code == 2


@pytest.mark.parametrize("command,extra", [
    ("review-professional", ["--reproduction-request", REQUEST,
                             "--defect-id", DEFECT, "--attestation-ref", REVIEW]),
    ("accept-professional-resolution",
     ["--reproduction-request", REQUEST, "--defect-id", DEFECT]),
    ("complete-professional-n9", []),
])
def test_professional_commands_never_allow_operator_json_as_human_verifier(
        tmp_path, command, extra):
    with pytest.raises(SystemExit) as error:
        rc72_mission_cli.main([command,
            "--ledger", str(tmp_path / "absent-ledger"),
            "--source-commit", SOURCE, "--release-batch", BATCH,
            "--mission-config", str(tmp_path / "untrusted.json")] + extra)
    assert error.value.code == 2


def test_n9_gate_exit_does_not_accept_invented_bank_final_or_n10(
        tmp_path, monkeypatch, capsys):
    ledger, host, wiring, base = _setup(tmp_path, monkeypatch)
    host.complete_professional_n9 = lambda **kw: dict(
        status="PASS", state="N9_PASS", n9_gate_pass=True,
        field_verified=True, bank_final=True)
    before = ledger.read_bytes()
    assert rc72_mission_cli.main(["complete-professional-n9"] + base) == 37
    value = json.loads(capsys.readouterr().out)
    assert value["bank_final"] is True  # untrusted test signal; NOT accepted
    assert "MISSION_COMPLETION_STATUS" not in value
    assert ledger.read_bytes() == before
