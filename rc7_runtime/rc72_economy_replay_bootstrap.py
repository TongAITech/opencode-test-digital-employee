"""Install ALL C10-owned R1 event types before opening an existing ledger.

A bank cold restart MUST project prior token usage, schedule, native batch
candidate/review and N8 RetryDelta receipts. Installing validators only after
TruthRuntime(path) has replayed the event stream loses or rejects real prior
evidence; this is not an acceptable economy shortcut.
"""
from __future__ import annotations

from .rc72_model_economy import install_rc72_token_economy_overlay
from .rc72_model_usage import install_rc72_token_usage_overlay
from .rc72_retry_context import install_rc72_retry_context_overlay
from .rc72_schedule_semantics import install_rc72_schedule_semantics_overlay
from .rc72_safe_execution_batch import install_rc72_safe_execution_batch_overlay
from .rc72_native_shared_batch_review import install_native_batch_review_overlay
from .rc72_truth import install_rc72_truth_overlay


def install_rc72_economy_replay_bindings() -> None:
    """Idempotent, C10-owned additive R1 registration only."""
    install_rc72_truth_overlay()
    install_rc72_schedule_semantics_overlay()
    install_rc72_retry_context_overlay()
    install_rc72_token_economy_overlay()
    install_rc72_token_usage_overlay()
    install_rc72_safe_execution_batch_overlay()
    install_native_batch_review_overlay()
