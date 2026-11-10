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
- E owns the R1 read-only projection and must use a **scope-first** read: resolve only the selected Mission identity, require explicit R1 `project_id` and `batch_id` to match the B06-authorized scope, and only then query Tasks/Executions/Evidence. The unscoped `mission_overview(mission_id)` is prohibited for this seam. Missing or mismatched legacy bindings remain `R1_MISSION_SCOPE_UNRESOLVED`; `release_id`, names, or labels must never be treated as a batch ID.
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
1. Call the R1 `mission_overview_scoped(project_id, batch_id, mission_id)` port only.
2. Resolve the minimal Mission identity first and require explicit `mission_id`, `project_id`, and `batch_id` to match. A missing or cross-scope identity is rejected before any related query.
3. Only after the identity match, load Tasks/Executions/Evidence and require each row to retain the same `mission_id`; reject duplicate IDs or malformed collections.
4. Never fall back to the old `mission_overview(mission_id)` method, which reads related details before E can check scope.
5. Preserve B06 source refs and append the R1 projection source ref; never replace one provenance domain with the other.
6. Keep Attempt result `UNKNOWN_UNQUALIFIED`, Evidence `UNVERIFIED_NO_CONTENT_READ`, NodeGate `UNKNOWN`, and release decision `HOLD`. A declared hash is not a verified hash until bytes are read and recomputed.

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

## 6. B confirm + full pagination read isolation

B confirmed the exact `source_refs` and `next_page_cursor` semantics on E PR #96 and B PR #95. The consumer now exposes:
- `collect_authorized_b06_pages(page_fetcher, project_id, batch_id, page_size, max_pages)`: caller supplies a **Host-bound B06 port**, accepting (project_id, batch_id, page_size, page_cursor); the port must authorize each request, including resumed pages. No raw client principal argument is accepted.
- `r1_preview_after_full_b06_scope(page_fetcher, legacy_admin, project_id, batch_id, mission_id)`: requires successful consumption of **all** pages and stable project/batch/date/relation_revision/access_scope_revision before any R1 read.
- Each next cursor must be new; cross-page row identities must be unique; an UNSPLIT parent cannot become SPLIT within a single logical snapshot; source references are preserved and de-duplicated across pages; page-size and page-limit exhaustion are explicit failures.
- B remains responsible for actual cursor signature and DB snapshot isolation; this E adapter cannot cryptographically establish cursor authenticity. E preserves fail-closed statuses even when the complete B06 projection fixture succeeds.

The new `tests/test_dsh_workbench_e_pages.py` exercises the positive and negative page-chain protocol. No real Host, R1 production lineage, migration, HTTP server, command, SSE, or browser execution has been integrated by these fixture tests.

## 7. E source revision fence across B06 pages (2026-11-10)

The first consumer implementation checked that each row includes a verified requirement-version source link and that relation/access scope revisions remain stable across pages. This **did not yet ensure** that two SPLIT rows for the *same* `(requirement_id, system_version_id)` across different pages refer to one consistent authoritative BRV source identity/revision.

The consumer now captures `(source_link_ref, source_revision)` for each `(requirement_id, system_version_id)` across the entire B06 response chain. If another SST row for the same parent has a different tuple, it fails with `B06_REQUIREMENT_VERSION_SOURCE_DRIFT` **before any R1 mission overview read**. This applies within a page and across pages. Two different system versions are intentionally different parents, so re-used raw SST IDs or independent revisions across versions remain legal.

The E protocol tests cover stable same-parent multi-SST joins, both reference and revision drift, same-page contradictions, and valid cross-version independent provenance. This is a consumer-side defensive check **in addition to**, not instead of, B06 PostgreSQL snapshot isolation and source-trace FK enforcement. It does not authenticate the originating source or establish a bank Host ACL. The release decision stays `HOLD` and E01 remains `BLOCKED_DEPENDENCY_B06`.

## 8. F #111 P1: R1 Mission scope must precede related-detail reads (2026-11-10)

F independently reviewed E HEAD `917f597d11daa1ae0bfc0caa07066bd45ad64ffa` and accepted the B06 BRV source-revision fence, but found that the E consumer still called legacy `mission_overview(mission_id)` before `r1_preview` checked Mission `project_id/batch_id`. The old AdminProjection queried the Mission and then Tasks/Executions/Evidence without scope filtering. A rejected cross-project request could therefore cause related details to be read before rejection.

**Remediation:**
- E now requires `mission_overview_scoped(project_id, batch_id, mission_id)`; no unscoped fallback is permitted.
- The legacy in-process AdminProjection performs a minimal `truth.get("rc7_mission", mission_id)` identity lookup first. It compares explicit Mission `project_id` and `batch_id` against the authorized B06 scope; missing, unbound, or mismatched identities all fail with `R1_MISSION_SCOPE_UNRESOLVED` without disclosing whether another-scope Mission exists.
- Only after the identity matches does it query the selected Mission's Tasks, Executions, and Evidence. It returns only the three identity fields required by E, not the complete Mission row. It intentionally does not call `refresh()`, because that rebuilds the whole event projection before scope validation. It uses `TruthRuntime.query("rc7_mission", mission_id=...)` for the identity-only lookup; the inherited runtime has no `get()` API.
- Both E read seams (single-scope prototype and complete paginated consumer) call the same scope-first helper. A legacy object exposing only `mission_overview(mission_id)` is rejected with `R1_SCOPED_READ_UNAVAILABLE`; the unsafe method is never invoked.
- Negative tests cover cross-project, cross-batch, missing legacy bindings, old unscoped-only projection, and actual inherited RC7 AdminProjection. They assert zero related Tasks/Executions/Evidence queries before rejection. Positive fixtures assert the identity check happens before related reads.

**Limit:** inherited RC7 `Mission` currently has no canonical `project_id/batch_id` fields. Such old records now fail closed and cannot be previewed until an independently governed migration or authoritative scope binding exists. This method is a legacy in-process scope guard, not production PostgreSQL row-level security or a substitute for DSH Host principal authorization. B06 still must authorize the project/batch using the Host-bound principal; production R1 must provide a transactional scope-filtered identity/detail read. E01 remains `BLOCKED_DEPENDENCY_B06` / `IMPLEMENTATION_QA_NOT_RUN`.
