# Security and Execution Boundary

OpenCode built-in file and shell tools are denied. Role-scoped custom tools invoke the local Runtime. Capability Broker validates actor role, Mission state, current Step, capability ID, environment and Gate before any operation.

Business repositories are never modified by the Runtime. Test-environment writes require H3. High-risk writes additionally require an explicit HumanTask/approval and a project-specific adapter. Secrets remain behind `secret://`, `env://` or `profile://` references.
