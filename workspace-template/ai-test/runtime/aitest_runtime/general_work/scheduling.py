"""Typed integration port; there is deliberately no second Scheduler here.

The future root-owner adapter builds inputs for the existing pure R2.4
readiness/selection policy and commits its decision with exact subject/CAS.
This lifecycle foundation does not yet implement Task/Attempt/session dispatch.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Sequence
from aitest_runtime.durable_core import SubjectRef, SubjectState
from aitest_runtime.r2_4.contracts import TaskReadiness


@dataclass(frozen=True)
class SubjectReadiness:
    """Typed input compatible with select_ready_tasks' pure ready-set policy.

    Candidate selection is not a dispatch permission or durable task creation.
    No counterfeit Mission/Plan identity is needed to select a bounded set.
    """
    subject: SubjectRef
    observed_seq: int
    ready_tasks: tuple[TaskReadiness, ...]


class SubjectSchedulingPort(Protocol):
    def readiness(self, subject: SubjectRef, *, observed_seq: int) -> SubjectReadiness: ...
    def commit_dispatch(self, subject: SubjectRef, *, expected_seq: int, selected: Sequence[TaskReadiness]) -> SubjectState: ...
