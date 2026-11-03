"""C10 independent N7 EvaluatorBatch: one fresh native DSH reviewer call.

Consumes an actual multi-WorkItem candidate receipt and its raw DSH evidence.
The semantic reviewer produces separate *review candidates* for each original
WorkItem/Attempt. A model's "sufficient" opinion NEVER creates an N7 assertion,
business PASS, ExecutionAttempt, NodeGate, N10 convergence or BANK_FINAL.

Native producer/reviewer sessions and worker identities must differ. The
existing deterministic N7 execution-evidence/oracle pipeline is the only
authority for real test completion.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_native_shared_batch import (
    _one, _required, install_native_batch_candidate_overlay,
)
from .rc72_native_batch_raw_proof import attest_native_raw, verify_native_raw_digest


_ARTIFACT = "rc72_native_batch_review"
_EVENT = "RC72_NATIVE_BATCH_REVIEW_RECORDED"
_BUCKET = "rc72_native_batch_reviews"


class NativeBatchReviewError(ContractError):
    pass


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("BATCH_REVIEW_OBJECT_REQUIRED")
    out = dict(payload)
    for name in (
        "review_id", "candidate_id", "release_id", "mission_id",
        "batch_id", "assignment_id", "attempt_id", "worker_instance_id",
        "producer_worker_instance_id", "producer_session_id",
        "dsh_session_id", "raw_output_ref", "status", "output_sha256",
        "token_call_id",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["status"] != "UNVERIFIED_INDEPENDENT_REVIEW":
        raise _contracts.DomainValidationError("BATCH_REVIEW_NOT_BUSINESS_PASS")
    if out["dsh_session_id"] == out["producer_session_id"]:
        raise _contracts.DomainValidationError("BATCH_REVIEW_SESSION_NOT_FRESH")
    if out["worker_instance_id"] == out["producer_worker_instance_id"]:
        raise _contracts.DomainValidationError("BATCH_REVIEW_WORKER_NOT_INDEPENDENT")
    if not out["raw_output_ref"].startswith("file://") or len(out["output_sha256"]) != 64:
        raise _contracts.DomainValidationError("BATCH_REVIEW_EVIDENCE_INVALID")
    out.setdefault("raw_output_sha256", None)
    if out["raw_output_sha256"] is not None and (
        not isinstance(out["raw_output_sha256"], str)
        or len(out["raw_output_sha256"]) != 64
    ):
        raise _contracts.DomainValidationError("BATCH_REVIEW_RAW_DIGEST_INVALID")
    reviewer_tool_refs = out.get("review_tool_refs")
    if (
        not isinstance(reviewer_tool_refs, list)
        or not reviewer_tool_refs
        or any(
            not isinstance(ref, str) or not ref.startswith("dsh-event://tool-call/")
            for ref in reviewer_tool_refs
        )
        or len(reviewer_tool_refs) != len(set(reviewer_tool_refs))
    ):
        raise _contracts.DomainValidationError("BATCH_REVIEW_NATIVE_TOOL_PROOF_REQUIRED")
    members = out.get("members")
    if not isinstance(members, list) or len(members) < 2:
        raise _contracts.DomainValidationError("BATCH_REVIEW_MEMBER_DENOMINATOR_INVALID")
    for member in members:
        if not isinstance(member, dict) or set(member) != {
            "workitem_id", "attempt_id", "evidence_adequacy",
            "criticisms", "required_followups",
        }:
            raise _contracts.DomainValidationError("BATCH_REVIEW_MEMBER_FIELDS_INVALID")
        for name in ("workitem_id", "attempt_id", "evidence_adequacy"):
            _contracts._require_str(member, name)
        if not isinstance(member["evidence_adequacy"], str) or member["evidence_adequacy"] not in {
            "SUFFICIENT_CANDIDATE", "INSUFFICIENT", "UNKNOWN"
        }:
            raise _contracts.DomainValidationError("BATCH_REVIEW_CANNOT_DECLARE_PASS")
        if not all(isinstance(member.get(key), list) for key in ("criticisms", "required_followups")):
            raise _contracts.DomainValidationError("BATCH_REVIEW_MEMBER_LISTS_INVALID")
    for key in ("workitem_id", "attempt_id"):
        if len({member[key] for member in members}) != len(members):
            raise _contracts.DomainValidationError("BATCH_REVIEW_MEMBER_%s_DUPLICATE" % key.upper())
    out["members"] = members
    if type(out.get("recorded_at")) is not int or out["recorded_at"] < 0:
        raise _contracts.DomainValidationError("BATCH_REVIEW_TIMESTAMP_INVALID")
    if type(out.get("artifact_version", 1)) is not int or out.get("artifact_version", 1) < 1:
        raise _contracts.DomainValidationError("BATCH_REVIEW_VERSION_INVALID")
    out["artifact_version"] = out.get("artifact_version", 1)
    out["artifact_type"] = _ARTIFACT
    return out


def install_native_batch_review_overlay() -> None:
    install_native_batch_candidate_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = _validate
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "review_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "review_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    if not hasattr(truth.projection, _BUCKET):
        setattr(truth.projection, _BUCKET, {})
    truth.projection._versions.setdefault(_ARTIFACT, {})


class NativeSharedEvaluatorBatch:
    def __init__(self, truth: TruthRuntime, *, release_id: str, launcher: DshHeadlessWorkerLauncher) -> None:
        install_native_batch_review_overlay()
        _ensure_bucket(truth)
        if not isinstance(launcher, DshHeadlessWorkerLauncher):
            raise NativeBatchReviewError("BATCH_REVIEW_NATIVE_DSH_LAUNCHER_REQUIRED")
        if (launcher.truth is not truth or launcher.release_id != release_id
                or not getattr(launcher, "_rc72_production_economy_bound", False)):
            raise NativeBatchReviewError("BATCH_REVIEW_METERED_DSH_REQUIRED")
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.launcher = launcher

    def review(self, *, candidate_id: str, assignment: Any) -> Dict[str, Any]:
        candidate = _one(
            self.truth, "rc72_native_batch_candidate",
            candidate_id=_required(candidate_id, "candidate_id"),
        )
        if candidate.get("release_id") != self.release_id or candidate.get("status") != "UNVERIFIED":
            raise NativeBatchReviewError("BATCH_REVIEW_CANDIDATE_INVALID")
        verify_native_raw_digest(
            raw_ref=candidate["raw_output_ref"],
            expected_sha256=candidate.get("raw_output_sha256"),
        )
        if getattr(assignment, "mission_id", None) != candidate["mission_id"]:
            raise NativeBatchReviewError("BATCH_REVIEW_MISSION_MISMATCH")
        if getattr(assignment, "scope", None) != "evaluation-batch:" + candidate["batch_id"]:
            raise NativeBatchReviewError("BATCH_REVIEW_SCOPED_LEASE_REQUIRED")
        if getattr(assignment, "worker_instance_id", None) == candidate["worker_instance_id"]:
            raise NativeBatchReviewError("BATCH_REVIEW_WORKER_MUST_DIFFER")
        if getattr(assignment, "attempt_id", None) == candidate["attempt_id"]:
            raise NativeBatchReviewError("BATCH_REVIEW_ATTEMPT_MUST_DIFFER")
        inputs = getattr(assignment, "input_refs", None)
        if (
            not isinstance(inputs, (tuple, list))
            or tuple(inputs) != (candidate["raw_output_ref"],)
        ):
            raise NativeBatchReviewError("BATCH_REVIEW_MINIMAL_PRODUCER_EVIDENCE_REQUIRED")
        review_id = "NATIVEBATCHREVIEW-" + hashlib.sha256(
            ("\x1f".join((self.release_id, candidate_id,
                         _required(getattr(assignment, "assignment_id", None), "assignment_id")))).encode()
        ).hexdigest()[:24]
        existing = self.truth.query(_ARTIFACT, review_id=review_id)
        if len(existing) > 1:
            raise NativeBatchReviewError("BATCH_REVIEW_R1_NOT_UNIQUE")
        if existing:
            verify_native_raw_digest(
                raw_ref=existing[0]["raw_output_ref"],
                expected_sha256=existing[0].get("raw_output_sha256"),
            )
            return existing[0]
        if self.truth.query(
            "rc72_token_call", mission_id=candidate["mission_id"],
            attempt_id=_required(getattr(assignment, "attempt_id", None), "attempt_id"),
        ):
            raise NativeBatchReviewError("BATCH_REVIEW_PREVIOUS_ATTEMPT_REQUIRES_NEW_ASSIGNMENT")

        context = {
            "mission_id": candidate["mission_id"],
            "batch_id": candidate["batch_id"],
            "candidate_id": candidate_id,
            "producer_session_id": candidate["dsh_session_id"],
            "producer_raw_evidence_ref": candidate["raw_output_ref"],
            "members": [
                {
                    "workitem_id": member["workitem_id"],
                    "attempt_id": member["attempt_id"],
                    "observed_tool_refs": member["observed_tool_refs"],
                    "proposed_observation": member["proposed_observation"],
                    "gaps": member["gaps"], "unknowns": member["unknowns"],
                }
                for member in candidate["members"]
            ],
        }
        shape = {
            "status": "REVIEW_CANDIDATE",
            "members": [
                {
                    "workitem_id": member["workitem_id"],
                    "attempt_id": member["attempt_id"],
                    "evidence_adequacy": "SUFFICIENT_CANDIDATE|INSUFFICIENT|UNKNOWN",
                    "criticisms": ["actual source-based concern"],
                    "required_followups": ["real N7 oracle/evidence work still needed"],
                }
                for member in candidate["members"]
            ],
        }
        prompt = (
            "You are an INDEPENDENT RC7.2 semantic batch reviewer. Read the "
            "real producer raw DSH output and evaluate every independent "
            "WorkItem/Attempt, checking source, negative scenarios, Oracle "
            "and gaps. Use real approved tools; no inherited producer verdict. "
            "Return only one REVIEW_CANDIDATE per source member. This is NOT "
            "business PASS; canonical N7 actual execution, deterministic "
            "assertion, Evidence Review and N8/N9/N10 remain required. "
            "Context=" + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " RequiredShape=" + json.dumps(shape, ensure_ascii=False, sort_keys=True)
        )
        invocation, output = self.launcher.execute(assignment, prompt)
        session = _required(getattr(invocation, "dsh_session_id", None), "dsh_session_id")
        if session == candidate["dsh_session_id"]:
            raise NativeBatchReviewError("BATCH_REVIEW_SESSION_NOT_FRESH")
        reviewer_tool_refs = [
            row["call_ref"] for row in getattr(invocation, "tool_calls", ())
            if isinstance(row, dict)
            and isinstance(row.get("call_ref"), str)
            and row["call_ref"].startswith("dsh-event://tool-call/")
        ]
        if not reviewer_tool_refs or len(set(reviewer_tool_refs)) != len(reviewer_tool_refs):
            raise NativeBatchReviewError("BATCH_REVIEW_REAL_NATIVE_TOOL_PROOF_REQUIRED")
        raw = [
            ref for ref in getattr(invocation, "evidence_refs", ())
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(raw) != 1:
            raise NativeBatchReviewError("BATCH_REVIEW_RAW_EVIDENCE_NOT_UNIQUE")
        raw_proof = attest_native_raw(
            self.launcher, raw_ref=raw[0], session_id=session,
            expected_tool_refs=reviewer_tool_refs,
        )
        if not isinstance(output, dict) or set(output) != {"status", "members"}:
            raise NativeBatchReviewError("BATCH_REVIEW_STRICT_OUTPUT_REQUIRED")
        if output["status"] != "REVIEW_CANDIDATE":
            raise NativeBatchReviewError("BATCH_REVIEW_MODEL_CANNOT_ASSERT_PASS")
        rows = output["members"]
        if not isinstance(rows, list) or len(rows) != len(candidate["members"]):
            raise NativeBatchReviewError("BATCH_REVIEW_OUTPUT_DENOMINATOR_MISMATCH")
        expected = {
            (member["workitem_id"], member["attempt_id"]): member
            for member in candidate["members"]
        }
        matched = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "workitem_id", "attempt_id", "evidence_adequacy",
                "criticisms", "required_followups",
            }:
                raise NativeBatchReviewError("BATCH_REVIEW_MEMBER_FIELDS_INVALID")
            if any(
                not isinstance(row.get(name), str) or not row[name].strip()
                for name in ("workitem_id", "attempt_id")
            ):
                raise NativeBatchReviewError("BATCH_REVIEW_MEMBER_IDENTITY_INVALID")
            pair = (row["workitem_id"], row["attempt_id"])
            if pair not in expected or pair in matched:
                raise NativeBatchReviewError("BATCH_REVIEW_MEMBER_IDENTITY_MISMATCH")
            if not isinstance(row.get("evidence_adequacy"), str) or row["evidence_adequacy"] not in {
                "SUFFICIENT_CANDIDATE", "INSUFFICIENT", "UNKNOWN"
            }:
                raise NativeBatchReviewError("BATCH_REVIEW_CANNOT_ASSERT_PASS")
            if not all(isinstance(row.get(key), list) for key in ("criticisms", "required_followups")):
                raise NativeBatchReviewError("BATCH_REVIEW_MEMBER_CRITICISMS_REQUIRED")
            matched[pair] = dict(row)
        if set(matched) != set(expected):
            raise NativeBatchReviewError("BATCH_REVIEW_INCOMPLETE")
        ordered = [
            matched[(member["workitem_id"], member["attempt_id"])]
            for member in candidate["members"]
        ]
        metering = _one(
            self.truth, "rc72_token_call",
            mission_id=candidate["mission_id"],
            workitem_id="EVALUATOR_BATCH:" + candidate["batch_id"],
            attempt_id=assignment.attempt_id,
        )
        if metering.get("process_outcome") != "RETURNED":
            raise NativeBatchReviewError("BATCH_REVIEW_REAL_DSH_CALL_PROOF_REQUIRED")
        encoded = json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload = {
            "review_id": review_id,
            "candidate_id": candidate_id,
            "release_id": self.release_id,
            "mission_id": candidate["mission_id"],
            "batch_id": candidate["batch_id"],
            "assignment_id": assignment.assignment_id,
            "attempt_id": assignment.attempt_id,
            "worker_instance_id": assignment.worker_instance_id,
            "producer_worker_instance_id": candidate["worker_instance_id"],
            "producer_session_id": candidate["dsh_session_id"],
            "dsh_session_id": session,
            "raw_output_ref": raw[0],
            "raw_output_sha256": raw_proof["raw_output_sha256"],
            "review_tool_refs": reviewer_tool_refs,
            "output_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "token_call_id": metering["call_id"],
            "status": "UNVERIFIED_INDEPENDENT_REVIEW",
            "members": ordered,
            "recorded_at": int(time.time()),
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        return _one(self.truth, _ARTIFACT, review_id=review_id)
