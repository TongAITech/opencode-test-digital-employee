# RC7.2 — Linux x86_64 Field-Validation Transport

This is a **native Linux/Ubuntu 22.04 x86_64 field-validation candidate**, NOT a Windows ZIP
renamed as Linux and NOT a production release/BANK_FINAL package. It is built from the
exact source commit printed in SOURCE_COMMIT. This package requires glibc >= 2.35 on the
target; ABI and system library compatibility on the *bank* host must be verified there.

## Included

- RC6/RC7/RC7.2 runtime, tools, administration UI sources, R1 event-stream logic and N1–N10 control-plane code
- Managed, relocatable Linux CPython 3.11 and its bundled qualifier packages
- Native Linux Node.js >= 24.9.0 and Linux npm Playwright dependency tree
- Native Linux BrowserSkill CLI 0.4.1 and browser extension
- Offline Linux Playwright Chromium binaries
- DSH plugin vendor archive, including BrowserSkill DSH plugin 0.4.1 and Agent Teams
- Q3 target-Linux probe + handoff contract and exact per-file SHA256 manifest

**Not included:** any Windows executables as runtime dependencies, native bank-controlled
Linux DSH CLI, bank model secrets/certificates, external business connectivity.
GitNexus is deliberately **not bundled** because the verified upstream version carries
a PolyForm Noncommercial license; the graph capability remains HOLD unless separately
authorized. Source references and notices are not permission to run restricted code
in a commercial bank. No file from an unapproved DSH CLI is copied into this package.

## Download and move

Download the RC72-LINUX-FIELD-UBUNTU22-X64-<SHA> GitHub Actions artifact.
GitHub delivers an outer ZIP containing the inner native RC72-LINUX-FIELD-UBUNTU22-X64-<short-sha>.tar.gz
and the .tar.gz.sha256 file.

On a target Ubuntu 22.04 x86_64 compatible machine, extract the artifact ZIP first.
**Verify the inner tarball before extracting it**:

    sha256sum -c RC72-LINUX-FIELD-UBUNTU22-X64-<short-sha>.tar.gz.sha256
    tar -xzf RC72-LINUX-FIELD-UBUNTU22-X64-<short-sha>.tar.gz
    cd PFC-AITest-DSH-RC7.2-UBUNTU22-X64-FIELD
    bash packaging/rc7.2/LINUX-FIELD-AITEST.sh --verify-only

The verifier operates on package-local Python and checks every sealed file digest.
Run the exact Linux script; packaging/rc7.2/AITEST.sh belongs to Windows/Git Bash.

To actually launch the pre-approved bank Linux DSH CLI, set the *absolute* approved
executable path (not a Windows .exe, installer, symlink or text placeholder):

    export PFC_RC72_DSH_LINUX_HOST_BIN=/opt/bank/dsh/bin/dsh
    export PFC_RC72_DSH_LINUX_HOST_SHA256=<64_hex_official_digest>   # optional
    bash packaging/rc7.2/LINUX-FIELD-AITEST.sh

Only executable ELF64/x86_64 files or executable shebang scripts named dsh are
accepted; the SHA256 receipt is written to state/dsh-linux-host-binding.json.
This is **observation**, not identity/authorization or a bank field PASS.
The CLI is executed with an isolated rc7.2-bank-linux profile and package-local
Node/BrowserSkill on PATH. Plugin enablement and actual Captain/Agent Teams binding
must be validated using the bank's DSH profile and provider configuration.

## Q3 target Linux proof

The generic GitHub Ubuntu Runner is deliberately **not** approved bank target Linux.
Generate a real target observation and external attestation request in the bank environment:

    bash packaging/rc7.2/LINUX-FIELD-AITEST.sh --q3-handoff \
      --runner-kind BANK_FIELD_TARGET \
      --runner-identity <approved_machine_identity> \
      --output-dir runtime-state/q3-target-handoff

An independent trusted verifier must bind the actual host observation to the exact
package evidence. Do not edit the observation or claim Q3 PASS from the GitHub runner.

## Boundaries and checks

The clean GitHub runner qualification checks source commit, full SHA256 coverage,
runtime executables and imports, Playwright+Chromium offline, BrowserSkill CLI
native version, and Linux Q3 generic HOLD behavior. Native Agent Teams 32-member
real runtime, true R1/Q3 acceptance, bank DSH launch, session cold recovery,
business 4A/Libra/CAT/DB E2E, Graph coverage and BANK_FINAL require bank-side proof.

No sudo, package manager, network download or configuration overwrite is performed
during normal field startup or standalone package verification.
