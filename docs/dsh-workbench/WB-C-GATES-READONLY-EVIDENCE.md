# C Gates read-only snapshot component evidence

Base: `3057466a5dba3b6fcb477c2ebcdaffea7533ee16`. This component is pending independent F review; it does not establish a release or field acceptance.

## Behavior and boundary

Tasks and Gates mount the same RuntimeClient and retain one Mission, R1 byte digest and explicitly displayed graph/workitems/quality read timestamps when navigating between these sections under unchanged whole-batch Scope. Refresh is manual. Gates displays raw NodeGate decisions and delivery IDs, N1–N10 raw states, explicit N10 absence, source/gap references and Evidence integrity metadata. Overall release remains HOLD and Human approval UNKNOWN_NOT_QUERIED even when N10 and its Gate are PASS and Evidence has a matching hash. No commands, approval controls, new APIs or R1 mutations are introduced.

Scope/revision/filter changes, failures and late responses clear the single snapshot and its DOM metadata. Subset filters cannot silently reuse whole-batch facts. A new browser window starts without Mission/private results. Locale switching preserves identity and the snapshot. Public readiness follows the actual ScopeClient status through a small event listener; each module retains its separate source/status boundary.

## Reproducible verification

- `node --test tests/test_dsh_workbench*.mjs`: 118 passed, including explicit missing-N10 and N10 PASS/Gate PASS/hash-only → HOLD/Human unknown.
- Real PostgreSQL (nonowner application role), loopback same-origin HTTP and Chromium browser suite: eight component tests. Runtime browser case uses persistent synthetic R1 records and an explicit fixture Host. Assertions use PostgreSQL ACL, raw R1 Node/Gate/delivery IDs, R1 digest and controlled file hash as Oracles.
- Runtime case covers missing N10, fixture recording N10 and explicit refresh, shared Tasks/Gates Mission/as-of/digest without requests on navigation, both locales, keyboard navigation, 375px width, independent browser windows, foreign Mission 403, revoked ACL 403 and Scope readiness/recovery, mixed revision and corrupt Gate delivery rejection, missing-source 503/recovery, subset filter clearing, and delayed read versus Scope switch. All UI requests remain GET; R1 bytes remain unchanged after fixture setup/updates.

Local environment: PostgreSQL socket `/tmp/dsh-pg-371f43f0`, port 55432; `WB_PG_TEST_DSN` names the disposable test database. Browser invocation uses Playwright Chromium and the existing psycopg test environment. No credentials are recorded here.

## Remaining gates

Independent F review must bind to the final exact PR HEAD. Synthetic Scope/Mission fixtures do not prove production Mission creation. Native DSH 1.18.26, Windows, bank network and offline delivery remain unverified and require transfer into the bank. This component does not implement Human approval, release approval or the complete Gates product.
