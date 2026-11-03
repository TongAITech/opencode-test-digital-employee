# Code tool subprocess scope

CodeGraph MCP, CodeGraph CLI and local read-only Git processes now receive the
existing scoped OS/tool environment instead of a copy of the Worker environment.
The configured executable is resolved before spawn. The repository cwd and exact
command arguments remain unchanged. Provider tokens, native parent-gate tokens,
DSH profile paths, unrelated credentials and inherited Python/plugin injection
settings are not forwarded. Each invocation owns a temporary private home;
CodeGraph MCP keeps it alive through client shutdown/reaping and then removes it.
Startup failure removes the private home as well. No bank/user profile is copied.

Git diff already disabled external diff; it now also disables textconv on both
name and content queries. A repository-defined converter otherwise executes a
program during a nominal read-only diff. Original commit resolution, selected
paths and bounded raw diff output remain. This does not authorize writes,
indexing or a fallback repository.

Validation: actual Python MCP child performs initialize/list/query with the
approved cwd and private home; synthetic credential names and a private profile
marker are absent. Child exit precedes home cleanup, including startup-failure
cleanup. Direct code-tool child has the same credential boundary. A real local
Git repository demonstrates that its configured textconv makes ordinary Git
diff fail, while the protected adapter returns the original actual diff without
executing the converter. 12 focused tests passed in 1.89s; 19 inherited MCP/
DSH/code-evaluator/node-policy tests passed in 0.80s.

These are local engineering proofs, using a synthetic CodeGraph protocol server
and real Git. They do not qualify the packaged CodeGraph binary or bank data.
Approved repository/revision fences, exact bank-tool provenance, automatic
per-role SDK patch provisioning, generic orphan-tree recovery and the complete
bank execution adapter remain separate required construction. This environment
is not an OS filesystem sandbox and does not grant a CodeGraph query authority
merely because it can start a process.
