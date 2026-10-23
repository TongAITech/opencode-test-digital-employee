"""Deterministic startup reconciliation for RC8 provider/model failover."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol

from rc8_runtime.provider_recovery import RecoveryAction, RecoveryCheckpoint, SideEffectState


class ProviderCheckpointRepository(Protocol):
    def save(self, checkpoint: RecoveryCheckpoint, *, provider_ref=None, model_ref=None, now=None):
        ...

    def list_open(self, *, test_run_id=None):
        ...

    def close(self, checkpoint_id: str, *, reason="WORK_ITEM_COMPLETED", now=None):
        ...


@dataclass(frozen=True)
class ProviderResumePlan:
    checkpoint: RecoveryCheckpoint
    action: RecoveryAction
    source_provider_ref: Optional[str]
    source_model_ref: Optional[str]
    target_provider_ref: str
    target_model_ref: str
    r1_event_type: str
    reason: str

    @property
    def resume_key(self) -> str:
        return self.checkpoint.resume_key


class ProviderRecoveryService:
    """Center-owned recovery service; recovery authority never belongs to an LLM."""

    def __init__(self, repository: ProviderCheckpointRepository) -> None:
        self.repository = repository

    def checkpoint_before_request(self, checkpoint: RecoveryCheckpoint, *, provider_ref: str, model_ref: str, now: Optional[int] = None):
        if not str(provider_ref or "").strip():
            raise ValueError("PROVIDER_REF_REQUIRED")
        if not str(model_ref or "").strip():
            raise ValueError("MODEL_REF_REQUIRED")
        return self.repository.save(checkpoint, provider_ref=str(provider_ref).strip(), model_ref=str(model_ref).strip(), now=now)

    def startup_reconcile(self, *, target_provider_ref: str, target_model_ref: str, test_run_id: Optional[str] = None) -> List[ProviderResumePlan]:
        if not str(target_provider_ref or "").strip():
            raise ValueError("TARGET_PROVIDER_REF_REQUIRED")
        if not str(target_model_ref or "").strip():
            raise ValueError("TARGET_MODEL_REF_REQUIRED")
        target_provider = str(target_provider_ref).strip()
        target_model = str(target_model_ref).strip()
        plans: List[ProviderResumePlan] = []
        for stored in self.repository.list_open(test_run_id=test_run_id):
            checkpoint = stored.checkpoint
            if checkpoint.side_effect_state == SideEffectState.UNKNOWN:
                plans.append(ProviderResumePlan(
                    checkpoint=checkpoint,
                    action=RecoveryAction.RECONCILE_SIDE_EFFECT,
                    source_provider_ref=stored.provider_ref,
                    source_model_ref=stored.model_ref,
                    target_provider_ref=target_provider,
                    target_model_ref=target_model,
                    r1_event_type="PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED",
                    reason="unknown external side effect must be reconciled before failover replay",
                ))
            else:
                plans.append(ProviderResumePlan(
                    checkpoint=checkpoint,
                    action=RecoveryAction.CONTINUE,
                    source_provider_ref=stored.provider_ref,
                    source_model_ref=stored.model_ref,
                    target_provider_ref=target_provider,
                    target_model_ref=target_model,
                    r1_event_type="PROVIDER_CHECKPOINT_RESUME_READY",
                    reason="durable checkpoint recovered; resume same mission/work item/attempt from saved cursor",
                ))
        return plans

    def complete_checkpoint(self, checkpoint_id: str, *, reason: str = "WORK_ITEM_COMPLETED", now: Optional[int] = None):
        return self.repository.close(checkpoint_id, reason=reason, now=now)
