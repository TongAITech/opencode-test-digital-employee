from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError


POLICY_ID = "r1.3a.structural"
POLICY_VERSION = 1
SECTION_ORDER = ("execution", "runtime", "work_graph", "knowledge")


def _positive(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class SectionPolicy:
    name: str
    max_items: int
    max_bytes: int

    def __post_init__(self) -> None:
        if self.name not in SECTION_ORDER:
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", f"Unknown section: {self.name}")
        object.__setattr__(self, "max_items", _positive(self.max_items, f"{self.name}.max_items"))
        object.__setattr__(self, "max_bytes", _positive(self.max_bytes, f"{self.name}.max_bytes"))

    def to_dict(self) -> dict[str, Any]:
        return {"max_items": self.max_items, "max_bytes": self.max_bytes}


@dataclass(frozen=True)
class ExecutionContextPolicy:
    policy_id: str
    policy_version: int
    max_total_bytes: int
    max_metadata_bytes: int
    max_sections: int
    max_items_total: int
    max_item_bytes: int
    max_omission_samples: int
    sections: Mapping[str, SectionPolicy]

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "policy_id must be a non-empty string")
        for name in (
            "policy_version",
            "max_total_bytes",
            "max_metadata_bytes",
            "max_sections",
            "max_items_total",
            "max_item_bytes",
            "max_omission_samples",
        ):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if not isinstance(self.sections, Mapping) or tuple(self.sections) != SECTION_ORDER:
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "sections must use the frozen section order")
        copied = {name: self.sections[name] for name in SECTION_ORDER}
        if any(not isinstance(item, SectionPolicy) or item.name != name for name, item in copied.items()):
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "section policies do not match their names")
        if self.max_sections != len(SECTION_ORDER):
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "max_sections must equal four")
        object.__setattr__(self, "sections", MappingProxyType(copied))

    def section(self, name: str) -> SectionPolicy:
        try:
            return self.sections[name]
        except KeyError as exc:
            raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", f"Unknown section: {name}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "max_total_bytes": self.max_total_bytes,
            "max_metadata_bytes": self.max_metadata_bytes,
            "max_sections": self.max_sections,
            "max_items_total": self.max_items_total,
            "max_item_bytes": self.max_item_bytes,
            "max_omission_samples": self.max_omission_samples,
            "sections": {name: self.sections[name].to_dict() for name in SECTION_ORDER},
        }


R1_3A_STRUCTURAL_POLICY = ExecutionContextPolicy(
    policy_id=POLICY_ID,
    policy_version=POLICY_VERSION,
    max_total_bytes=65536,
    max_metadata_bytes=8192,
    max_sections=4,
    max_items_total=64,
    max_item_bytes=16384,
    max_omission_samples=16,
    sections=MappingProxyType(
        {
            "execution": SectionPolicy("execution", 1, 4096),
            "runtime": SectionPolicy("runtime", 8, 12288),
            "work_graph": SectionPolicy("work_graph", 31, 28672),
            "knowledge": SectionPolicy("knowledge", 24, 12288),
        }
    ),
)


class ExecutionContextPolicyRegistry:
    def __init__(self, policies: tuple[ExecutionContextPolicy, ...] = (R1_3A_STRUCTURAL_POLICY,)) -> None:
        values: dict[tuple[str, int], ExecutionContextPolicy] = {}
        for policy in policies:
            if not isinstance(policy, ExecutionContextPolicy):
                raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "registry values must be policies")
            key = (policy.policy_id, policy.policy_version)
            if key in values:
                raise RuntimeError("EXECUTION_CONTEXT_POLICY_INVALID", "duplicate policy identity and version")
            values[key] = policy
        self._policies = MappingProxyType(values)

    def get(self, policy_id: str, policy_version: int) -> ExecutionContextPolicy:
        try:
            return self._policies[(policy_id, policy_version)]
        except KeyError as exc:
            raise RuntimeError(
                "EXECUTION_CONTEXT_POLICY_NOT_FOUND",
                f"Execution Context policy not found: {policy_id}@{policy_version}",
            ) from exc

    def resolve(self, policy_id: str, policy_version: int) -> ExecutionContextPolicy:
        return self.get(policy_id, policy_version)
