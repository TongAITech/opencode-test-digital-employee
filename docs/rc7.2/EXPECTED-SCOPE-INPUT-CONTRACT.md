# Expected release scope from original N1 input

The release owner supplies the expected catalog through the originally registered
`release-batch://<ReleaseBatchID>` input. `ExpectedScopeInputService` freezes its
actual captured bytes and lineage into the existing ReleaseScopeManifest. It
never derives the expected denominator from observed N2 output, generated Cases,
accepted Attempts, coverage ratios or a model's completion claim.

The trust boundary is the release owner's original resource registration. A
signed file read proves which bytes were read by the original scoped worker; it
does not prove that a file genuinely originated in a bank system, establish a
bank verifier's approval or grant BANK_FINAL. Actual bank-source acquisition and
verification remain part of the production connector/Field configuration.

## Input

The original file contains exactly these fields:

```json
{
  "schema": "RC72_EXPECTED_RELEASE_SCOPE_V1",
  "release_id": "the actual release",
  "release_batch_id": "the actual ReleaseBatch ID",
  "mission_id": "the original Mission ID",
  "source_commit": "the exact 40-character RC7.2 source commit",
  "application_ids": ["the original application ID"],
  "version_ids": ["the original version ID"],
  "requirement_ssts": {
    "the original Requirement ID": ["the expected SST ID"]
  },
  "required_levels_by_sst": {
    "the expected SST ID": ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
  },
  "source_refs": ["the authoritative original catalog reference/version"]
}
```

This is a shape example, not valid bank acceptance data. Application, version,
Requirement, ReleaseBatch, Mission and runtime source identities must match the
actual canonical batch. A batch with no version IDs preserves an empty version
list; it cannot silently gain or lose versions after freezing. Every Requirement
has a nonempty expected SST list, SST ownership is unique, and every expected SST
has a nonempty explicitly declared level set. Duplicate JSON keys, duplicate or
blank identities/levels, unexpected fields and JSON non-finite values are denied.
A declared subset of levels is the original policy's responsibility; the importer
never selects a subset from what happened to execute. No measurement percentage
or actual coverage result is supplied through this contract.

## Composition and checks

Construct the existing strict N1 pipeline with a NativeN1ReadDshLauncher whose
registry binds the original ReleaseBatch source reference to this real file.
Wrap that same pipeline with ExpectedScopeInputService and pass it as
ReleaseBatchDriver's `expected_scope`. The controller requires the same R1,
source, launcher and exact tool projection. It uses the composed pipeline so the
real N1 prompt requests `facts.expected_scope_input={source_ref,sha256}` copied
from the actual tool result. This prompt is not permission or proof: the importer
independently checks the signed native call, capture bytes, actual returned
candidate and accepted current N1 Gate.

Before N2 starts, the controller freezes a signed input receipt and the canonical
manifest. Repeated original reads are allowed only when their captured bytes are
identical; every contributing call is bound. Changing catalogs during N1 are
rejected rather than choosing a favorable version. Existing unattested manifests
cannot be silently adopted. Changing a signed receipt or reducing a frozen
manifest fails closed, including during controller continuation.

A crash after the signed input receipt but before the manifest write resumes
that same receipt. Replay can run in a fresh controller without the original
input file, another worker process, restored worker leases or another read. It
still requires unchanged parent-owned captures and raw handoff evidence. The
existing bounded native-reader size limit applies; no source is truncated to
produce a smaller expected denominator.

Editing the source file after its original read does not amend a frozen policy.
A legitimate catalog revision requires controlled source/scope revision rather
than overwriting expected rows. Such broader revision recovery and production
factory/CLI wiring remain construction work. A configured invalid policy stops
before N2; it does not automatically repair or replace its original source.

This establishes the expected denominator only. Missing observed SSTs/levels,
measured authoritative coverage, defects, unresolved gaps and other N10 criteria
remain independently required. It creates neither TestObligations nor Cases,
execution success, release convergence or bank acceptance.
