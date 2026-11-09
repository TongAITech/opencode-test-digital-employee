# WB-E01 — B06 Consumer Protocol and R1 Read-Only Projection

Status: **PRE_IMPLEMENTATION_CONSUMER_CONTRACT / B06_NOT_IMPLEMENTED / E01_QA_NOT_RUN**

This is an E-owned consumer-side protocol note derived from:
- `docs/dsh-workbench/02-BUSINESS-DOMAIN-CONTRACT.md`
- `docs/dsh-workbench/05-RC72-INTEGRATION-CONTRACT.md`
- `docs/dsh-workbench/06-API-AND-EVENT-CONTRACT.md`
- `docs/dsh-workbench/WB-B-A03-DESIGN-SIGNOFF.md`
- `docs/dsh-workbench/WB-E-A03-DESIGN-SIGNOFF.md`

It does not implement B06, authorize a principal, add an HTTP endpoint, or qualify E01.

## 1. Ownership boundary

- DSH Host/D supplies the authenticated server-side principal. Browser JSON, prompt text, UI state, and request-body `principal`/`authorization` fields are never identity sources. E invokes a B06 port bound to that server-side request context; the E adapter accepts project+batch only and does not accept/pass a raw principal argument.
- B06 owns the project + stable batch + verified Requirement/SystemVersion/SST relation query. Its request is scoped by project/batch (or project/business date) plus explicit ID filters and pagination. It is **not** a Mission authorization endpoint and must not be asked to infer Mission membership.
- E owns the R1 read-only projection and must verify the selected Mission against explicit R1 `project_id` and `batch_id` bindings after B06 has authorized the project/batch. Missing legacy bindings remain `R1_MISSION_SCOPE_UNRESOLVED`; `release_id`, names, or labels must never be treated as a batch ID.
- E calls the host-bound B06 port first. On 401/403/404/409/422/503 or malformed/unverified scope, E must not query R1. The adapter never calls `dispatch_post`, `append_atomic`, or any R1 write API.

## 2. B06 response fields consumed by E

The E adapter expects the signed B06 response to carry:
- `project_id`, `batch_id`, canonical `release_date` (`YYYY-MM-DD`), positive `relation_revision`, positive `access_scope_revision`;
- non-empty `records`, each an actual BRV/BRVS relation (including an explicit `UNSPLIT` row when BRV exists without SST);
- `source_refs`, a unique list of non-empty source references that includes each row's `source_verified_requirement_version.source_link_ref` and, for split rows, `source_verified_link.source_link_ref`;
- per relation, a verified requirement-version link with `source_link_ref` + `source_revision`; split SST rows additionally have `source_link_ref` + `verified_source_revision`;
- optional `warnings`, `gap_indicators`, and `next_page_cursor`.

No records is not an empty-success response: when an explicitly selected relation does not exist, B06 must return the contract's 422 `ILLEGAL_ASSOCIATION`. A legal BRV without an SST is represented as `UNSPLIT`, not as an empty relation set.

If `next_page_cursor` is present and non-null, the page is incomplete and E must preserve the cursor and expose a pagination gap. If pagination metadata is absent, completeness is unknown and E must not claim a complete scope. This adapter is a protocol validator, not a replacement for B06's signed cursor or page consistency implementation.

**B review requested:** confirm that `source_refs` is a unique string list containing all per-row verified link refs, and confirm the exact cursor field/shape before B06 implementation is frozen. E does not silently redefine B's SQL schema or source identity fields.

## 3. R1 read-only mapping

After B06 succeeds:
1. Read the exact Mission overview from the in-process R1 projection.
2. Require `mission_id`, `project_id`, and `batch_id` to match the selected Scope.
3. Require each Task/Execution/Evidence row to retain the same `mission_id`; reject duplicate IDs or malformed collections.
4. Preserve B06 source refs and append the R1 projection source ref; never replace one provenance domain with the other.
5. Keep Attempt result `UNKNOWN_UNQUALIFIED`, Evidence `UNVERIFIED_NO_CONTENT_READ`, NodeGate `UNKNOWN`, and release decision `HOLD`. A declared hash is not a verified hash until bytes are read and recomputed.

The inherited R1 `Mission` currently carries `release_id`, not canonical project/batch fields. Therefore old Mission records without explicit, independently migrated bindings are rejected. No guess or backfill is performed by E.

## 4. Positive and negative test contract

The pre-B06 tests cover:
- project/batch equality, valid business date, positive relation/access revisions;
- source-link presence and membership in top-level source refs;
- no empty successful relation result, valid UNSPLIT vs invented SST;
- duplicate relation/source-ref rejection;
- same raw SST ID across system versions remains distinct;
- Mission ownership checked from explicit R1 binding, not a B06 mission allow-list;
- B06 denial precedes any R1 read;
- pagination cursor preservation and incomplete-page HOLD;
- old Admin GET/POST route absence and no R1 event-stream mutation.

Run: `python -m unittest discover -s tests -p 'test_dsh_workbench_e_*.py' -v`

These are protocol/fixture tests only. They do not exercise PostgreSQL, real B06 HTTP, DSH Host authentication, R1 production data, persisted commands, SSE, NodeGate, Agent Teams, or field execution.

## 5. Admission rule

`WB-E01=BLOCKED_DEPENDENCY_B06` until B provides the real PostgreSQL-backed B06 API, trusted DSH Host principal integration is available, and source-verified joins/ACL/error semantics/pagination are verified against real data. E01 QA requires real R1 read-only mapping and negative tests on the same integrated source SHA. E02–E06 remain unstarted until W0 and their explicit dependencies are accepted. E07 remains optional and must share the exclusive BrowserLease manager with BSK if later admitted.

No production route, PASS, Evidence, Defect, NodeGate, command, or bank package is created by this note.
