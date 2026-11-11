# RC7.2 DSH Ecosystem Offline Bundle

This is a platform-specific **optional extension payload**, not a DSH engine installer. It contains four DSH extensions, their npm runtime dependency trees, a matching Mnemon native Memory CLI, original licenses/notices, an SPDX SBOM and SHA-256 manifest.

## Included

| Extension | Package | Pinned version | License |
|---|---|---:|---|
| Skills Manager | `@michengai/dsh-skills-manager` | 1.4.1 | Apache-2.0 |
| Mnemon | `dsh-mnemon` | 0.5.43 | MIT |
| Archify | `dsh-archify` | 0.1.0 | MIT |
| ModLens | `@liustack/modlens` | 3.27.3 | MIT |

The Mnemon local Memory Provider additionally needs the native `mnemon` CLI. This bundle includes v0.2.9 for the matching OS/CPU and verifies the upstream release checksum before packaging.

## Explicit exclusions

`dsh-qa`, `dsh-routing-suite` (no new integration), Tencent WeKnora and `dsh-weknora` are not included. Existing RC7.2 core components are not removed or modified by this add-on.

## Requirements

- An existing RC7.2 package root with `SOURCE_COMMIT` and `packaging/rc7.2/AITEST.sh`.
- Python 3.8+ for the installer.
- An existing bank DSH host; the DSH engine itself is not bundled.
- For explicit activation: the DSH CLI and `pnpm` must be on `PATH`; Node.js 20+ is required for Skills Manager and Mnemon. ModLens additionally requires Node.js 22.19+.
- DSH profile `rc7.2-bank` (or another explicitly named `rc7.2-*` profile). The protected `web` profile is forbidden.

The optional extensions are **disabled by default**. The first install only stages and hash-verifies their payloads; it does not mutate any DSH profile. Each explicit activation uses a local `link:` dependency in the selected isolated profile, with pnpm offline mode and public registry access disabled. The activation flow initializes a new custom profile from the shipped `web` template when needed, verifies the composed config, performs a bounded profile boot, checks that the protected `web` profile is unchanged, and writes a DSH Profile Activation Receipt. A receipt proves profile configuration and boot only; it does not claim a real plugin tool call or runtime effect. R1 evidence is still required for that.

## Verify before installation

Windows PowerShell:

```powershell
Get-FileHash .\RC72-DSH-ECOSYSTEM-WINDOWS-X64.zip -Algorithm SHA256
python .\install.py verify
```

Linux:

```bash
sha256sum RC72-DSH-ECOSYSTEM-LINUX-X64.zip
python3 install.py verify
```

The downloaded ZIP must match its adjacent `.sha256` file before extraction. The installer also verifies every package tree hash and the Mnemon native executable hash.

## Stage the optional payload

Windows:

```powershell
python .\install.py install --rc72-home "D:\RC7.2" --profile rc7.2-bank
```

Linux:

```bash
python3 ./install.py install --rc72-home "$HOME/RC7.2" --profile rc7.2-bank
```

This copies the four extension trees and the Mnemon CLI into the RC7.2 package root and writes an install receipt. It does not create or mutate a DSH profile and does not enable any extension.

## Explicitly activate an extension

Run only after the DSH host and pnpm are available. Each command links the local package into the isolated profile; it never targets `web`.

```bash
python install.py enable-plugin --rc72-home <RC72_ROOT> --package-id dsh-skills-manager --dsh-bin <DSH_CLI> --profile rc7.2-bank
python install.py enable-plugin --rc72-home <RC72_ROOT> --package-id dsh-mnemon --dsh-bin <DSH_CLI> --profile rc7.2-bank
python install.py enable-plugin --rc72-home <RC72_ROOT> --package-id dsh-archify --dsh-bin <DSH_CLI> --profile rc7.2-bank
```

If `DSH_HOME` is unset, the DSH profile is resolved under `.dsh` in the user's home. Set `DSH_HOME` explicitly when the bank host uses a non-default DSH home.

## Mnemon local-only policy

The native CLI is copied to `workspace-template/runtime/mnemon`; the RC7.2 launcher adds it to `PATH` and exports `MNEMON_CLI_PATH`. The bank bundle rewrites the Mnemon provider list to `mnemon-native` only. Remote Memory Space providers, auto-capture and skill self-evolution are disabled by default.

Memory is not the execution truth source. R1/event-stream remains authoritative for task state, test results and evidence.

## ModLens safe activation

ModLens is **staged but not registered by default**. Its upstream default can select a public provider when no config exists, so it cannot be activated until an approved internal endpoint is configured.

1. Configure an approved internal OpenAI-compatible multimodal endpoint:
   `python install.py configure-modlens --internal-host-suffix <bank-internal-domain-suffix>`
2. The command prompts for endpoint/model and reads the API key through hidden input. It requires direct HTTPS and refuses endpoints outside the supplied internal DNS suffix. Existing config is preserved unless `--replace-existing` is explicitly supplied; any replaced config is backed up.
3. Explicitly activate ModLens:
   `python install.py enable-modlens --rc72-home <RC72_ROOT> --internal-host-suffix <bank-internal-domain-suffix> --profile rc7.2-bank --dsh-bin <DSH_CLI>`

The activation gate checks Node.js 22.19+, the internal HTTPS endpoint, empty proxy inheritance, `denyWhenUnknown`, and all Claude/Codex/OpenCode/Pi/Grok credential-reuse grants set to false.

## Health and uninstall

```bash
python install.py health --rc72-home <RC72_ROOT> --profile rc7.2-bank
python install.py uninstall --rc72-home <RC72_ROOT> --profile rc7.2-bank --dsh-bin <DSH_CLI>
```

Health distinguishes staged payloads from explicitly activated plugins and checks their activation receipts. Runtime effect remains `false` until independently established from R1 evidence. Uninstall removes active local links, the staged payload and the bundled Mnemon executable only when package and binary hashes still match. It preserves `.mnemon` memory data and verifies that the protected `web` profile was not mutated.

## Qualification boundary

A GitHub build proves the artifact was assembled and hashed on the named platform. A DSH Profile Activation Receipt proves only isolated-profile configuration and boot. Neither proves a real plugin tool call, bank-host acceptance or Bank Final.
