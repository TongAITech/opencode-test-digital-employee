"""Fail-closed validator for RC-AUTONOMOUS-TEST-LOOP machine contracts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from .autonomous_contract import (
    CANONICAL_LAYER_IDS,
    CANONICAL_NODE_IDS,
    NodeLoopState,
    canonical_coverage_targets,
    canonical_execution_profile_specs,
)
from .autonomous_events import AutonomousEvent


class AutonomousContractValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContractValidationResult:
    contract_id: str
    contract_version: str
    baseline_sha: str
    schema_files: Tuple[str, ...]
    validated: bool


_REQUIRED_SCHEMAS = (
    "node_delivery_package.schema.json",
    "layer_coverage_receipt.schema.json",
    "failure_recovery_package.schema.json",
    "defect_delivery_package.schema.json",
    "mission_convergence_package.schema.json",
)


def _load(path: Path) -> Any:
    if not path.is_file():
        raise AutonomousContractValidationError("CONTRACT_FILE_REQUIRED:%s" % path.name)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutonomousContractValidationError("CONTRACT_JSON_INVALID:%s" % path.name) from exc


def _unique_ids(rows: Any, *, code: str) -> Tuple[str, ...]:
    if not isinstance(rows, list) or not rows:
        raise AutonomousContractValidationError(code + "_REQUIRED")
    ids = tuple(str(row.get("id") or "") for row in rows if isinstance(row, dict))
    if len(ids) != len(rows) or any(not value for value in ids):
        raise AutonomousContractValidationError(code + "_ID_REQUIRED")
    if len(set(ids)) != len(ids):
        raise AutonomousContractValidationError(code + "_DUPLICATE")
    return ids


def validate_shared_contract(contract_root: Path = None) -> ContractValidationResult:
    root = contract_root or (Path(__file__).resolve().parents[1] / "contracts" / "autonomous_loop")
    root = Path(root).resolve()
    manifest: Dict[str, Any] = _load(root / "contract_manifest.json")
    if manifest.get("contract_id") != "RC-AUTONOMOUS-TEST-LOOP" or manifest.get("contract_version") != "1.0.0":
        raise AutonomousContractValidationError("CONTRACT_IDENTITY_DRIFT")
    reality = manifest.get("reality_status")
    if not isinstance(reality, dict) or reality.get("controlled_engineering") != "PASS" or reality.get("bank_field_reality") != "NOT_VERIFIED":
        raise AutonomousContractValidationError("CONTRACT_REALITY_BOUNDARY_DRIFT")
    baseline_sha = str(manifest.get("baseline_sha") or "")
    if baseline_sha != "98d7ee59cb3caf760177d7aaa933ee70082a6ff3":
        raise AutonomousContractValidationError("CONTRACT_BASELINE_SHA_DRIFT")

    nodes = _load(root / "canonical_nodes.json")
    layers = _load(root / "canonical_layers.json")
    if _unique_ids(nodes, code="CANONICAL_NODES") != CANONICAL_NODE_IDS:
        raise AutonomousContractValidationError("CANONICAL_NODE_REGISTRY_DRIFT")
    if _unique_ids(layers, code="CANONICAL_LAYERS") != CANONICAL_LAYER_IDS:
        raise AutonomousContractValidationError("CANONICAL_LAYER_REGISTRY_DRIFT")
    expected_names = tuple(canonical_execution_profile_specs()[layer]["action_kind"] for layer in CANONICAL_LAYER_IDS)
    if tuple(str(row.get("name") or "") for row in layers) != expected_names:
        raise AutonomousContractValidationError("CANONICAL_LAYER_MEANING_DRIFT")

    states = _load(root / "node_states.json")
    if tuple(states) != tuple(state.value for state in NodeLoopState):
        raise AutonomousContractValidationError("NODE_STATE_REGISTRY_DRIFT")
    if _load(root / "coverage_contracts.json") != canonical_coverage_targets():
        raise AutonomousContractValidationError("COVERAGE_TARGET_REGISTRY_DRIFT")

    events = _load(root / "r1_events.json")
    if not isinstance(events, list) or len(events) != len(set(events)) or set(events) != {item.value for item in AutonomousEvent}:
        raise AutonomousContractValidationError("R1_EVENT_REGISTRY_DRIFT")
    invariants = _load(root / "invariants.json")
    if not isinstance(invariants, list) or len(invariants) != len(set(invariants)):
        raise AutonomousContractValidationError("INVARIANT_REGISTRY_INVALID")
    for required in (
        "R1_IS_RUNTIME_TRUTH",
        "DIRECTOR_SELF_EXECUTION_FORBIDDEN",
        "NO_LOCAL_EXECUTION_FALLBACK",
        "COVERAGE_DENOMINATOR_CANNOT_SHRINK_WITHOUT_EVIDENCE",
        "TEST_FAIL_IS_NOT_DEFECT",
        "TEST_SUFFICIENCY_IS_NOT_PRODUCT_QUALITY",
    ):
        if required not in invariants:
            raise AutonomousContractValidationError("REQUIRED_INVARIANT_MISSING:%s" % required)

    routes = _load(root / "gap_routes.json")
    if not isinstance(routes, dict) or routes.get("DATA_PRECONDITION_AUTH_RESERVATION") != "N5":
        raise AutonomousContractValidationError("GAP_ROUTE_REGISTRY_DRIFT")

    schema_root = root / "schemas"
    for name in _REQUIRED_SCHEMAS:
        schema = _load(schema_root / name)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or schema.get("type") != "object":
            raise AutonomousContractValidationError("CONTRACT_SCHEMA_INVALID:%s" % name)
        if not isinstance(schema.get("required"), list) or not schema["required"]:
            raise AutonomousContractValidationError("CONTRACT_SCHEMA_REQUIRED_FIELDS_MISSING:%s" % name)

    return ContractValidationResult(
        contract_id=str(manifest["contract_id"]),
        contract_version=str(manifest["contract_version"]),
        baseline_sha=baseline_sha,
        schema_files=_REQUIRED_SCHEMAS,
        validated=True,
    )
