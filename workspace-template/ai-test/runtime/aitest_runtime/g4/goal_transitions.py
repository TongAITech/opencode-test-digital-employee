from __future__ import annotations

TERMINAL_GOAL_STATUSES = frozenset({
    "SATISFIED",
    "COMPLETED_WITH_ACCEPTED_GAP",
    "BLOCKED",
    "CANCELLED",
    "STOPPED",
})

# A non-terminal TestingGoal status describes the currently dominant execution or
# waiting reason. As R1 facts change, that reason may legally move between the
# operational/waiting states. Repair Wave 2's hard invariant is terminal locking:
# terminal goals never return to ordinary active/waiting states; new source/release
# work must create or supersede another goal/revision.
_OPERATIONAL_GOAL_STATUSES = frozenset({
    "ACTIVE",
    "EXECUTING",
    "MEASURING",
    "REPLANNING",
    "WAITING_HUMAN",
    "WAITING_COVERAGE_REFRESH",
    "WAITING_ENVIRONMENT",
    "WAITING_APPROVAL",
})

LEGAL_GOAL_TRANSITIONS = {
    "PROPOSED": frozenset({"PROPOSED", "ACTIVE", "CANCELLED", "STOPPED"}),
    **{
        status: frozenset(_OPERATIONAL_GOAL_STATUSES | TERMINAL_GOAL_STATUSES)
        for status in _OPERATIONAL_GOAL_STATUSES
    },
    **{status: frozenset({status}) for status in TERMINAL_GOAL_STATUSES},
}
