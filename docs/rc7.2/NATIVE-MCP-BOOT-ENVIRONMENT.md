# Native Worker MCP boot environment

The generated rc7_release.dsh.write_patch overlay now explicitly forwards only
PFC_RC72_TOOL_GATE_URL, PFC_RC72_TOOL_GATE_TOKEN, PFC_RC72_TOOL_GATE_CONTEXT and
PFC_RC72_TOOL_GATE_PROTOCOL through JavaScript boot expressions. Expressions
read the current Worker process environment with an empty absent-value default.
Neither their current values nor model/control credentials are serialized in
the generated patch. The configured Mission model-environment selector refuses
these four names before host loading or controller-key creation; native parent
gates own their values.

Reason: pinned public SDK source 8bd073392eef6f54e921a093b95076248eb08cbb,
packages/mcp/mcp-client/src/transport.ts, merges explicit MCP env after
scrubbedParentEnv(). packages/subprocess/subprocess/src/index.ts removes
credential-shaped KEY/PASSWORD/SECRET/TOKEN names and DSH_* facts from implicit
inheritance. Thus a native per-Worker tool-gate token is lost without deliberate
forwarding. Removing the SDK scrub would expose unrelated model credentials.
The generated explicit projection retains the scrub and restores only this
parent-issued scoped capability. It does not carry a Captain signing key.

Validation uses the actual generated expressions in Node, followed by a real
MCP Python child and live parent-owned N1 gate. With implicit scrub alone the
read is denied and no native attempt/read is accepted. With explicit native
projection the actual approved source bytes are captured and admitted. Existing
scope/lease/revocation/capture/no-replay cases remain. This is engineering proof
using a synthetic Worker protocol and the pinned public SDK scrub semantics;
it is not an installed bank DSH/model invocation or bank SDK compatibility fact.

This fix applies to generated patches. It does not rewrite arbitrary approved
external patches or copy a user's global profile. Full configured factory
per-role patch generation, selected model/provider setup, exact bank SDK boot,
private-profile provisioning and all-role call-time tool provenance remain
required construction. N1/N5 native capabilities are not a replacement for
other roles' complete tool adapters or generic bank execution.
