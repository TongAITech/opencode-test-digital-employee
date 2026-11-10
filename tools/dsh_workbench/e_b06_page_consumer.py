"""Fail-closed pre-B06 multipage Scope consumer with no production authority.

The injected page_fetcher MUST be host-bound and backed by B06's real
authorization, signed page cursor and source-verified BRV/BRVS join.
This module implements only the consumer protocol and cross-page safeguards.
It is not a B06 database/service, HTTP route, Host login, R1 transaction,
execution outcome, or product QA evidence.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Dict, Mapping, Optional

from .e_contract_oracle import ContractRejection
from .e_readonly_scope_prototype import (
    normalize_b06_scope, r1_preview, read_scoped_r1_mission_overview,
)


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ContractRejection(code)


def collect_authorized_b06_pages(
    page_fetcher: Callable[[str, str, int, Optional[str]], Mapping[str, Any]],
    *, project_id: str, batch_id: str, page_size: int = 100,
    max_pages: int = 32,
) -> Dict[str, Any]:
    """Consume the entire authorized B06 cursor chain or reject.

    B06 authenticates and authorizes each page, signs cursor scope, and owns
    server-side snapshot semantics. This consumer additionally verifies stable
    project/batch/date/revisions and complete provenance across pages. It never
    returns a partial page as an allegedly complete Scope.
    """
    _require(callable(page_fetcher), "SCOPE_SOURCE_UNAVAILABLE")
    _require(isinstance(project_id, str) and bool(project_id.strip())
             and isinstance(batch_id, str) and bool(batch_id.strip()),
             "INVALID_SCOPE")
    _require(type(page_size) is int and 1 <= page_size <= 200,
             "INVALID_PAGE_SIZE")
    _require(type(max_pages) is int and 1 <= max_pages <= 128,
             "INVALID_PAGE_LIMIT")
    cursor = None
    used_cursors = set()
    first = None
    records = []
    refs = []
    ref_seen = set()
    warnings = []
    gaps = []
    seen_relations = set()
    split_state_by_parent = {}
    # One authoritative BRV source identity/revision for the SAME
    # (requirement, system_version) across all SST rows and pages.
    # Distinct system versions must remain distinct even with same raw SST ID.
    source_by_parent = {}
    for _page_number in range(max_pages):
        page = page_fetcher(project_id, batch_id, page_size, cursor)
        _require(isinstance(page, Mapping), "SCOPE_SOURCE_UNAVAILABLE")
        # B06's signed cursor is mandatory even when this is the first/last page.
        _require("next_page_cursor" in page, "B06_PAGINATION_UNAVAILABLE")
        normalized = normalize_b06_scope(
            page, project_id=project_id, batch_id=batch_id)
        _require(len(normalized["records"]) <= page_size,
                 "B06_PAGE_SIZE_EXCEEDED")
        if first is None:
            first = {
                "project_id": normalized["project_id"],
                "batch_id": normalized["batch_id"],
                "release_date": normalized["release_date"],
                "relation_revision": normalized["relation_revision"],
                "access_scope_revision": normalized["access_scope_revision"],
            }
        else:
            _require(normalized["release_date"] == first["release_date"],
                     "B06_BUSINESS_DATE_CHANGED")
            _require(normalized["relation_revision"] ==
                     first["relation_revision"], "B06_RELATION_REVISION_CHANGED")
            _require(normalized["access_scope_revision"] ==
                     first["access_scope_revision"], "B06_ACCESS_REVISION_CHANGED")
        for row, raw_row in zip(normalized["records"], page["records"]):
            parent = (row["requirement_id"], row["system_version_id"])
            source = raw_row["source_verified_requirement_version"]
            identity = (source["source_link_ref"], source["source_revision"])
            previous_source = source_by_parent.get(parent)
            _require(previous_source is None or previous_source == identity,
                     "B06_REQUIREMENT_VERSION_SOURCE_DRIFT")
            source_by_parent[parent] = identity
            key = parent + (row["sst_id"],)
            _require(key not in seen_relations,
                     "B06_DUPLICATE_RELATION_ACROSS_PAGES")
            seen_relations.add(key)
            mode = row["split_state"]
            previous_mode = split_state_by_parent.get(parent)
            _require(previous_mode is None or previous_mode == mode,
                     "B06_SPLIT_STATE_CONFLICT")
            split_state_by_parent[parent] = mode
        # Preserve B06 raw verified relation maps. They are re-normalized
        # before R1 reads, not reconstructed from label/SST string guesses.
        records.extend(deepcopy(list(page["records"])))
        for ref in normalized["source_refs"]:
            if ref not in ref_seen:
                ref_seen.add(ref)
                refs.append(ref)
        for value in normalized["warnings"]:
            if value not in warnings:
                warnings.append(value)
        for value in normalized["gap_indicators"]:
            if value not in gaps:
                gaps.append(value)
        next_cursor = normalized["next_page_cursor"]
        if next_cursor is None:
            _require(first is not None and bool(records),
                     "ILLEGAL_ASSOCIATION")
            return {
                **first,
                "source_refs": refs,
                "records": records,
                "warnings": warnings,
                "gap_indicators": gaps,
                "next_page_cursor": None,
            }
        _require(next_cursor != cursor and next_cursor not in used_cursors,
                 "B06_CURSOR_CYCLE")
        used_cursors.add(next_cursor)
        cursor = next_cursor
    raise ContractRejection("B06_PAGE_LIMIT_REACHED")


def r1_preview_after_full_b06_scope(
    page_fetcher: Callable[[str, str, int, Optional[str]], Mapping[str, Any]],
    legacy_admin: Any, *, project_id: str, batch_id: str, mission_id: str,
    page_size: int = 100, max_pages: int = 32,
) -> Dict[str, Any]:
    """Only read R1 AFTER a whole authorized and revision-stable B06 Scope.

    The inherited R1 Mission needs explicit project/batch bindings. Missing
    legacy fields are refused, not inferred from a ReleaseBatch/release_id.
    """
    _require(isinstance(mission_id, str) and bool(mission_id.strip()),
             "INVALID_SCOPE")
    scope = collect_authorized_b06_pages(
        page_fetcher, project_id=project_id, batch_id=batch_id,
        page_size=page_size, max_pages=max_pages)
    projection = getattr(legacy_admin, "projection", None)
    overview = read_scoped_r1_mission_overview(
        projection, project_id=project_id, batch_id=batch_id,
        mission_id=mission_id)
    return r1_preview(scope, overview, project_id=project_id,
                      batch_id=batch_id, mission_id=mission_id)
