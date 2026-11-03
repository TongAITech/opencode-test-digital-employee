# Package-owned configuration assembly

`rc7_release.rc72_configured_mission.configured_mission_bindings` creates the
native host capabilities from one approved local JSON file. Operators do not
have to implement a Python Mission factory. The existing approved execution
environment adapter is loaded through the inherited typed adapter interface.
This does not implement that adapter or certify its physical bank tools.

`rc72_mission_cli run` accepts exactly one of `--mission-config` or
`--bindings-module`. The original package/source/batch checks still precede
loading capabilities; native Q7/mirror and all node gates still precede effects.
The fixed module entry also accepts the configuration location from
`PFC_RC72_MISSION_CONFIG`; the direct CLI flag avoids a global environment edit.

`mirror-check` uses the same configured native provider and cold-stable
authority to execute the actual bank PC mirror observation into R1. It does
not start Mission nodes or grant Q7 admission. Optional original-user-config
bridging and retries of an authenticated returned failure must be explicit;
UNKNOWN is never replayed. Only a native full-package BANK_FIELD mirror fact
permits this subcommand's exit 0. Hosted engineering remains non-Field and
returns 37; Field/BANK_FINAL flags remain false in every mirror result.

The schema is `RC72_MISSION_CAPABILITIES_V1`, with exactly these fields:

* schema, release_id, source_commit
* package_root, state_root, dsh_bin, patch_path
* inputs: nonempty original source_ref/path pairs
* role_tools: the eleven exact roles and their exact non-wildcard tool lists
* tool_registry: formal execution family/tool lists
* environment_module: the existing approved execution adapter module
* archive, pip_field_config: native mirror gate inputs
* model_environment_names: explicit approved model environment variable names

Paths are resolved relative to the configuration file. Package source and all
bound files must exist. The file contains model variable names, not credential
values. Only the selected values are projected into the scoped launcher;
unrelated ambient credentials are not copied. Control-identity/signing-key and
private-home overrides are refused. Adapter failures become a safe contract
code without printing the original private exception or creating an authority.

After validation, an exclusive, fsynced 32-byte controller key is generated in
owned state under the canonical ledger lock. It is not part of the sealed
transport and never enters a Worker environment. Ledger/release/source scopes
have separate state; HMAC-derived per-role, formal-execution and mirror
authorities are distinct and stable on cold reconstruction at the same ledger
location. Corrupt keys and symlinks fail closed rather than being replaced.
Active ledger relocation requires explicit authority migration; the initial
transport contains no activated key or execution state.

Construction and cold reconstruction launch no model or business process and
append no R1 event. Neither a successful configuration read nor key creation is
evidence of SDK/provider readiness, Field qualification, node completion or
BANK_FINAL. The selected DSH patch/provider provisioning and every physical
role/tool fence remain separate required construction. Code roles now require the four registered Git/CodeGraph MCP tools defined in
CONCRETE-CODE-TOOL-BINDING-CONTRACT.md. Capability-only aliases are refused by
production factories; per-target native call-time provenance is still required.
No tool-policy relaxation is authorized by this configuration layer. A bank turnkey claim remains premature until these
integrations, professional repair and terminal closure are implemented.
