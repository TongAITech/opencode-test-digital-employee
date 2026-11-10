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

## Native fetch receiver correction after independent rejection

F PR #221, report `22b14214f8a7eb7523e45c9b2cab92e1b9ebb7ac`, rejected the previous `60f013d9` source. Its complete reproduction appendix was read and executed unchanged before the fix. Actual old-source output: native receiver control printed `TypeError: Failed to execute 'fetch' on 'Window': Illegal invocation`; the ordinary second window reached ERROR/TRUTH_SOURCE_UNAVAILABLE instead of READY (one failed test, 3.165 seconds). This retained failure invalidates default native-path qualification; previous wrapped browser passes are not transferred to that path.

The new unwrapped browser test was also executed before the correction: its first ordinary directory load reached ERROR instead of READY (one failed test, 1.654 seconds). DirectoryClient has the same demonstrated receiver defect. Both clients now call the supplied transport as an ordinary function instead of a client method. Scope's existing closure transport is unchanged. There is no global fetch replacement, Window monkey patch, server fix or R1 implementation change.

`test_native_runtime_product_browser.py` uses native fetch without any init script or replacement, checks its native function identity in both windows, and reads actual authorized project/date directories into Scope, then Tasks/Gates. Both ordinary windows must issue graph/workitems/quality GETs. Assertions cover real ACL revocation and recovery, 503 recovery, HOLD/Human unknown, raw N10/Gate/delivery/Evidence IDs, two locales, keyboard focus, 375px, explicit manual refresh, no writes and no legacy API. Existing wrapped delayed-response race tests remain separate. Node transport tests assert an undefined receiver for both clients.

After correction: the original F appendix passed its product reads in 3.934 seconds. Its deliberately invalid receiver control still prints the expected native TypeError; that control is a reproduction diagnostic, not a product pass. Final Node suite: 120 passed, zero skips. Browser suite: all nine passed in 41.248 seconds (original eight plus the separate unwrapped native case); the final native-function identity/second-window route assertions additionally passed a targeted rerun in 6.065 seconds. All results remain component-only and require independent F review of the newly frozen exact HEAD.
