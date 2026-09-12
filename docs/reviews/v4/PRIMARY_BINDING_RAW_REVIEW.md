# Primary binding independent raw-source review

**CURRENT DECISION = PROCEED_C1_REMAINING; INITIAL P1 CLOSED BY SOURCE AND NEGATIVE RECHECK BELOW.** Initial review recorded one concrete P1; no P0 or v7 global invariant contradiction found. This is a C1 prerequisite source review, not C2 pressure/successor qualification and not another Resume checkpoint. Reviewer changed no product source.

Reviewed current new `primary_sessions.py` and canonical registration, existing root compatibility implementation, and relevant Host provider behavior. Exact source fingerprint is recorded in PRIMARY_BINDING_REVIEW_OBSERVATION.json.

## Supported design

The additive PRIMARY_INTERACTION root uses the existing R1 transactions/replay. It never creates a core Mission or Session; actual Host IDs are root-owned binding fields. CREATE binds workspace-derived logical identity; REQUEST owns a deterministic provision identity; BIND requires current REQUESTED epoch and exact directory digest; FENCE prevents old Session reuse. BIND lease duration is bounded to eight hours and current() rejects expired or non-current bindings. Provisioning can recover a uniquely matching actual Host Session after a create-response crash. Replay identity uses stored text and does not resolve paths on the replay machine.

The registry change correctly activates the existing unknown-root guard. An independent new-root→composition-without-Primary-owner check returned ROOT_OWNER_UNSUPPORTED. The existing frozen Mission bytes/fingerprint/hash test was rerun once because registration changed: **1 test OK / 0.211s**. No closed General file suite was unnecessarily repeated.

## P1 PRIMARY-HOST-REALM-MISSING

R1 bindings contain Session ID and workspace directory only; they do not identify the OpenCode Host authority that issued the Session. `ensure_current` accepts an existing BOUND lease if the current provider lists any same-ID/same-directory Session. It does not prove that the provider is the one that created the binding. `current()` likewise has no Host identity input/check.

Independent two-Host inventory fixture (`primary-binding-independent-check.json`) uses Host A and Host B with deliberately colliding local Session IDs and the same directory. Host B's Session has an unrelated title. Calling owner B.ensure_current returns **the exact old Host A binding/epoch/lease, with zero new events**. This is a labeled protocol fixture, not a claim to have reproduced a collision in real OpenCode. It demonstrates that the binding key is incomplete whenever Host endpoints/instances change or session stores are copied/restored.

Minimum repair:

- Include a Runtime-derived OpenCode Host realm/instance identity in REQUEST/BIND and current caller admission, obtained from trusted launcher/provider configuration or verified Host instance metadata. This identifies the OpenCode Host, **not the LLM model/provider**.
- A changed or unknown realm must fail closed/fence before granting a current lease; recovery may match the provision token only inside its recorded realm. No model-supplied realm field may authorize it.
- Define dynamic-port/restart semantics explicitly. Conservative endpoint change→new binding is safer than silently claiming continuity. If stable identity spans restarts, it needs actual evidence; do not derive it merely from a Session title.
- Add two-Host same-ID negative, same-Host retry/restart positive, change-between-launch-and-tool-call negative and no secret values in stored identity. Keep stale caller rejection before domain mutation.

## Remaining verification obligations for this new component

The module is not yet connected to actual launcher/ToolContext in the reviewed source. Positive actual ownership and negative old caller/model self-registration tests are still needed after wiring. Test crash after REQUEST, actual creation-before-BIND, FENCE-before-next REQUEST and BIND-before-operational pointer; duplicate launches must converge on one current binding. Delayed BIND from a prior epoch must not modify current state. Lease exact deadline, malformed root/version, old-owner write/rebuild preservation and canonical replay should be explicit.

Budget/shape checks should be shared between live command admission and reducer; currently the command's 16KiB event check is not repeated in reducer. This is defensive replay consistency, not a demonstrated external execution bypass. `record` is a trusted in-process seam; actor strings alone are not a remote permission mechanism, so model tools must never expose this creation/binding port.

Not findings against this C1 prerequisite: absence of pressure/poison flags, compact, automatic clean successor and TUI follow. They remain C2 OPEN and must not be inferred from ensure_current's ownership lookup. Architecture change is not required to repair the Host identity gap.

TASK_DIFFICULTY = HARD. REASONING_RECOMMENDATION = HIGH for identity/lease/concurrency review; ordinary wiring may proceed without user confirmation.

## Incremental recheck of latest Host-realm and entry wiring

**Primary binding prerequisite: no remaining demonstrated P0/P1 in this review scope. Continue construction without user confirmation.** This is an additive CC-01 component implementation, with no identified v7 global invariant change. Full C1 and C2 remain OPEN.

The Runtime now derives `host_realm` from trusted provider endpoint plus workspace; REQUEST, BIND and current caller admission check it. Credentials cannot enter the accepted endpoint. A changed endpoint conservatively fences the old epoch. BIND reuse checks `(host_realm, session_id)`, avoiding a permanent failure when an empty new Host generates the same local Session ID. REQUESTED bindings may be fenced only through the same trusted owner, and fence time cannot precede the request. Thus a Host change after create-before-BIND does not reinterpret the prior request in a different realm. This establishes endpoint-scoped authority, not proof of persistent server-instance identity across endpoint reuse.

Independent `primary-binding-realm-recheck.json`: two isolated Host protocol fixtures with the same local Session ID produced epoch 1 then epoch 2, changed realm, FENCED predecessor, BOUND successor; old Host caller was denied with PRIMARY_HOST_REALM_MISMATCH. `primary-binding-boundary-recheck.json`: actual temporary R1 storage with a create-before-BIND fault, changed Host and delayed old BIND returned PRIMARY_STALE_EPOCH with no added event; the old REQUESTED record was FENCED. At the exact expiry timestamp current() returned PRIMARY_LEASE_EXPIRED. Projection verification and rebuild both passed. These are component fixtures, not live Host evidence.

Latest `test_primary_sessions.py`: **11 tests / OK / 2.025s** independently run. Covers current reuse/replay, old caller rejection, create-before-bind recovery, changed realm, new Host local-ID reuse, pending Host change, expired lease, wrong directory, model actor denial, old registry denial, actual product-entry protocol verification and zero-Mission chat. The prior nine-test run also passed before the last two cases landed.

Source review confirms launcher now provisions through PrimarySessionOwner and treats its JSON pointer as operational output. The Director product entry holds the shared Runtime coordination lock across current binding, actual Host tool-part verification and domain dispatch. Verification requires actual assistant role/agent, exact Session/message/call identity, unique call part, running tool state and exact action/payload; ambiguous duplicate call IDs are rejected before input filtering. Model parameters expose no Primary creation or lease-grant route. Shared transition budget validation now also covers replay.

Remaining qualification obligations: committed-source real Host/model admission evidence, integration into subsequent Mission controls/update/HumanGate owners, and C2 pressure/poison/clean successor/launcher lifecycle work. The reviewed new probe script is correctly labeled component-only and must actually run before a real Host PASS is asserted. Existing launcher finalization still stops its control loop; this is retained C2/C3 product work, not closed by Primary binding. New authority wiring must retain old frozen Mission bytes and previously passed General file/R1 results.
