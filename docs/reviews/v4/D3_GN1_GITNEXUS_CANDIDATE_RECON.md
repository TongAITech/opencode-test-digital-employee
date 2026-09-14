# D3-GN1 GitNexus Candidate Reality Recon

Repository: `TongAITech/opencode-test-digital-employee`  
ArchitectureBaseline: `v7 / FROZEN / UNCHANGED`

## Purpose

D3-GN1 evaluates whether a second structural graph provider can complement the current
Git + CodeGraph path for Vue/page-impact analysis. It does not replace Git as change
truth and does not replace CodeGraph where CodeGraph is already proven.

## Current proven baseline

- Git is the sole changed-file / changed-line authority.
- Real Windows CodeGraph 0.20.1 is proven for Java and TypeScript structural impact.
- Real Vue CodeGraph qualification is fail-closed: unsupported/unresolved structural
  mapping is PARTIAL with an OPEN obligation rather than false COMPLETE.

## GitNexus candidate reality

Upstream package metadata observed during D3-GN1 recon:

- package: `gitnexus`
- version: `1.6.12`
- engine: `node ^22.18.0 || >=24.11.0`
- license: `PolyForm-Noncommercial-1.0.0`
- relevant capabilities present upstream:
  - Vue SFC ingestion
  - Vue scope resolution
  - graph impact
  - git-diff `detect_changes`
  - execution-process detection
  - API route map / API impact

Candidate Node runtime is therefore pinned to the minimum supported 22.x boundary:

- Node: `22.18.0`
- platform: `windows-x64`
- archive: `node-v22.18.0-win-x64.zip`
- archive SHA256:
  `c95d8a7e1c99e669cc08c9f1176e068c1f50847c37908fcb8c35b62482366511`

D3-GN1 qualification must invoke this portable runtime by exact path. System Node
and the bank host's existing Node 20.11 are not runtime authority.

## Mandatory license gate

The GitNexus repository/package declares `PolyForm-Noncommercial-1.0.0`.
The AITest target is a bank/commercial environment.

Therefore:

```text
GITNEXUS_TECHNICAL_CANDIDATE = REGISTERED
GITNEXUS_COMMERCIAL_USE_AUTHORITY = NOT_ESTABLISHED
GITNEXUS_EXECUTION_IN_BANK_PACKAGE = FORBIDDEN_PENDING_LICENSE_AUTHORIZATION
GITNEXUS_BUNDLING = FORBIDDEN_PENDING_LICENSE_AUTHORIZATION
```

No GitNexus package bytes, transitive dependencies, source, index, or runtime output
may be promoted into the bank offline package until a compatible commercial-use
license/authorization is established.

## D3-GN1 qualification stages

1. Portable Node Windows identity/execution qualification.
2. Provider-neutral secondary graph seam and Page Impact contract may be designed
   without embedding GitNexus.
3. Real GitNexus execution against AITest/PFC fixtures remains
   `LICENSE_AUTHORIZATION_REQUIRED`.
4. If commercial-use authorization is later established, execute a separate exact
   version Windows qualification that proves:
   - Vue SFC indexing
   - changed Vue/component mapping
   - upstream component/page blast radius
   - git-diff `detect_changes`
   - Vue Router/Page Impact reconciliation
   - fail-closed behavior for unknown edges.

## Provider policy

```text
GIT = CHANGE_TRUTH_AUTHORITY
CODEGRAPH = STRUCTURAL_PROVIDER_1
SECONDARY_GRAPH_PROVIDER = OPTIONAL / NON_AUTHORITY
PAGE_IMPACT = AITEST_CANONICAL_PRODUCT_SEMANTICS

SECONDARY_PROVIDER_OUTPUT != PAGE_IMPACT_TRUTH
PROVIDER_FAILURE != EMPTY_IMPACT
UNKNOWN_EDGE => EXPLICIT_OPEN_OBLIGATION
```

D3-GN1 does not reopen D1/D2 and does not modify ArchitectureBaseline v7.
