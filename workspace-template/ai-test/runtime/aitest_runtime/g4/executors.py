from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from aitest_runtime.durable_core import RuntimeError

EXECUTOR_CAPABILITIES = frozenset({
    'BROWSER_UI','API','DB_DATA','CAT_LOG','MANUAL','SECURITY','PERFORMANCE'
})
ALIASES = {
    'BROWSER':'BROWSER_UI','UI':'BROWSER_UI','BROWSER_UI':'BROWSER_UI',
    'API':'API',
    'DB':'DB_DATA','DATA':'DB_DATA','DB_DATA':'DB_DATA',
    'CAT':'CAT_LOG','LOG':'CAT_LOG','CAT_LOG':'CAT_LOG',
    'MANUAL':'MANUAL','SECURITY':'SECURITY','PERFORMANCE':'PERFORMANCE',
}

def canonical_capability(value: str) -> str:
    key=str(value or '').strip().upper()
    result=ALIASES.get(key)
    if result is None: raise RuntimeError('G4_EXECUTOR_CAPABILITY_UNKNOWN',key or '<empty>')
    return result

class CapabilityExecutorProvider(Protocol):
    capability_id: str
    capability_status: str
    safety_profile: Mapping[str, Any]
    auth_requirements: Mapping[str, Any]
    side_effect_classification: str
    retry_semantics: Mapping[str, Any]
    evidence_channels: tuple[str, ...]
    def prepare(self, step: Mapping[str, Any], runtime_facts: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def execute(self, prepared: Mapping[str, Any], execution_context: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def observe(self, result: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def collect_evidence(self, result: Mapping[str, Any]) -> list[str] | tuple[str, ...]: ...
    def cleanup(self, result: Mapping[str, Any]) -> Mapping[str, Any] | None: ...

@dataclass(frozen=True)
class ExecutorProviderDescriptor:
    capability_id: str
    capability_status: str
    safety_profile: Mapping[str, Any]
    auth_requirements: Mapping[str, Any]
    side_effect_classification: str
    retry_semantics: Mapping[str, Any]
    evidence_channels: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        return {
            'capability_id':self.capability_id,'capability_status':self.capability_status,
            'safety_profile':dict(self.safety_profile),'auth_requirements':dict(self.auth_requirements),
            'side_effect_classification':self.side_effect_classification,'retry_semantics':dict(self.retry_semantics),
            'evidence_channels':list(self.evidence_channels),
        }

class CapabilityExecutorRegistry:
    def __init__(self, providers: Mapping[str, CapabilityExecutorProvider] | None = None) -> None:
        self._providers: dict[str, CapabilityExecutorProvider]={}
        for key, provider in dict(providers or {}).items():
            self.register(key,provider)
    def register(self, capability_id: str, provider: CapabilityExecutorProvider) -> None:
        canonical=canonical_capability(capability_id)
        declared=canonical_capability(getattr(provider,'capability_id',canonical))
        if declared!=canonical: raise RuntimeError('G4_EXECUTOR_PROVIDER_CAPABILITY_MISMATCH',f'{canonical}!={declared}')
        status=str(getattr(provider,'capability_status','UNAVAILABLE')).upper()
        if status not in {'AVAILABLE','PARTIAL','UNAVAILABLE','AUTH_REQUIRED','APPROVAL_REQUIRED'}:
            raise RuntimeError('G4_EXECUTOR_PROVIDER_STATUS_INVALID',status)
        for method in ('prepare','execute','observe','collect_evidence','cleanup'):
            if not callable(getattr(provider,method,None)): raise RuntimeError('G4_EXECUTOR_PROVIDER_CONTRACT_INVALID',f'{canonical}:{method}')
        self._providers[canonical]=provider
    def get(self, capability_id: str) -> CapabilityExecutorProvider | None:
        return self._providers.get(canonical_capability(capability_id))
    def descriptor(self, capability_id: str) -> ExecutorProviderDescriptor | None:
        p=self.get(capability_id)
        if p is None: return None
        return ExecutorProviderDescriptor(
            canonical_capability(capability_id),str(getattr(p,'capability_status','UNAVAILABLE')).upper(),
            dict(getattr(p,'safety_profile',{}) or {}),dict(getattr(p,'auth_requirements',{}) or {}),
            str(getattr(p,'side_effect_classification','UNKNOWN')).upper(),dict(getattr(p,'retry_semantics',{}) or {}),
            tuple(str(x) for x in (getattr(p,'evidence_channels',()) or ())),
        )
