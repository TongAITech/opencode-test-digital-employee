"""Frozen N4 test-case inventory authority for case-scoped execution work.

N5/N6/N7 may fan out only from a TEST_DESIGN artifact that is referenced by the
latest completed TEST_DESIGN Stage, produced by that Stage's projected COMPLETED
Attempt, AVAILABLE in Center's hash-verified Artifact Store, and self-describing
with the frozen RC8 case-inventory schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Tuple

from rc8_runtime import ArtifactAvailability, AttemptStatus
from rc8_runtime.mission_graph import MissionStageType

from .artifacts import FileArtifactStore
from .repository_ports import ArtifactMetadataRepository, GovernanceRepository


CASE_INVENTORY_KIND = "TEST_CASE_INVENTORY"
CASE_INVENTORY_SCHEMA = "rc8.test-case-inventory.v1"


class FrozenCaseInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrozenCaseIdentity:
    case_id: str
    case_revision_ref: str


@dataclass(frozen=True)
class FrozenCaseInventory:
    test_run_id: str
    scope_version: str
    stage_instance_id: str
    artifact_id: str
    artifact_sha256: str
    cases: Tuple[FrozenCaseIdentity, ...]

    @property
    def artifact_ref(self) -> str:
        return "artifact:%s" % self.artifact_id

    @property
    def fingerprint_ref(self) -> str:
        return "case-inventory-sha256:%s" % self.artifact_sha256


def _required(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrozenCaseInventoryError("%s_REQUIRED" % name.upper())
    return value.strip()


def _artifact_id(ref: str) -> str:
    value = _required(ref, "artifact_ref")
    return value.split(":", 1)[1] if value.startswith("artifact:") else value


class CenterFrozenCaseInventoryResolver:
    def __init__(
        self,
        *,
        governance_repository: GovernanceRepository,
        control_repository: object,
        artifact_repository: ArtifactMetadataRepository,
        artifact_store: FileArtifactStore,
    ) -> None:
        self.governance_repository = governance_repository
        self.control_repository = control_repository
        self.artifact_repository = artifact_repository
        self.artifact_store = artifact_store

    def resolve(self, *, test_run_id: str, scope_version: str) -> FrozenCaseInventory:
        run_id = _required(test_run_id, "test_run_id")
        scope = _required(scope_version, "scope_version")
        design = self._latest_completed_design_stage(run_id, scope)
        manifest = self._inventory_manifest(design)
        self._validate_attempt_authority(design, manifest)

        if manifest.availability != ArtifactAvailability.AVAILABLE:
            raise FrozenCaseInventoryError("CASE_INVENTORY_ARTIFACT_NOT_AVAILABLE")
        if manifest.test_run_id != run_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_TEST_RUN_MISMATCH")
        if str(manifest.metadata.get("schema_version") or "") != CASE_INVENTORY_SCHEMA:
            raise FrozenCaseInventoryError("CASE_INVENTORY_SCHEMA_METADATA_MISMATCH")

        path = self.artifact_store.content_path(manifest.artifact_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise FrozenCaseInventoryError("CASE_INVENTORY_JSON_INVALID") from exc
        if not isinstance(payload, dict):
            raise FrozenCaseInventoryError("CASE_INVENTORY_OBJECT_REQUIRED")
        if str(payload.get("schema_version") or "") != CASE_INVENTORY_SCHEMA:
            raise FrozenCaseInventoryError("CASE_INVENTORY_SCHEMA_MISMATCH")
        if str(payload.get("test_run_id") or "") != run_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_CONTENT_TEST_RUN_MISMATCH")
        if str(payload.get("stage_instance_id") or "") != design.stage_instance_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_STAGE_MISMATCH")
        if str(payload.get("scope_version") or "") != scope:
            raise FrozenCaseInventoryError("CASE_INVENTORY_SCOPE_MISMATCH")

        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise FrozenCaseInventoryError("CASE_INVENTORY_CASES_REQUIRED")
        cases: List[FrozenCaseIdentity] = []
        seen = set()
        for item in raw_cases:
            if not isinstance(item, dict):
                raise FrozenCaseInventoryError("CASE_INVENTORY_CASE_OBJECT_REQUIRED")
            case_id = _required(item.get("case_id"), "case_id")
            revision_ref = _required(item.get("case_revision_ref"), "case_revision_ref")
            if case_id in seen:
                raise FrozenCaseInventoryError("CASE_INVENTORY_DUPLICATE_CASE_ID:%s" % case_id)
            seen.add(case_id)
            cases.append(FrozenCaseIdentity(case_id=case_id, case_revision_ref=revision_ref))

        return FrozenCaseInventory(
            test_run_id=run_id,
            scope_version=scope,
            stage_instance_id=design.stage_instance_id,
            artifact_id=manifest.artifact_id,
            artifact_sha256=manifest.sha256.lower(),
            cases=tuple(sorted(cases, key=lambda value: value.case_id)),
        )

    def _latest_completed_design_stage(self, test_run_id: str, scope_version: str):
        candidates = [
            stage
            for stage in self.governance_repository.list_stages(test_run_id)
            if stage.stage_type == MissionStageType.TEST_DESIGN.value
            and stage.scope_version == scope_version
        ]
        if not candidates:
            raise FrozenCaseInventoryError("CASE_INVENTORY_TEST_DESIGN_STAGE_REQUIRED")
        latest = sorted(candidates, key=lambda value: value.attempt_no)[-1]
        if str(latest.state.value) != "COMPLETED":
            raise FrozenCaseInventoryError("CASE_INVENTORY_TEST_DESIGN_STAGE_NOT_COMPLETED")
        return latest

    def _inventory_manifest(self, design):
        inventory = []
        for ref in design.output_refs:
            artifact_id = _artifact_id(ref)
            manifest = self.artifact_repository.get(artifact_id)
            if manifest is not None and manifest.kind == CASE_INVENTORY_KIND:
                inventory.append(manifest)
        if not inventory:
            raise FrozenCaseInventoryError("CASE_INVENTORY_ARTIFACT_REQUIRED")
        if len(inventory) != 1:
            raise FrozenCaseInventoryError("CASE_INVENTORY_ARTIFACT_MUST_BE_UNIQUE")
        return inventory[0]

    def _validate_attempt_authority(self, design, manifest) -> None:
        attempt_id = _required(manifest.attempt_id, "case_inventory_attempt_id")
        attempt = self.governance_repository.get_attempt(attempt_id)
        if attempt is None or attempt.status != AttemptStatus.COMPLETED:
            raise FrozenCaseInventoryError("CASE_INVENTORY_COMPLETED_ATTEMPT_REQUIRED")
        if attempt.test_run_id != design.test_run_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_ATTEMPT_TEST_RUN_MISMATCH")
        if attempt.stage_instance_id != design.stage_instance_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_ATTEMPT_STAGE_MISMATCH")
        if attempt.work_item_id != manifest.work_item_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_ATTEMPT_WORK_ITEM_MISMATCH")
        if "artifact:%s" % manifest.artifact_id not in attempt.evidence_refs:
            raise FrozenCaseInventoryError("CASE_INVENTORY_NOT_BOUND_TO_COMPLETED_ATTEMPT")
        link = self.control_repository.get_stage_link_for_work_item(manifest.work_item_id)
        if link is None or link.stage_instance_id != design.stage_instance_id:
            raise FrozenCaseInventoryError("CASE_INVENTORY_WORK_ITEM_STAGE_LINK_REQUIRED")
