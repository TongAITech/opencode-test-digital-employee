#!/usr/bin/env python3
"""Validate RC8 machine-readable no-discount capability governance.

CI runs this on Windows and Linux. The validator deliberately fails closed when
claims are promoted without the gates/evidence required by their scope or when
the frozen formal Center technology stack is silently substituted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rc8_runtime.governance import ClaimState, ScopedStatusClaim, StatusScope  # noqa: E402
from rc8_runtime.contracts import RC8ContractError  # noqa: E402


KNOWN_GATES = {
    "architecture",
    "implementation",
    "automated_test",
    "coverage",
    "sufficiency",
    "product",
    "reality",
    "rc7_regression",
    "recovery",
    "deployment",
    "mission_sufficient",
}

REQUIRED_TECH_STACK = {
    "center_backend": "FastAPI",
    "api_validation": "Pydantic",
    "durable_persistence": "PostgreSQL",
    "orm": "SQLAlchemy",
    "migration": "Alembic",
    "coordination": "Redis",
    "frontend": "Vue 3",
    "frontend_language": "TypeScript",
    "frontend_build": "Vite",
    "frontend_router": "Vue Router",
    "frontend_state": "Pinia",
    "web_edge": "Nginx",
    "center_deployment": "Docker Compose",
    "stdlib_http_role": "MINIMAL_PROTOCOL_TEST_ADAPTER_ONLY",
    "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
}

REQUIRED_TECH_STACK_CONTRACT = "docs/rc8/RC8-CENTER-TECHNOLOGY-STACK-CONTRACT.md"


def _strings(value: Any, name: str) -> List[str]:
    if not isinstance(value, list):
        raise ValueError("%s_MUST_BE_LIST" % name.upper())
    result: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("%s_INVALID" % name.upper())
        result.append(item.strip())
    return result


def _claim_from_row(row: Mapping[str, Any]) -> ScopedStatusClaim:
    return ScopedStatusClaim(
        scope=StatusScope(str(row["scope"])),
        subject_id=str(row["subject_id"]),
        state=ClaimState(str(row["state"])),
        evidence_refs=tuple(_strings(row.get("evidence_refs", []), "evidence_refs")),
        reality_refs=tuple(_strings(row.get("reality_refs", []), "reality_refs")),
        evaluator_ref=(str(row["evaluator_ref"]).strip() if row.get("evaluator_ref") else None),
        coverage_refs=tuple(_strings(row.get("coverage_refs", []), "coverage_refs")),
        unresolved_gap_ids=tuple(_strings(row.get("unresolved_gap_ids", []), "unresolved_gap_ids")),
        dependency_claim_refs=tuple(_strings(row.get("dependency_claim_refs", []), "dependency_claim_refs")),
    )


def _validate_technology_stack(payload: Mapping[str, Any]) -> None:
    stack = payload.get("technology_stack")
    if not isinstance(stack, dict):
        raise ValueError("CENTER_TECHNOLOGY_STACK_REQUIRED")
    for key, expected in REQUIRED_TECH_STACK.items():
        actual = stack.get(key)
        if actual != expected:
            raise ValueError("CENTER_TECHNOLOGY_STACK_MISMATCH:%s:%s!=%s" % (key, actual, expected))


def validate(path: Path, root: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("GOVERNANCE_SCHEMA_VERSION_UNSUPPORTED")

    _validate_technology_stack(payload)

    contract_refs = _strings(payload.get("frozen_contract_refs", []), "frozen_contract_refs")
    if not contract_refs:
        raise ValueError("FROZEN_CONTRACT_REFS_REQUIRED")
    if REQUIRED_TECH_STACK_CONTRACT not in contract_refs:
        raise ValueError("CENTER_TECHNOLOGY_STACK_CONTRACT_MUST_BE_FROZEN")
    missing_contracts = [ref for ref in contract_refs if not (root / ref).is_file()]
    if missing_contracts:
        raise ValueError("FROZEN_CONTRACT_MISSING:%s" % ",".join(missing_contracts))

    rows = payload.get("claims")
    if not isinstance(rows, list) or not rows:
        raise ValueError("GOVERNANCE_CLAIMS_REQUIRED")

    by_id: Dict[str, Mapping[str, Any]] = {}
    typed: Dict[str, ScopedStatusClaim] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("GOVERNANCE_CLAIM_MUST_BE_OBJECT")
        claim_id = str(row.get("claim_id") or "").strip()
        if not claim_id:
            raise ValueError("CLAIM_ID_REQUIRED")
        if claim_id in by_id:
            raise ValueError("CLAIM_ID_DUPLICATE:%s" % claim_id)
        scope = str(row.get("scope") or "").strip()
        if not claim_id.startswith(scope + ":"):
            raise ValueError("CLAIM_ID_SCOPE_MISMATCH:%s" % claim_id)

        required = set(_strings(row.get("required_gates", []), "required_gates"))
        completed = set(_strings(row.get("completed_gates", []), "completed_gates"))
        unknown = sorted((required | completed) - KNOWN_GATES)
        if unknown:
            raise ValueError("UNKNOWN_GATES:%s:%s" % (claim_id, ",".join(unknown)))
        if not completed.issubset(required):
            extra = sorted(completed - required)
            raise ValueError("COMPLETED_GATE_NOT_REQUIRED:%s:%s" % (claim_id, ",".join(extra)))

        claim = _claim_from_row(row)
        by_id[claim_id] = row
        typed[claim_id] = claim

        if claim.state == ClaimState.REALITY_VERIFIED:
            if "reality" not in required or "reality" not in completed:
                raise ValueError("REALITY_VERIFIED_REQUIRES_REALITY_GATE:%s" % claim_id)
            if required != completed:
                missing = sorted(required - completed)
                raise ValueError("REALITY_VERIFIED_HAS_INCOMPLETE_REQUIRED_GATES:%s:%s" % (claim_id, ",".join(missing)))

        if claim.state == ClaimState.SUFFICIENT:
            if "sufficiency" not in required or "sufficiency" not in completed:
                raise ValueError("SUFFICIENT_REQUIRES_SUFFICIENCY_GATE:%s" % claim_id)
            if required != completed:
                missing = sorted(required - completed)
                raise ValueError("SUFFICIENT_HAS_INCOMPLETE_REQUIRED_GATES:%s:%s" % (claim_id, ",".join(missing)))

        if claim.scope == StatusScope.RELEASE and claim.state == ClaimState.PASS:
            if "mission_sufficient" not in completed:
                raise ValueError("RELEASE_PASS_REQUIRES_MISSION_SUFFICIENT_GATE:%s" % claim_id)
            if required != completed:
                missing = sorted(required - completed)
                raise ValueError("RELEASE_PASS_HAS_INCOMPLETE_REQUIRED_GATES:%s:%s" % (claim_id, ",".join(missing)))

    for claim_id, claim in typed.items():
        for dep in claim.dependency_claim_refs:
            if dep not in typed:
                raise ValueError("DEPENDENCY_CLAIM_NOT_FOUND:%s:%s" % (claim_id, dep))

    # A release PASS may depend only on an actually sufficient mission claim.
    for claim_id, claim in typed.items():
        if claim.scope == StatusScope.RELEASE and claim.state == ClaimState.PASS:
            mission_deps = [typed[dep] for dep in claim.dependency_claim_refs if typed[dep].scope == StatusScope.MISSION]
            if not mission_deps or any(dep.state != ClaimState.SUFFICIENT for dep in mission_deps):
                raise ValueError("RELEASE_PASS_REQUIRES_SUFFICIENT_MISSION_CLAIM:%s" % claim_id)

    # Guard the exact regression that triggered the no-discount reset: tool truth
    # and L1 truth must be represented by distinct claims.
    if "TOOL:MAVEN_JUNIT" not in typed or "LAYER:L1" not in typed:
        raise ValueError("MAVEN_AND_L1_SCOPED_CLAIMS_REQUIRED")
    if typed["TOOL:MAVEN_JUNIT"].scope == typed["LAYER:L1"].scope:
        raise ValueError("TOOL_LAYER_SCOPE_COLLAPSED")

    # Freeze the formal Center stack as a separate incomplete capability until
    # FastAPI/PostgreSQL/Redis/Vue/Nginx/Compose implementation and reality gates pass.
    stack_claim = typed.get("STAGE:CENTER_PRODUCT_STACK")
    if stack_claim is None:
        raise ValueError("CENTER_PRODUCT_STACK_SCOPED_CLAIM_REQUIRED")
    if stack_claim.state == ClaimState.REALITY_VERIFIED and by_id["STAGE:CENTER_PRODUCT_STACK"].get("completed_gates") != by_id["STAGE:CENTER_PRODUCT_STACK"].get("required_gates"):
        raise ValueError("CENTER_PRODUCT_STACK_REALITY_CANNOT_SKIP_GATES")

    return {
        "status": "PASS",
        "schema_version": 1,
        "claim_count": len(typed),
        "contract_count": len(contract_refs),
        "technology_stack": dict(REQUIRED_TECH_STACK),
        "claims": {claim_id: claim.state.value for claim_id, claim in typed.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RC8 no-discount governance claims")
    parser.add_argument(
        "--contracts",
        default=str(ROOT / "governance" / "rc8-capability-contracts.json"),
        help="path to machine-readable governance claims",
    )
    args = parser.parse_args()
    try:
        result = validate(Path(args.contracts).resolve(), ROOT)
    except (OSError, ValueError, KeyError, RC8ContractError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())