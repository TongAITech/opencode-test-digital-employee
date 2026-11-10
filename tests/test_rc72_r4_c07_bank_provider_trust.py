"""R4-01: bank-pinned provider code and Host roots cannot be self-certified."""
import hashlib
import time
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_release.rc72_dsh_agentteams_factory import (
    BankCaptainTrustRoots, configured_agentteams_host_bindings,
)

RELEASE = "BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-R4"
COMMIT = "a" * 40
MODULE = "approved_bank_team_provider"


def _provider_file(tmp_path, *, own_roots=False, marker=None):
    proof = """
    proof = SignedAgentTeamsCaptain(
        release_id=RELEASE, source_commit=COMMIT, release_batch_id=BATCH,
        mission_id="MISSION-R4", team_id="TEAM-R4",
        captain_session_id="session-r4-captain-0001",
        dsh_session_id="session-r4-captain-0001",
        role="CAPTAIN", observed_at=int(time.time()), signature="x" * 64)
"""
    if own_roots:
        body = """
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_release.rc72_dsh_agentteams_factory import CaptainProviderWiring
from rc7_release.rc72_dsh_agentteams_host import SignedAgentTeamsCaptain
import time
RELEASE = "BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-R4"
COMMIT = "a" * 40
def create_captain_observation_provider(**kwargs):
    membership = RC72AuthorityRuntime(b"plugin-forged-member-signing-key")
    host = RC72AuthorityRuntime(b"plugin-forged-host-signing-key")
"""+proof+"""
    return CaptainProviderWiring(
        proof, membership, host, {"L3_EXECUTE": ("api_http",)}, ("api_http",))
"""
    else:
        body = """
from rc7_release.rc72_dsh_agentteams_factory import CaptainProviderWiring
from rc7_release.rc72_dsh_agentteams_host import SignedAgentTeamsCaptain
import time
RELEASE = "BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-R4"
COMMIT = "a" * 40
def create_captain_observation_provider(**kwargs):
    membership = kwargs["membership_authority"]
    host = kwargs["host_authority"]
"""+proof+"""
    return CaptainProviderWiring(
        proof, membership, host, {"L3_EXECUTE": ("api_http",)}, ("api_http",))
"""
    if marker is not None:
        body += "\nfrom pathlib import Path\nPath(%r).write_text('executed')\n" % str(marker)
    path = tmp_path / "approved_bank_team_provider.py"
    path.write_text(body, encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _roots(tmp_path, *, provider=MODULE, own_roots=False, key=None, marker=None):
    path, digest = _provider_file(tmp_path, own_roots=own_roots, marker=marker)
    membership = RC72AuthorityRuntime(
        key or b"bank-managed-member-authority-r4-test")
    host = RC72AuthorityRuntime(
        key or b"bank-managed-host-authority-r4-test")
    return BankCaptainTrustRoots(
        provider, str(path), digest, membership, host)


def _invoke(tmp_path, *, roots=None, name=MODULE):
    return configured_agentteams_host_bindings(
        TruthRuntime(tmp_path / "r1.jsonl"),
        release_id=RELEASE, source_commit=COMMIT,
        release_batch_id=BATCH, config_path=str(tmp_path / "not-needed.json"),
        provider_module=name, dsh_base_url="http://127.0.0.1:4096",
        bank_trust_roots=roots)


def test_unapproved_provider_rejected_before_provider_file_execution_or_r1(tmp_path):
    roots = _roots(tmp_path)
    with pytest.raises(ContractError, match="PROVIDER_NOT_BANK_APPROVED"):
        _invoke(tmp_path, roots=roots, name="unapproved_bank_provider")
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_missing_host_roots_rejected_before_provider_file_execution_or_r1(tmp_path):
    roots = _roots(tmp_path)
    with pytest.raises(ContractError, match="BANK_CONTROLLED_TRUST_ROOTS_REQUIRED"):
        _invoke(tmp_path, roots=None)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_provider_cannot_return_own_self_signed_authorities(tmp_path):
    roots = _roots(tmp_path, own_roots=True)
    with pytest.raises(ContractError, match="PROVIDER_SELF_SIGNED_TRUST_ROOT_FORBIDDEN"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_different_objects_with_same_signing_key_not_independent_trust_roots(tmp_path):
    key = b"bank-duplicate-secret-not-independent"
    path, digest = _provider_file(tmp_path)
    roots = BankCaptainTrustRoots(
        MODULE, str(path), digest,
        RC72AuthorityRuntime(key), RC72AuthorityRuntime(key))
    with pytest.raises(ContractError, match="SEPARATE_BANK_SIGNERS_REQUIRED"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_approved_roots_still_require_valid_real_plugin_signature(tmp_path):
    roots = _roots(tmp_path)
    # The provider receives only the two bank-pinned authority objects. Its
    # unsigned proof still cannot bootstrap a Captain or write Mission/R1.
    with pytest.raises(ContractError, match="TEAM_SIGNATURE_INVALID"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_provider_file_digest_is_verified_before_code_execution(tmp_path):
    marker = tmp_path / "provider-executed.txt"
    roots = _roots(tmp_path, marker=marker)
    provider_path = Path(roots.approved_provider_path)
    provider_path.write_text(provider_path.read_text(encoding="utf-8") + "\n# tampered\n",
                             encoding="utf-8")
    with pytest.raises(ContractError, match="PROVIDER_DIGEST_MISMATCH"):
        _invoke(tmp_path, roots=roots)
    assert not marker.exists()
    assert (tmp_path / "r1.jsonl").read_bytes() == b""


def test_provider_path_symlink_is_rejected_before_code_execution(tmp_path):
    roots = _roots(tmp_path)
    target = Path(roots.approved_provider_path)
    alias = tmp_path / "provider-alias.py"
    try:
        alias.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("file symlink creation not permitted on this runner")
    roots = BankCaptainTrustRoots(
        MODULE, str(alias), roots.approved_provider_sha256,
        roots.membership_authority, roots.host_authority)
    with pytest.raises(ContractError, match="PROVIDER_PATH_SYMLINK_FORBIDDEN"):
        _invoke(tmp_path, roots=roots)
    assert (tmp_path / "r1.jsonl").read_bytes() == b""
