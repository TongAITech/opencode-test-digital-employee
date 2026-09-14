# D3-GN1 Portable Node Windows Evidence

Repository: `TongAITech/opencode-test-digital-employee`  
Branch: `work/v1.13.0-recovery-turnkey-validation`  
ArchitectureBaseline: `v7 / FROZEN / UNCHANGED`

## Disposition

```text
D3_GN1_PORTABLE_NODE_IDENTITY = PASS
D3_GN1_PORTABLE_NODE_WINDOWS_EXECUTION = PASS
D3_GN1_NODE_PACKAGE_CONTRACT = PASS
D3_GN1_NODE_TREE_IDENTITY = PASS
D3_GN1_GITNEXUS_EXECUTION = NOT_EXECUTED / LICENSE_AUTHORIZATION_REQUIRED
D3_GN1_GITNEXUS_BUNDLING = FORBIDDEN_PENDING_LICENSE_AUTHORIZATION
OFFLINE_PAYLOAD_REGISTRY_NODE_SYNC = PENDING
FINAL_PACKAGE_NODE_MATERIALIZATION = PENDING
```

This evidence closes the portable Node qualification only. It does not authorize
GitNexus commercial use, does not claim a final bank package, and does not turn any
secondary graph provider into Git change truth or Page Impact truth.

## 1. Candidate identity

The qualified candidate is:

```text
Node = 22.18.0
npm = 10.9.3
platform = windows-x64
archive = node-v22.18.0-win-x64.zip
archive_sha256 =
c95d8a7e1c99e669cc08c9f1176e068c1f50847c37908fcb8c35b62482366511

node.exe_sha256 =
c22d1c59a1f767a1ed0178445a027f2257d318c55430fc819d48f269586822b7
```

The runtime is invoked by exact absolute path. Host/system Node is not runtime
authority.

## 2. Windows execution qualification

Corrected qualification commit:

`646d96a0983b6877d0540af4c4557092d1d54c87`

Workflow:

`V4 D3-GN1 portable Node Windows qualification v2`

Evidence:

```text
run_id = 34866676311
job_id = 104052127359
conclusion = SUCCESS
artifact_id = 10357621136
artifact_sha256 =
72f860f0faae100e74921779c7b15cb153dc8ed7ce4842d7cbfa2523388f1674
```

The Windows run proved:

- exact archive SHA256;
- `node.exe --version = v22.18.0`;
- `npm.cmd --version = 10.9.3`;
- `process.execPath` is the extracted portable `node.exe`;
- Windows x64 execution;
- host Node is not runtime authority.

The earlier workflow attempts `34866445644` and `34866500912` failed because a
PowerShell local variable named `$home` collided with read-only `$HOME`. This was
a qualification-runner defect, not a Node product/runtime failure. The broken v1
workflow was retired by commit
`1a109b5aaad1a0e92c552efb2c2301454808b70d`.

## 3. Runtime lock and package contract

Runtime-lock registration commit:

`088f4cb72e4954185377beb3fd10eab5b041ef84`

The lock pins Node 22.18.0, archive SHA, executable SHA and:

```text
host_node_authority = false
gitnexus_binding_status = LICENSE_AUTHORIZATION_REQUIRED
```

The existing D3 real CodeGraph Windows qualification re-ran after this runtime-lock
change and remained green:

```text
run_id = 34866849466
conclusion = SUCCESS
```

Therefore the Node lock addition did not regress the proven Java/TypeScript/Vue
CodeGraph path.

Package build requirement commit:

`0f1036e62b90f5bde1d6145fd585fd2fd501a988`

The package builder now requires at least:

```text
runtime/tools/node/node.exe
runtime/tools/node/npm.cmd
```

Installed-package validation commit:

`8ab2e53922e6bba4856afe7641582a951e1e5a0d`

The Windows package validator now executes the installed portable Node by package
relative path and requires `v22.18.0`.

Package-contract gate:

```text
commit = 94980064a644f252f22687750ee198a5a1dda4ed
run_id = 34867192990
job_id = 104053871648
conclusion = SUCCESS
artifact_id = 10357386945
artifact_sha256 =
c292f81767ce4d21593311bce782f4afb95e89e41912067ae95e13f8196a902d
```

## 4. Exact Node tree identity

Tree-manifest workflow commit:

`f8ed899ebb314b8671949ba4b05743eecf38e751`

Evidence:

```text
run_id = 34867611040
job_id = 104055291672
conclusion = SUCCESS
artifact_id = 10357532305
artifact_sha256 =
6f2fade20f82e576cb91f6a37a438c4538c251f87ac84e93e5ea0dcd3683fd4e

file_count = 2313
size_bytes = 98350838
tree_sha256 =
3b6d4fe8479e4e4c699be3b237dc5c81eb4d0da2af0bd7eed152b793a3bbc096

npm.cmd_sha256 =
21b46c69ad6e2f231f02a9e120f4ba6c8e75fef5a45637103002eab99f888ab8
```

The tree digest was calculated from sorted bundle-relative file paths and each
file's SHA256. The uploaded manifest contains all 2313 per-file identities.

Generic staged-tree verification support was added in commit:

`b7825fb8861c0283934162c17cd15a43748b6c09`

The package builder can verify a staged artifact using `hash_kind=tree_digest`
plus exact digest, file count and byte count.

## 5. GitNexus boundary

GitNexus candidate recon is recorded in:

`docs/reviews/v4/D3_GN1_GITNEXUS_CANDIDATE_RECON.md`

The upstream candidate inspected during this work is GitNexus 1.6.12 and requires
Node `^22.18.0 || >=24.11.0`. Its public license is
`PolyForm-Noncommercial-1.0.0`.

Because the target is a bank/commercial environment:

```text
GITNEXUS_COMMERCIAL_USE_AUTHORITY = NOT_ESTABLISHED
GITNEXUS_REAL_EXECUTION = NOT_AUTHORIZED
GITNEXUS_BANK_PACKAGE_BUNDLING = NOT_AUTHORIZED
```

No GitNexus package bytes, index or output are admitted by this evidence.

## 6. Page impact architecture reality

The repository already contains the canonical R3.5 PageGraph/PageNode model with:

- route patterns;
- router refs;
- component refs;
- menu/permission refs;
- API binding refs;
- backend relation refs;
- explicit unresolved gaps.

Therefore a future secondary graph provider, if authorized, is enrichment only:

```text
Git exact diff
  -> CodeGraph / optional secondary structural provider
  -> R3.5 PageGraph reconciliation
  -> affected page/route set
  -> explicit unresolved impact edges
```

A provider's `affected_processes` output must not become a second Page Impact truth.

## 7. Remaining work

The existing `OFFLINE_PAYLOAD_REGISTRY.json` has not yet been successfully
updated with the new Node tree contract because connector safety checks blocked the
large Registry mutation. That blocked write did not partially modify the file.

Consequently:

```text
PORTABLE_NODE_ENGINEERING_QUALIFICATION = PASS
PORTABLE_NODE_FINAL_PAYLOAD_REGISTRY_SYNC = PENDING
PORTABLE_NODE_FINAL_STAGE_MATERIALIZATION = PENDING
GITNEXUS_LICENSE_GATE = OPEN
D3 = IN_PROGRESS
```
