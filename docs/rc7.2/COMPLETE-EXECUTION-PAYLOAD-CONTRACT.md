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


## Observed copied Windows result

Component run `41602084608` at exact source
`b6bc99f02b05fba5702af42038ac6854b6e9478a` completed successfully. Downloaded
results prove actual copied offline graph construction (five nodes/six edges),
current registered analyzer, symbol/caller context and separate MCP resource
read. The component uses copied Node v22.23.4 and GitNexus 1.6.12. Full-text
search was disabled because FTS could not load. This result does not qualify
FTS, embeddings, the whole toolchain or the complete product package.

## Full-text extension construction

The copied-runtime doctor run `41602670990` confirmed that LadybugDB 0.18.3
loads its native module but has no FTS or VECTOR extension installed. The
published GitNexus 1.6.12 loader differs from current upstream packaging. No
current-upstream 0.22 artifact is substituted for that 0.18.3 native core.

The dedicated execution component now invokes its own packaged native FTS
installer at build time in a temporary private home. Only resulting native
extension artifacts are carried, with their original home-relative paths,
matching native core version and per-file hashes/sizes. The temporary build
home is removed before archive extraction. Restoration into a fresh private
worker home verifies every artifact before copying; no registry, credential,
source index or arbitrary home file is restored.

After clean extraction, the Node firewall and JavaScript network fence remain
active and extension policy is explicitly `load-only`. Qualification requires
an actual native FTS index over a two-document control fixture and an actual
query selecting the correct record. Search capability is marked qualified only
when that query succeeds. The dedicated job requires this payload; ordinary
graph-only qualification still identifies search as unqualified when absent.
This new construction path requires a successful Windows run before any claim
of copied offline FTS capability. VECTOR/embedding capability remains separate.
