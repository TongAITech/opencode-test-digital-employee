# RC7.2 Windows Field-Validation Package

## What this package is

This is a **field-validation transport**, built from one exact RC7.2 source commit. It carries the RC7.2 source/runtime, package-local Python, Node, BrowserSkill/Chromium, CodeGraph, Java/Maven, offline plugin payloads, test tooling and the other runtime payloads listed in PACKAGE_MANIFEST.json and FULL-CAPABILITY-INVENTORY.json.

It deliberately **does not contain a native DSH CLI executable**. The bank must bind an already installed and approved Windows x64 DSH CLI on the target machine. This separates the ability to transport and inspect RC7.2 from permission to redistribute a third-party/bank-controlled executable.

This is not the final C12 turnkey package, is not a bank release, and does not claim that any Q3-Q9 field gate has passed. The package identity and manifest keep field_verified=false and bank_final=false.

## Install and start

1. Extract the ZIP to a writable local directory. Keep the complete directory structure.
2. Confirm the target machine has the bank-approved Git Bash installation.
3. Double-click start-rc7.2.cmd.
4. If the package-local workspace-template/runtime/dsh/dsh.exe is absent, the launcher asks for the full path to the bank-approved dsh.exe. Enter a path such as C:\BankTools\DSH\dsh.exe without surrounding quotation marks.
5. The launcher checks that the selected file is a regular Windows PE32+/AMD64 executable named dsh.exe, records its path and SHA256 in state/dsh-host-binding.json, and verifies that Git Bash resolves the exact same executable. It does not copy or modify the bank DSH installation.
6. If the bank has an independently recorded expected SHA256, set PFC_RC72_DSH_HOST_SHA256 before starting. A matching hash verifies bytes only; it does not establish vendor identity or organizational authorization.

You can preconfigure the path from a command prompt before starting:

- set PFC_RC72_DSH_HOST_BIN=C:\BankTools\DSH\dsh.exe
- set PFC_RC72_DSH_HOST_SHA256=<64-hex-expected-sha256> (optional)

Do not place quotes around the path value. The environment variables are inherited by Git Bash.

## What remains a bank-side binding

Git Bash, the approved DSH CLI, model endpoint/account, 4A, business routes, CAT, database connectivity, internal certificates and any bank-only dependency mirrors remain controlled by the bank. Do not copy credentials, tokens, certificates or protected DSH profiles into the package.

The runtime launcher continues to use an isolated RC7.2 DSH profile and does not overwrite the protected base profile. Agent Teams 32-member capacity is a source/configuration capability; it is not proof that 32 real sessions were created. The default active-worker admission limit remains separate from the roster size.

## First field-validation sequence

1. Start the package and preserve the generated state/dsh-host-binding.json.
2. Confirm the DSH UI starts with the isolated rc7.2-bank profile.
3. Verify the RC7.2 package identity, R1 event stream and durable runtime state.
4. Verify Agent Teams provider trust, real Captain/session binding, 32 roster behavior and 33rd-member rejection using the approved bank DSH host.
5. Exercise real model 429/502 back-pressure, cold restart/session recovery and N8-N9-N10 evidence convergence.
6. Run the bank-specific 4A, BrowserSkill, Libra and business Journey checks. Preserve original failures and all signed evidence.

A successful package build or DSH path observation is not a successful field test. The bank Host and independent reviewer must produce the real evidence required by the frozen Q3-Q9 contracts.

## Integrity and qualification boundary

- The ZIP has a sibling .sha256 file. Verify it before extraction.
- SOURCE_COMMIT, PACKAGE_MANIFEST.json, CHECKSUMS.sha256 and FIELD-VALIDATION-PACKAGE.json identify the exact source and physical payload.
- dsh_main_payload.bundled=false and dsh_main_payload.mode=EXTERNAL_BANK_HOST_BINDING_REQUIRED are intentional and must not be changed to claim a complete C12 package.
- The package workflow performs clean extraction, package identity/checksum verification, full physical payload inventory, Python/document capability checks, offline execution-node qualification and clean R1/session continuity checks.
- Final native DSH redistribution, physical C12 Q2 with a packaged executable, bank Q3-Q9 and BANK_FINAL remain separate gates.
