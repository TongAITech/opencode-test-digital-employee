# F independent M1 governed-root rename design review

Reviewed exact documents:

- D PR #211: `1e1a75ff6c49cfaf36a6f36f3bdde1e047cf77d2`, WB-D-PROJECT-METADATA-BOARD-INCREMENT and its catalog/inventory evidence.
- B PR #230: `a21b82fe805926a22b5d90babec5670dd912c6aa`, WB-B-PROJECT-METADATA-M1-NAMESPACE-CANDIDATE-20261111.
- A decision root commit: `9a41b1456ceed0a0efb66ab662e1d3e3dff136aa`, WB-A-PROJECT-METADATA-M1-DECISION-20261111.

**M1_GOVERNED_ROOT_RENAME_DESIGN_ACCEPTED_FOR_ISOLATED_IMPLEMENTATION.** No design P0/P1 found in this bounded combination. D's broad staged proposal is narrowed for M1 by B's candidate and A's explicit product decisions. F does not sign D/E/C responsibilities or declare SQL, product functionality, production governance, Host or field acceptance. Those implementations do not yet exist.

## Actual dependencies checked

Current wb.project has stable project_id/name/access_scope_revision; no metadata_revision, namespace/type/parent or name uniqueness. Runtime project writes are not currently granted. Metadata GET/PATCH is absent. D's isolated PG catalog is correctly labeled prior observation at source199a3163, not current rename QA. F read the catalog/inventory and current migration, directory, business request-key and source-profile implementations, without copying their old PASS to this new design.

Current migrate only permits1–7 and scans the continuous prefix. Therefore009 cannot be executed by merely naming an SQL file. A explicitly chooses a reviewed dependency manifest/runner change:009 depends001–007 and not008;008 stays E's formal binding slot. Implementation must retain checksum/advisory-lock/atomicity and safe rollback semantics; no empty008, falsified ledger prefix or checksum skip. Real009 empty up/down/up and nonempty-history refusal are implementation gates, not design evidence already satisfied.

Current Directory hashes authorized project_id/name/access_scope_revision records. A→B→A can restore that digest: metadata_revision must enter the stable project-directory snapshot and versioned wire to prevent ABA old-cursor reuse. This is a real needed change, not a present capability. Batch directory, DATE/relation/access revisions and legitimate ten-section Scope do not change merely because the project display name changes.

Current Scope profile is pinned `dsh.scope-source.project-only.pg17.001-007.v2` plus content hash. New columns, grants, policies and triggers require a separately reviewed profile/template. The design explicitly requires UNQUALIFIED until approved; no dynamic catalog learning, ID reuse with edited profile, or privilege relaxation. This review does not authorize a new profile's contents before exact SQL exists.

## Governance and complete duplicate-name denominator

M1 permits only already-governed root PROJECT renames inside a NAMING_ACTIVE namespace. The namespace comes from an approved server administrative source with source_ref/revision/hash, complete project/kind/parent membership and explicit exclusion grounds for other legacy rows. Unknown potential members or historical invalid/duplicate names keep the domain on GOVERNANCE_HOLD. Unknown legacy stays readable according to old ACL, while metadata writes reject METADATA_NOT_GOVERNED. Ordinary writer cannot self-bind or activate a namespace, choose private per-project namespaces, redefine type/parent or resolve hidden duplicates by moving domains.

The server/DB byte-key uniqueness denominator includes invisible members. Approved product choice allows a generic NAME_UNAVAILABLE bit, but no other project's identity/member/parent details or arbitrary namespace lookup. project_id remains the join identity; project.name is the one current text fact and binding.key is its constrained canonical byte representation, not a second independently editable name. Administration governs conflicts before activation; no smallest-ID/visible-list silent rename.

A freezes project-name/utf8-exact-v1: reject invalid UTF8/surrogates/C0/DEL, trim only edgeU+0020,1–128 scalar values/≤512 UTF8 bytes, case/normalization/other Unicode whitespace exact. Therefore A and a, composed/decomposed accents remain distinct while edge ASCII-space variants collide. Server canonicalization, DB consistency constraints and bytea unique indexes must all agree; client messaging explains the unusual but deliberate whitespace policy. No implementation of those checks has passed yet.

## Authorization, CAS, receipts and recovery

Existing read identity does not imply mutation. M1 uses trusted server principal, current Host mutation and CSRF/Origin proof, original subject write-context, current project can_write and active server governance policy for existing-project rename. It grants no project.create, iteration.create, membership/parent management, global ACL or native directory/session capability. Runtime must not use migration-owner/BYPASS privileges. New SQL must prove restricted name/metaRev/key maintenance with mandatory history/audit/receipt/outbox and no direct bypass; ACL-trigger-only access revision changes must remain viable.

New-body field allowlist, exact decimal revision strings bounded to bigint, unknown/duplicate JSON keys and size/type rejection are specified. CAS is metadata and access revision, never floating-point approximated. No-op normalized name returns a durable NO_CHANGE receipt and operation audit without a fake change history/metaRev/event. Ordinary rename updates name/key/revision/history/audit/receipt/project-domain outbox atomically, no R1/external side effect and no invented Mission PREPARE.

K=(project_id,principal,request_id) stays in the shared request namespace with action/full canonical payload digest; other action or payload sameK conflicts. After renewed authorization/context verification, committed sameK/digest returns the **complete original receipt before current CAS**, even if another rename has advanced metadata. UI refreshes current state instead of overwriting it with that historical response. Receipt must encode its applied revision/history status. Single-transaction failure is full rollback; commit-response loss is original K/body/actor reconciliation, not a new request or changed CAS. Different subject, revoked authority, unreadable DB/key/context failures HOLD; no cached absence proof or replacement token grants replay rights.

Namespace→project→binding→request-result locking and administrative operations' compatible ordering remain a concrete SQL/concurrency acceptance gate. Namespace and binding are reread after locks; a moved domain must rollback/retry, not proceed under an old lock. The earlier D generic sketch is not an alternative lock order to implement alongside B's refined protocol. Actual two-connection CAS, hidden duplicate race, revoke/domain-stop race, faults at key/history/outbox and restart/connection-pool behavior must be tested on exact PostgreSQL implementation.

## Additional cross-action lock-order implementation condition

A supplied a concrete source-level concurrency concern during review. F checked BusinessStore._claim: it inserts the shared request_log key before later business locks; AssetStore.mutate calls it before locking the batch. request_log has a project FK. B's proposed metadata order instead acquires project FOR UPDATE before claiming that same K. A concurrent asset action and metadata action with the same project/principal/request_id may therefore interact through speculative/unique-key waiting and the FK parent KEY SHARE lock in the opposite order. **No deadlock was reproduced in this review**, and no new permission/concurrency attack experiment was run; this is a source-supported design risk requiring SQL proof, not a fabricated defect result.

Before freezing SQL, B must resolve the lock compatibility/order explicitly across existing claim-first actions and the new metadata action. A suggested project FOR NO KEY UPDATE (when no key changes) or a consistent claim/parent order are candidate approaches, not automatically accepted fixes. The exact chosen SQL must have real two-connection same-K cross-action tests, different-K controls, rollback/retry/no-prefix checks and ACL/governance ordering tests. Merely demonstrating two concurrent metadata renames is insufficient. This condition does not block pure name codec or isolated candidate implementation; unresolved SQL cannot be signed for runtime deployment. It strengthens the existing requirement for reviewed lock order rather than silently changing D/B/A contracts in this F report.

## Limited actual regression in this review

No new permission/attack experiment was run. Only existing necessary tests were executed from the isolated worktree rooted at9a41b145:

- `node --test tests/test_dsh_workbench_directory_client.mjs`: **11/11**,0 skipped,0.243 seconds.
- `PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m pytest tests/test_dsh_workbench_b_directory_postgres.py tests/test_dsh_workbench_scope_profile_artifact.py -q`: **18/18**,0 skipped,5.49 seconds. Real existing isolated PostgreSQL directory fixtures and existing pinned-profile tests, including inherited collected tests. No new metadata schema, rename, uniqueness,009 migration or ABA implementation was exercised by those tests.

Two initial source lookups guessed nonexistent test/profile filenames; F then used the actual file inventory and read the correct sources. These lookup errors are not tests or successful verification.

## Implementation admission and outstanding gates

B may implement the isolated pure name codec,009 dependency runner/schema candidate, restricted transaction/CAS/receipt path and real-PG tests; C may implement the corresponding same-origin bilingual read/edit interaction after its wire review. Real Host unavailability does not block those software components. A fixture administrative source can demonstrate component behavior but cannot certify production membership/governance or actual Host authorization.

Before deployment/feature acceptance, D/E/C precise scope signatures and F exact implementation QA still apply, including genuine reviewed SQL/profile, independent source governance, no-prefix rollback, metadata Directory ABA and full denominator tests. No current P03-01/P06-02 feature is closed by this design review. M2 create/iteration/membership, M3 batch-plan stage and M4 formal release/SSE remain separate. Card identity is(project_id,batch_id); current E02 HOLD/Human UNKNOWN cannot become RELEASED through this metadata work. No native DSH, Windows/offline or final delivery PASS is given. F wrote only this report, not implementation or08/09/10, and did not merge.
