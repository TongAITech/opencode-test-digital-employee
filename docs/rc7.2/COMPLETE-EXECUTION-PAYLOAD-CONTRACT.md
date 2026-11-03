# Complete execution payload and physical inventory

The RC7.1 reference physically carried GitNexus beside Playwright. The RC7.2
materializer now acquires both, allows their required native build/install
steps at build time, and preserves the dependency lock and digest. GitNexus stays
an optional secondary provider, disabled by default and without change-truth
or R1 authority. Optional runtime activation does not remove its full-transport
carriage requirement. Package name/version/CLI entry must be valid and local;
an empty folder, missing CLI or external CLI path cannot establish completeness.
Actual manifest license and resolved version are included in inventory metadata.

The new `FULL-CAPABILITY-INVENTORY.json` records all thirteen physical runtime
groups, actual file/byte counts, source identity, carried secondary provider and
optional plugin archives. Paths are package-relative and inventory is checked
again after relocation. Missing groups or omission hidden by a weaker lock are
refused. This is **physical discovery**, not execution or product completion;
actual tool qualification and full-file manifest/checksum verification remain
separate authorities.

Repacking applies the existing generated-file exclusion rules used by checksums:
compiled Python caches and root build/session state are not transported as new
bank state. Filtering does not delete those files from the source directory.

## Actual execution component qualification

The dedicated Windows workflow builds Node plus both execution packages, archives
them, deletes staging and extracts to a path with spaces. It then blocks outbound
traffic for the copied Node executable and verifies the actual firewall rule,
active profiles and firewall service. This is an isolated CI test, not a bank
startup firewall requirement. A controlled Node preload additionally rejects
network calls and runtime package-manager/download fallback. The test receives
no model/API credentials and requests no embedding generation.

`rc72_execution_node_qualification` uses only the copied Node and package-local
CLI entry. It imports Playwright, analyzes two local TypeScript fixture files,
reads actual registered-index status, verifies a real symbol/caller edge, and
reads `gitnexus://repo/rc72-offline-graph/context` through a separately launched
stdio MCP server. Analysis uses the documented index-only mode in an isolated
home/registry, so it does not modify the user's repo instructions or registry.
The no-Git fixture uses the documented skip-Git mode; this does not certify
project Git access or bank source binding. Actual native database/parser and
resource-read results are required, not merely a successful `--version`.

The context resource is read directly through the packaged stdio MCP server.
The delivered probe invokes a known local CLI entry, with no npx or global-install
fallback. The upstream [GitNexus CLI documentation](https://github.com/abhigyanpatwari/GitNexus)
provides the analysis, status and context interfaces. The same execution probe
is included in the full portable clean-extraction step.

Local contract and actual Node preload tests passed; the Windows native component
run is required before claiming its copied-platform graph capability. Component
archive/evidence alone is not the complete product delivery. Native professional
runtime, final all-source/product/package qualification and bank Field remain
separate requirements of the full RC7.2 objective.
