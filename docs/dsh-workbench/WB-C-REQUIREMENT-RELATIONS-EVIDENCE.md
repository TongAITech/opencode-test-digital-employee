# C04 requirement relations: read-only component evidence

Base: `2b94d2361fbc92cb56ad06cc8046e4474b86ca12`, the local A integration of independently rechecked Gates/native fetch. Pending independent F exact-HEAD review.

## Implemented boundary

The existing Requirements section now renders a synchronous projection of the one existing ScopeClient state, with no new endpoint, network consumer, cache or business persistence. Only a complete validated READY Scope supplies rows. Every displayed relation keeps its original requirement ID, version ID, exact SST (or explicit UNSPLIT/pending split), BRV source reference/revision and BRVS source reference/revision. Shared versions do not share SST automatically. Relation sources are explicitly labelled as relations, not unqueried requirement document sources. The page does not claim requirement text, test obligations or coverage completion.

Global requirement/version/SST filters intersect actual rows. Invalid/stale selected identities clear the projection; incompatible filters show no valid match, never a zero-requirement success claim. Unready/loading/error/Scope changes clear rows and Scope/revision DOM metadata. Each render derives from the current Scope and selection, so no view-owned results can outlive ScopeClient. Project/batch/date, relation revision and access revision are displayed. Leaving the section removes its private rendered contents; returning derives from the same currently loaded Scope.

Six pages and ten sections remain unchanged. Both locales use textContent, not HTML interpretation. No new controls, POSTs, legacy API reads, R1 writes or localStorage business data are added.

## Validation

Commands from this worktree:

- `node --test tests/test_dsh_workbench*.mjs`
- `PYTHONPATH="$PWD/../pg-environment-venv/lib/python3.9/site-packages" WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' python3 -m unittest discover -s tests/browser -p 'test*.py'`

Final local result: Node **124 passed**, zero skips (0.572 seconds); browser **10 passed**, zero skips (46.544 seconds), including the previous nine cases and the new requirement-relation case.

The new browser case uses a real disposable PostgreSQL database, nonowner application role, explicit fixture Host, same-origin HTTP and ordinary native Chromium fetch with no replacement/init script. Its Oracle is a direct SQL join of BRV/BRVS and verified relation-source tables, not screenshots or model answers. The 101-row fixture forces two Scope pages and includes two requirements sharing V1 with different SSTs, 99 UNSPLIT relations and a literal HTML-like source reference.

Checks: every SQL tuple and its exact source refs/revisions appears; no Cartesian SST duplication; last-page source remains present; HTML-looking ref stays literal with no injected element/execution; multi-select and downstream intersection; locale preserves identity with no request; 375px and keyboard focus; navigation between existing sections; real page-two response held via an explicit transport-negative route (no fetch replacement), first-page rows hidden while loading, then Scope edit and delayed delivery cannot restore them; real ACL403 and missing-service503 clear/recover; rescheduled batch invalidates the old date and recovers only with the current date. Requests remain GET under workbench v1; business data is absent from saved settings.

The existing ScopeClient tests continue to qualify source/revision drift, incomplete pagination, duplicate rows, foreign scope and late response rejection; this view does not bypass or replace those checks.

## Acceptance limits

This is one C04 read-only association slice, not complete requirement management, formal obligation creation or end-to-end test coverage. Synthetic fixture relation provisioning does not establish production data creation or runtime Mission binding. Native DSH 1.18.26, Windows, bank-network and offline acceptance still require the bank environment. No release acceptance is inferred. Only A may integrate; F must independently review the final exact source.
