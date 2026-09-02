from __future__ import annotations

from typing import Any, Mapping

from .contracts import PageGraph, PageRuntimeReconciliation, SourceRef
from .errors import R35Error


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return dict(result)
    raise R35Error("R3_5_SCHEMA_INVALID", f"{name} must be a mapping or to_dict value")


def _auth_valid(auth_context: Any) -> bool:
    value = _as_mapping(auth_context, "auth_context")
    status = str(value.get("status") or "").upper()
    validation = str(value.get("validation_status") or value.get("validationStatus") or "").upper()
    if status not in {"AUTHENTICATED", "VALID"} and validation != "VALID":
        return False
    if validation and validation != "VALID":
        return False
    receipt = value.get("verification_receipt") if isinstance(value.get("verification_receipt"), Mapping) else {}
    real_runtime = value.get("real_runtime", receipt.get("real_runtime", True))
    if real_runtime is False:
        return False
    verifier_kind = str(value.get("verifier_kind") or receipt.get("verifier_kind") or "").upper()
    return verifier_kind not in {"MOCK", "FAKE", "NOT_CONFIGURED"}


def verify_sut_auth_context(
    auth_service: Any,
    *,
    mission_id: str,
    auth_context_ref: Mapping[str, Any],
    expected_browser_context_ref: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> Mapping[str, Any]:
    """Read and validate an existing R3.E2 context; never creates auth truth."""
    if auth_service is None or not callable(getattr(auth_service, "get_context", None)):
        raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "R3.E2 SUTAuthContext seam is unavailable")
    ref = _as_mapping(auth_context_ref, "auth_context_ref")
    context_id = ref.get("auth_context_id") or ref.get("context_id") or ref.get("sut_auth_context_id")
    context_epoch = ref.get("context_epoch")
    if not isinstance(context_id, str) or not context_id.strip() or not isinstance(context_epoch, int):
        raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "auth_context_ref requires exact context identity and epoch")
    try:
        context = auth_service.get_context(mission_id, context_id, context_epoch)
    except Exception as exc:
        raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "R3.E2 rejected the requested SUTAuthContext") from exc
    if context is None:
        raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "SUTAuthContext was not found")
    value = _as_mapping(context, "sut_auth_context")
    if not _auth_valid(value):
        raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "SUTAuthContext is not valid real runtime auth")
    if observed_at and value.get("expires_at") and str(observed_at) >= str(value["expires_at"]):
        raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "SUTAuthContext is expired")
    if expected_browser_context_ref is not None and value.get("browser_context_ref") is not None:
        if not _context_equal(value["browser_context_ref"], expected_browser_context_ref):
            raise R35Error("R3_5_BROWSER_CONTEXT_MISMATCH", "SUTAuthContext is bound to another Browser context")
    return value


def _context_equal(left: Any, right: Any) -> bool:
    return _as_mapping(left, "browser_context_ref") == _as_mapping(right, "expected_browser_context_ref")


def _route_matches(node: Any, route: str | None) -> bool:
    if not route:
        return False
    for pattern in node.route_patterns:
        if pattern == route or pattern == "*" or (pattern.endswith("*") and route.startswith(pattern[:-1])):
            return True
    return node.page_key == route


def reconcile_page_runtime(
    graph: PageGraph,
    *,
    browser_context_ref: Mapping[str, Any] | Any,
    observation: Mapping[str, Any] | None = None,
    auth_context: Mapping[str, Any] | Any | None = None,
    protected: bool = False,
    permission_visible: bool = True,
    auth_service: Any | None = None,
    auth_context_ref: Mapping[str, Any] | None = None,
    browser_runtime: Any | None = None,
    mission_id: str | None = None,
) -> PageRuntimeReconciliation:
    if not isinstance(graph, PageGraph):
        raise R35Error("R3_5_SCHEMA_INVALID", "reconciliation requires a source-backed PageGraph")
    context = _as_mapping(browser_context_ref, "browser_context_ref")
    if browser_runtime is not None:
        try:
            inspected_context = browser_runtime.inspect_context(browser_context_ref)
            inspected_lease = browser_runtime.inspect_lease(browser_context_ref)
            inspected_context_value = _as_mapping(inspected_context, "browser_context_ref")
            if str(inspected_lease) != str(context.get("lease_owner") or context.get("observed_lease_owner")):
                raise R35Error("R3_5_BROWSER_LEASE_MISMATCH", "R3.E3 lease differs from BrowserContextRef")
            context = inspected_context_value
            if observation is None:
                observation = _as_mapping(browser_runtime.context_observation(browser_context_ref), "observation")
        except R35Error:
            raise
        except Exception as exc:
            raise R35Error("R3_5_BROWSER_CONTEXT_MISMATCH", "R3.E3 Browser context inspection failed") from exc
    raw = dict(observation or {})
    route = raw.get("observed_route") or raw.get("route") or raw.get("url")
    origin = raw.get("observed_origin") or raw.get("origin")
    state_digest = raw.get("observed_state_digest") or raw.get("state_digest")
    if not isinstance(state_digest, str) or not state_digest.strip():
        raise R35Error("R3_5_SCHEMA_INVALID", "runtime observation requires observed_state_digest")
    observation_ref = raw.get("observation_ref") or raw.get("source_ref")
    if observation_ref is None:
        raise R35Error("R3_5_EVIDENCE_REF_REQUIRED", "runtime reconciliation requires a source-backed observation ref")
    ref = observation_ref if isinstance(observation_ref, SourceRef) else SourceRef.from_dict(observation_ref)
    expected_context = raw.get("expected_browser_context_ref")
    if expected_context is not None and not _context_equal(context, expected_context):
        raise R35Error("R3_5_BROWSER_CONTEXT_MISMATCH", "runtime observation context differs from expected context")

    node = next((item for item in graph.nodes if raw.get("page_node_ref") == item.page_node_id), None)
    if node is None:
        node = next((item for item in graph.nodes if _route_matches(item, str(route) if route is not None else None)), None)
    observed_page_key = raw.get("observed_page_key") or raw.get("page_key")
    if node is not None and observed_page_key is not None and str(observed_page_key) != node.page_key:
        return PageRuntimeReconciliation(
            graph_ref=f"{graph.graph_id}:v{graph.graph_version}",
            page_node_ref=node.page_node_id,
            browser_context_ref=context,
            observation_ref=ref,
            observed_route=str(route) if route is not None else None,
            observed_origin=str(origin) if origin is not None else None,
            observed_state_digest=state_digest,
            state="CODE_RUNTIME_CONFLICT",
            relation_checks=tuple(raw.get("relation_checks") or ()),
            reasons=("observed_page_key_differs_from_code_page",),
            reconciled_at=str(raw.get("reconciled_at") or ref.revision),
        )
    if node is None:
        runtime_only = route is not None or observed_page_key is not None
        return PageRuntimeReconciliation(
            graph_ref=f"{graph.graph_id}:v{graph.graph_version}",
            page_node_ref=None,
            browser_context_ref=context,
            observation_ref=ref,
            observed_route=str(route) if route is not None else None,
            observed_origin=str(origin) if origin is not None else None,
            observed_state_digest=state_digest,
            state="DYNAMIC_RUNTIME_ONLY" if runtime_only else "UNRESOLVED",
            relation_checks=tuple(raw.get("relation_checks") or ()),
            reasons=("runtime_target_has_no_source_backed_page_node",) if runtime_only else ("runtime_observation_has_no_route_or_page_identity",),
            reconciled_at=str(raw.get("reconciled_at") or ref.revision),
        )
    if not permission_visible or node.protection == "PERMISSION_REQUIRED" and raw.get("permission_visible") is False:
        state = "PERMISSION_HIDDEN"
        reasons = ("permission_or_runtime_visibility_policy_hides_code_page",)
    else:
        if protected or node.protection == "AUTH_REQUIRED":
            if auth_service is not None:
                if auth_context_ref is None:
                    raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "protected runtime requires an exact R3.E2 auth context ref")
                auth_context = verify_sut_auth_context(
                    auth_service,
                    mission_id=str(mission_id or raw.get("mission_id") or ""),
                    auth_context_ref=auth_context_ref,
                    expected_browser_context_ref=context,
                    observed_at=str(raw.get("observed_at") or "") or None,
                )
            if auth_context is None or not _auth_valid(auth_context):
                raise R35Error("R3_5_PAGE_RUNTIME_AUTH_REQUIRED", "protected runtime reconciliation requires valid R3.E2 auth")
            auth_value = _as_mapping(auth_context, "auth_context")
            if auth_value.get("browser_context_ref") is None:
                raise R35Error("R3_5_AUTH_CONTEXT_INVALID_OR_EXPIRED", "valid protected auth must retain its Browser context ref")
            if not _context_equal(auth_value["browser_context_ref"], context):
                raise R35Error("R3_5_BROWSER_CONTEXT_MISMATCH", "auth context and Browser context differ")
        visible = bool(raw.get("runtime_visible", True))
        state = "CODE_DEFINED_RUNTIME_VISIBLE" if visible else "CODE_DEFINED_RUNTIME_HIDDEN"
        reasons = ("code_route_and_runtime_observation_reconciled",) if visible else ("code_page_not_visible_in_runtime_observation",)
    return PageRuntimeReconciliation(
        graph_ref=f"{graph.graph_id}:v{graph.graph_version}",
        page_node_ref=node.page_node_id,
        browser_context_ref=context,
        observation_ref=ref,
        observed_route=str(route) if route is not None else None,
        observed_origin=str(origin) if origin is not None else None,
        observed_state_digest=state_digest,
        state=state,
        relation_checks=tuple(raw.get("relation_checks") or ()),
        reasons=reasons,
        reconciled_at=str(raw.get("reconciled_at") or ref.revision),
    )
