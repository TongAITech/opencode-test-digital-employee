"""Proof-based N7 no-effect classification.

Only a signed negative PRE-CONDITION / DATA_RECHECK / TOOL_PROBE observation
captured by the trusted formal runner *before* any execution process or native
business transport permits a deterministic FAILED (non-business) dispatch.
Exception text is never an authority or negative-effect attestation.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from rc6_runtime import truth as registry


_CHECK_KINDS = frozenset({
    "N7_FORMAL_PRECONDITION", "N7_FORMAL_DATA_RECHECK",
    "N7_FORMAL_TOOL_PROBE", "N7_FORMAL_TOOL_UNAVAILABLE",
})
_EFFECT_TYPES = (
    "rc72_n7_http_call",
    "rc72_execution_process_heartbeat",
    "rc72_n7_formal_runner_receipt",
    "rc72_native_tool_call",
)


def verified_no_external_business_effect(preparation, prepared, error):
    """Return verified R1 evidence IDs, or empty tuple if effects are unknown.

    A trusted FormalRunnerError *alone* is insufficient. Verifying the actual
    signed negative preparation check and absence of observed execution is
    required, and only the explicit pre-execution error family is admitted.
    A tool/process crash after invocation remains UNKNOWN.
    """
    from .rc72_formal_runner import FormalRunnerError

    if not isinstance(error, FormalRunnerError):
        return ()
    if not (str(error).startswith("FORMAL_PREPARATION_NOT_SATISFIED:")
            or str(error) == "FORMAL_EXECUTION_TOOL_PROBE_FAILED"):
        return ()
    truth = preparation.truth
    attempt_id = prepared["attempt_id"]
    for artifact_type in _EFFECT_TYPES:
        if artifact_type in registry.BUCKETS and truth.query(artifact_type, attempt_id=attempt_id):
            return ()
    observed = []
    for evidence in truth.query("rc7_evidence", mission_id=prepared["mission_id"]):
        if (evidence.get("kind") not in _CHECK_KINDS
                or attempt_id not in evidence.get("subject_refs", ())
                or evidence.get("check_success") is not False
                or evidence.get("release_id") != prepared["release_id"]):
            continue
        kind = evidence["kind"][len("N7_FORMAL_"):]
        check = {
            "kind": kind, "spec": evidence["check_spec"], "success": False,
            "evidence_id": evidence["evidence_id"],
            "captured_ref": evidence["content_ref"],
            "sha256": evidence["content_hash"],
        }
        signature = preparation.authority._sign(dict(
            purpose="N7_LIVE_PREPARATION_CHECK", attempt_id=attempt_id, **check))
        actual = evidence.get("check_runtime_signature")
        if not isinstance(actual, str) or not hmac.compare_digest(actual, signature):
            return ()
        ref = check["captured_ref"]
        if not isinstance(ref, str) or not ref.startswith("file://"):
            return ()
        captured = Path(ref[len("file://"):])
        if not captured.is_file():
            return ()
        if not hmac.compare_digest(hashlib.sha256(captured.read_bytes()).hexdigest(), check["sha256"]):
            return ()
        observed.append(evidence["evidence_id"])
    # Fail closed if the exception category and attested observation differ.
    if str(error) == "FORMAL_EXECUTION_TOOL_PROBE_FAILED":
        observed = [ref for ref in observed if ref.startswith("N7PROBE-")]
    else:
        observed = [ref for ref in observed if ref.startswith("N7CHECK-")]
    return tuple(sorted(set(observed)))
