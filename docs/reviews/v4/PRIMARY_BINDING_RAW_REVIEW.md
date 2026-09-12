# Primary binding independent raw-source review

**DECISION = REPAIR_HOST_AUTHORITY_IDENTITY_BEFORE_CALLER_ADMISSION.** One concrete P1 below; no P0 or v7 global invariant contradiction found. This is a C1 prerequisite source review, not C2 pressure/successor qualification and not another Resume checkpoint. Reviewer changed no product source.

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
