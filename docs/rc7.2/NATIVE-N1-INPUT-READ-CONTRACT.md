# RC7.2 native N1 registered input read contract

Protocol: `RC72_NATIVE_N1_READ_V1`.

Construction supplies `N1ReadResource(source_ref, actual_file_path)` and a
`NativeN1ReadDshLauncher` to the existing N1 strict pipeline. The registry may
contain only original approved assignment input_refs. This does not establish
truth of a document's claims or replace a deployment/capability probe.

The exposed MCP tool is `read_scoped_reality_source`. Arguments contain only
`source_ref` and `mission_context={mission_id,task_id,worker_id}`; task_id is the
original canonical WorkItem. Tool schemas and production MCP routing share the
existing parent RPC transport with native N5, but parent authority and argument
validation are specific to N1 and cannot be switched by the child.

The parent permits only the original exact N1 worker/session/generation/lease,
no artifact-write authority, and the one read tool. Reads are at most 256 KiB
of UTF-8 text from regular files, with no child-selected path. Every actual
operation has a signed IN_FLIGHT intent and RETURNED or UNKNOWN observation.
The result contains source_ref, text, size_bytes, SHA256 and parent-owned capture
reference. The ephemeral URL/token never enters durable authority records.

A repeated live MCP request ID returns the same original capture; changed
arguments are denied. Historical/cold invocations do not replay reads or acquire
fresh authority. An unfinished invocation requires reconciliation or a new
canonical assignment; issuing another lease cannot restart the same assignment.
Post-effect authority/source loss preserves actual capture and UNKNOWN, with no
successful worker Attempt. A completed gate binds actual DSH session, output
hash and exact observed call count before handoff admission.

Replay validates original source/assignment lineage, signed historical lease,
signed complete call denominator and original captured bytes. Original source
files may subsequently change or disappear. Missing/changed captures fail
closed, including after strict N1 has already reached PASS. Captured document
contents are observations, and the existing independent N1 evaluator remains
responsible for semantic admission. This facility supplies neither Node PASS
nor Field/BANK_FINAL authority and is not an operating-system sandbox.
