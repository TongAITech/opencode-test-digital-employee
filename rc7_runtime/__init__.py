"""RC7 autonomous testing control-plane runtime.

RC7 is an additive refactor over the proven RC6 capability surface.  The
package owns durable control-plane semantics (Mission/Task/Artifact/Evidence/
Gap/Evaluation/Event); existing RC6 testing capabilities remain reusable and
are integrated through adapters in later work items.
"""

from .models import (
    Artifact,
    ArtifactStatus,
    Evaluation,
    EvaluationResult,
    EventRecord,
    Evidence,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)
from .state_machine import (
    ConvergenceInput,
    ConvergenceDecision,
    decide_convergence,
    invalidate_artifact,
    transition_gap,
    transition_mission,
    transition_task,
)

__all__ = [
    "Artifact",
    "ArtifactStatus",
    "Evaluation",
    "EvaluationResult",
    "EventRecord",
    "Evidence",
    "Gap",
    "GapSeverity",
    "GapStatus",
    "Mission",
    "MissionStatus",
    "Task",
    "TaskStatus",
    "ConvergenceInput",
    "ConvergenceDecision",
    "decide_convergence",
    "invalidate_artifact",
    "transition_gap",
    "transition_mission",
    "transition_task",
]
