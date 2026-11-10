"""R4-01: no DSH provider can self-certify Host trust roots or spawn a fake Captain."""
from types import SimpleNamespace
import importlib
import time

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_release.rc72_dsh_agentteams_factory import (
    BankCaptainTrustRoots, CaptainProviderWiring,
    configured_agentteams_host_bindings,
)
from rc7_release.rc72_dsh_agentteams_host import SignedAgentTeamsCaptain

RELEASE = "BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-R4"
COMMIT = "a" * 40
MODULE = "approved_bank_team_provider"


def _roots(provider=MODULE):
    membership = RC72AuthorityRuntime(b"bank-managed-member-authority-r4-test")
    host = RC72AuthorityRuntime(b"bank-managed-host-authority-r4-test")
    return BankCaptainTrustRoots(provider, membership, host)


def _invoke(tmp_path, *, roots=None, name=MODULE):
    return configured_agentteams_host_bindings(
        TruthRuntime(tmp_path / "r1.jsonl"),
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, config_path=str(tmp_path / "not-needed.json"),
        provider_module=name, dsh_base_url="http://127.0.0.1:4096",
        bank_trust_roots=roots)


def _wiring(roots, *, own_roots=False):
    membership = (RC72AuthorityRuntime(b"plugin-forged-member-signing-key")
                  if own_roots else roots.membership_authority)
    host = (RC72AuthorityRuntime(b"plugin-forged-host-signing-key")
            if own_roots else roots.host_authority)
    proof = SignedAgentTeamsCaptain(
        release_id=RELEASE, source_commit=COMMIT, release_batch_id=BATCH,
        mission_id="MISSION-R4", team_id="TEAM-R4",
        captain_session_id="session-r4-captain-0001",
        dsh_session_id="session-r4-captain-0001",
        role="CAPTAIN", observed_at=int(time.time()), signature="x" * 64)
    return CaptainProviderWiring(proof, membership, host,
                                 {"L3_EXECUTE": ("api_http",)}, ("api_http",))


@pytest.mark.parametrize("choice", ["missing", "wrong_name"])
def test_unapproved_provider_rejected_before_import_or_r1(tmp_path, monkeypatch, choice):
    called = []
    def importer(name):
        called.append(name)
        raise AssertionError("unapproved code was imported")
    monkeypatch.setattr(importlib, "import_module", importer)
    roots = None if choice == "missing" else _roots()
    name = MODULE if choice == "missing" else "unapproved_module"
    with pytest.raises(ContractError, match=(
            "BANK_CONTROLLED_TRUST_ROOTS_REQUIRED" if choice == "missing"
            else "PROVIDER_NOT_BANK_APPROVED")):
        _invoke(tmp_path, roots=roots, name=name)
    assert called == []
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_provider_cannot_return_own_self_signed_authorities(tmp_path, monkeypatch):
    roots = _roots()
    fake = SimpleNamespace(
        create_captain_observation_provider=lambda **kwargs:
            _wiring(roots, own_roots=True))
    monkeypatch.setattr(importlib, "import_module", lambda name: fake)
    with pytest.raises(ContractError, match="PROVIDER_SELF_SIGNED_TRUST_ROOT_FORBIDDEN"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_different_objects_with_same_signing_key_not_independent_trust_roots(
        tmp_path, monkeypatch):
    key = b"bank-duplicate-secret-not-independent"
    roots = BankCaptainTrustRoots(
        MODULE, RC72AuthorityRuntime(key), RC72AuthorityRuntime(key))
    def forbidden_import(name):
        raise AssertionError("unseparated signer reached plugin import")
    monkeypatch.setattr(importlib, "import_module", forbidden_import)
    with pytest.raises(ContractError, match="SEPARATE_BANK_SIGNERS_REQUIRED"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_approved_roots_still_require_valid_real_plugin_signature(tmp_path, monkeypatch):
    roots = _roots()
    fake = SimpleNamespace(
        create_captain_observation_provider=lambda **kwargs: _wiring(roots))
    monkeypatch.setattr(importlib, "import_module", lambda name: fake)
    # The HMAC trust roots match the bank configuration, but an unsigned
    # proof still cannot bootstrap a Captain or write a Mission/R1 event.
    with pytest.raises(ContractError, match="TEAM_SIGNATURE_INVALID"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""
