"""Explicit RC7.2 durable schema bootstrap; no services are executed here.

The package invokes this after compatibility adapters have loaded, before any
external RC7.2 caller can construct or replay a TruthRuntime. Keep the allowlist
explicit: importing an arbitrary plugin must never authorize an unknown event.
"""
from importlib import import_module
from threading import RLock

_LOCK = RLock()
_INSTALLED = False
_INSTALLERS = (
    ('rc72_n7_member_drain', 'install_rc72_n7_member_drain_overlay'),
    ('rc72_execution_heartbeat', 'install_rc72_execution_heartbeat_overlay'),
    ('rc72_lease_renewal', 'install_rc72_lease_renewal_overlay'),
    ('rc72_capability_resolution', 'install_rc72_capability_resolution_overlay'),
    ('rc72_n8_retry_truth', 'install_rc72_n8_retry_truth_overlay'),
    ('rc72_n5_existing_data_repair_truth', 'install_rc72_n5_existing_data_repair_overlay'),
    ('rc72_n8_repair_boundary', 'install_rc72_n8_repair_boundary_overlay'),
    ('rc72_n8_execution_diagnosis', 'install_rc72_n8_execution_diagnosis_overlay'),
    ('rc72_n7_finalization', 'install_rc72_n7_finalization_overlay'),
    ('rc72_formal_runner', 'install_rc72_formal_runner_overlay'),
    ('rc72_n7_evidence_review', 'install_rc72_n7_evidence_review_overlay'),
    ('rc72_n7_cleanup', 'install_rc72_n7_cleanup_overlay'),
    ('rc72_n7_tool_dispatch', 'install_rc72_n7_tool_dispatch_overlay'),
    ('rc72_n7_execution_preparation', 'install_rc72_n7_execution_preparation_overlay'),
    ('rc72_n7_execution_planning', 'install_rc72_n7_execution_planning_overlay'),
    ('rc72_n7_execution_admission', 'install_rc72_n7_execution_admission_overlay'),
    ('rc72_browser_resources', 'install_rc72_browser_overlay'),
    ('rc72_capability_broker', 'install_rc72_capability_overlay'),
    ('rc72_coverage_convergence', 'install_rc72_coverage_overlay'),
    ('rc72_data_resources', 'install_rc72_data_overlay'),
    ('rc72_decomposition_truth', 'install_rc72_decomposition_truth_overlay'),
    ('rc72_deterministic_first', 'install_rc72_deterministic_first_overlay'),
    ('rc72_diagnosis_orchestration', 'install_rc72_diagnosis_overlay'),
    ('rc72_field_mission_start', 'install_rc72_field_mission_start_overlay'),
    ('rc72_field_qualification', 'install_rc72_field_qualification_overlay'),
    ('rc72_impact_truth', 'install_rc72_impact_truth_overlay'),
    ('rc72_journey_benchmark', 'install_rc72_journey_benchmark_overlay'),
    ('rc72_journey_compiler', 'install_rc72_journey_compiler_overlay'),
    ('rc72_journey_promotion', 'install_rc72_journey_promotion_overlay'),
    ('rc72_journey_replay', 'install_rc72_journey_replay_overlay'),
    ('rc72_journey_teaching', 'install_rc72_journey_teaching_overlay'),
    ('rc72_mission_node_assignment', 'install_rc72_mission_node_assignment_overlay'),
    ('rc72_mission_node_dispatch', 'install_rc72_mission_node_dispatch_overlay'),
    ('rc72_mission_node_handoff', 'install_rc72_mission_node_handoff_overlay'),
    ('rc72_model_economy', 'install_rc72_token_economy_overlay'),
    ('rc72_model_failover', 'install_rc72_model_failover_overlay'),
    ('rc72_model_usage', 'install_rc72_token_usage_overlay'),
    ('rc72_n1_completion', 'install_rc72_n1_completion_overlay'),
    ('rc72_n1_executable_binding', 'install_rc72_n1_executable_binding_overlay'),
    ('rc72_n1_revision', 'install_rc72_n1_revision_overlay'),
    ('rc72_n2_candidate_guard', 'install_rc72_n2_candidate_guard_overlay'),
    ('rc72_n2_requirement_assignment', 'install_rc72_n2_requirement_assignment_overlay'),
    ('rc72_n2_requirement_dispatch', 'install_rc72_n2_requirement_dispatch_overlay'),
    ('rc72_n2_requirement_handoff', 'install_rc72_n2_requirement_handoff_overlay'),
    ('rc72_n2_revision', 'install_rc72_n2_revision_overlay'),
    ('rc72_n2_revision_execution', 'install_rc72_n2_revision_execution_overlay'),
    ('rc72_n3_code_analysis_anchor', 'install_rc72_n3_code_analysis_anchor_overlay'),
    ('rc72_n3_code_analysis_assignment', 'install_rc72_n3_code_analysis_assignment_overlay'),
    ('rc72_n3_code_analysis_dispatch', 'install_rc72_n3_code_analysis_dispatch_overlay'),
    ('rc72_n3_code_analysis_handoff', 'install_rc72_n3_code_analysis_handoff_overlay'),
    ('rc72_n3_source_target_anchor', 'install_rc72_n3_source_target_anchor_overlay'),
    ('rc72_n3_source_target_assignment', 'install_rc72_n3_source_target_assignment_overlay'),
    ('rc72_n3_source_target_dispatch', 'install_rc72_n3_source_target_dispatch_overlay'),
    ('rc72_n3_source_target_handoff', 'install_rc72_n3_source_target_handoff_overlay'),
    ('rc72_n3_source_target_revision', 'install_rc72_n3_source_target_revision_overlay'),
    ('rc72_n3_source_target_revision_handoff', 'install_rc72_n3_source_target_revision_handoff_overlay'),
    ('rc72_n4_test_design_anchor', 'install_rc72_n4_test_design_anchor_overlay'),
    ('rc72_n4_test_design_assignment', 'install_rc72_n4_test_design_assignment_overlay'),
    ('rc72_n4_test_design_dispatch', 'install_rc72_n4_test_design_dispatch_overlay'),
    ('rc72_n4_test_design_handoff', 'install_rc72_n4_test_design_handoff_overlay'),
    ('rc72_n5_data_discovery_anchor', 'install_rc72_n5_data_discovery_anchor_overlay'),
    ('rc72_n5_data_discovery_assignment', 'install_rc72_n5_data_discovery_assignment_overlay'),
    ('rc72_n5_data_discovery_dispatch', 'install_rc72_n5_data_discovery_dispatch_overlay'),
    ('rc72_n5_data_discovery_handoff', 'install_rc72_n5_data_discovery_handoff_overlay'),
    ('rc72_n5_data_inventory', 'install_rc72_n5_data_inventory_overlay'),
    ('rc72_n5_data_resolution', 'install_rc72_n5_data_resolution_overlay'),
    ('rc72_n5_data_verification_anchor', 'install_rc72_n5_data_verification_anchor_overlay'),
    ('rc72_n5_data_verification_finalization', 'install_rc72_n5_data_verification_finalization_overlay'),
    ('rc72_n5_data_verification_handoff', 'install_rc72_n5_data_verification_handoff_overlay'),
    ('rc72_n6_completion', 'install_rc72_n6_completion_overlay'),
    ('rc72_official_journey_execution', 'install_rc72_official_journey_execution_overlay'),
    ('rc72_q7_admission', 'install_rc72_q7_admission_overlay'),
    ('rc72_release_convergence', 'install_rc72_release_convergence_overlay'),
    ('rc72_release_provenance', 'install_rc72_release_provenance_overlay'),
    ('rc72_release_scope', 'install_rc72_release_scope_overlay'),
    ('rc72_retry_context', 'install_rc72_retry_context_overlay'),
    ('rc72_safe_execution_batch', 'install_rc72_safe_execution_batch_overlay'),
    ('rc72_schedule_semantics', 'install_rc72_schedule_semantics_overlay'),
    ('rc72_semantic_cache', 'install_rc72_semantic_cache_overlay'),
    ('rc72_sufficiency', 'install_rc72_sufficiency_truth_overlay'),
    ('rc72_truth', 'install_rc72_truth_overlay'),
    ('rc72_usage_ledger', 'install_rc72_usage_ledger_overlay'),
    ('rc72_worker_lifecycle', 'install_rc72_worker_lifecycle_overlay'),
)


def bootstrap_rc72_truth() -> None:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        for module_name, installer_name in _INSTALLERS:
            module = import_module("." + module_name, __package__)
            getattr(module, installer_name)()
        _INSTALLED = True
