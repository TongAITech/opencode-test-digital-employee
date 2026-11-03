# Native SDK wire seam

OwnedSDKWire is the bounded stdio transport needed by the forthcoming native
Worker SDK launcher. It requires an explicit command, cwd and complete scoped
environment containing DSH_HOME; it never reads a default user Harness home or
selects a fallback provider/model. Initialize sends the exact selected provider,
model and cwd, and checks the SDK server identity before allowing a prompt.

Protocol basis: public DeepSeek Harness source
8bd073392eef6f54e921a093b95076248eb08cbb, packages/sdk/protocol/src/types.ts and
packages/sdk/client/src/client.ts. The wire uses initialize, session/prompt,
session/wait and shutdown. session/prompt returns a durable messageId, not a
completed turn. session/wait returns an empty object after native waiting; raw
notifications committed before the response remain in order. The initialization
result supplies serverInfo, not proof of model authentication or the provider
actually used by a model request. No MODEL_AUTH_READY/Worker PASS is inferred.

One client enqueues at most one fresh turn after initialization. Local size
refusal precedes the send marker. Interrupted writes, missing enqueue receipts,
timeouts and disconnects after a send mark possible enqueue and poison the
client: no second prompt, automatic replay, model fallback or fresh runtime is
started. Native Worker intent/unknown-state persistence must wrap this seam in
the integration, before the first send. This module writes no R1 decision.

Writes have a deadline even when the child stops reading stdin. Reads have
finite time, frame-size, frame-count and total-byte bounds. Provider stderr is
drained without retaining or printing private error text. Runtime requests for
host approval or human input are held as HOST_DECISION_REQUIRED; no fabricated
approval or user answer is returned. A healthy client attempts bounded native
shutdown; a poisoned/stuck client closes through terminate/kill/reap of its
owned direct child. This is not complete descendant-process recovery.

The seam preserves raw server frames. It does not filter foreign sessions into
accepted truth, invent an inbox receipt, extract a final candidate, assert a
tool call, meter model usage or authorize a native lease. The Worker adapter
must validate its root session, actual agent/inbox/spliced receipt, committed
assistant/message, turn/end, concrete tool calls/usage and exact route against
the native Attempt before admitting any proof. The public SDK emits all runtime
sessions; client-side filtering alone is not an authority boundary.

Validation uses actual Python child processes implementing the pinned wire
shapes. Cases cover exact route/native receipt/frame order/graceful shutdown,
foreign server identity/refusal/response-id mismatch (including boolean id),
missing receipt, timeouts before/after enqueue, blocked stdin, host requests,
per-frame/queue/total output limits and local size refusal. No model SDK was
installed and no external model API call was made. 73 wire/Worker environment/
package-boundary checks passed in 7.70s. This module is mandatory in Q2B and is
included in the dedicated platform suite.

Remaining integration: native Worker launcher and Assignment/Attempt model
binding, native inbox/final/tool/usage evidence validation, private per-role
profile and patch generation, exact installed bank SDK compatibility and
professional model-readiness/failover. The existing configured Mission still
uses its approved headless launcher/patch; this seam does not silently replace
that route or claim complete default SDK startup.
