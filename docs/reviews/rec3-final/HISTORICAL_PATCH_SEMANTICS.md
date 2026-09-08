# V1.9.4 surviving patch semantics

Raw scripts were inspected without execution. These packages are historical capability evidence, never an overlay onto v7 Runtime.

- Browser harness `apply-browser-teaching-upgrade.sh:27` copies its payload into an existing Workspace; browser hardening `apply-upgrade.sh:36` likewise copies payload after checking the old bundled CodeGraph node. Preserve their operation/observation intent, not old `.tools` installation or legacy SQLite truth.
- Tomorrow bundle `INSTALL_ALL.sh:27,37` explicitly applies Current Release truth/attachment/delta first, then performance/security governance. The Current Release installer invokes `scripts/apply_refactor.py`, not a blind chronological copy.
- Both browser harness and Current Release carry `ai-test/v194/pfc_v194.py`; replacing that dispatcher can remove earlier browser commands. Capability integration must preserve both command families in canonical product entry instead of choosing the newest whole file.
- Freshness hotfix modifies the distribution gate scripts and workspace freshness runner; it is not a Runtime architecture migration.
- Quality governance launcher hotfix requires the governance stage/policy to exist before copying its payload. Applying it before its prerequisite cannot be assumed successful.
- Historical CodeGraph v1.5.0 cached archive SHA256 `d6798622b4f44ee6757c94335f437ee27a9ff7d3537b554cb6a2b3baf11bc4a1` matches its old installer expectation but is in `.cache`, not the expected vendor installation slot. It is registered as a local historical artifact; the current v7 CodeGraph0.20.1 contract remains unchanged.

No prior V1.9.4 runtime or aitest.db is copied into Product Truth. Current capabilities are upgraded at their existing governed application boundaries.
