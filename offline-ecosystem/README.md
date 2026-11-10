# RC7.2 DSH Ecosystem Offline Bundle

This is a platform-specific **extension bundle**, not a DSH engine installer. It contains four DSH extensions, their npm runtime dependency trees, a matching Mnemon native Memory CLI, original licenses/notices, an SPDX SBOM and SHA-256 manifest.

## Included

| Extension | Package | Pinned version | License |
|---|---|---:|---|
| Skills Manager | `@michengai/dsh-skills-manager` | 1.4.1 | Apache-2.0 |
| Mnemon | `dsh-mnemon` | 0.5.43 | MIT |
| Archify | `dsh-archify` | 0.1.0 | MIT |
| ModLens | `@liustack/modlens` | 3.27.3 | MIT |

The Mnemon local Memory Provider additionally needs the native `mnemon` CLI. This bundle includes v0.2.9 for the matching OS/CPU and verifies the upstream release checksum before packaging.

## Explicit exclusions

dsh-qa, dsh-routing-suite (no new integration), Tencent WeKnora and dsh-weknora are not included. Existing RC7.2 core components are not removed or modified by this add-on.

## Requirements

- An existing RC7.2-compatible DSH host; the DSH engine itself is not bundled.
- Node.js 22.19+ in the DSH host runtime.
- Python 3.8+ for the installer.
- An existing RC7.2 package root with `SOURCE_COMMIT` and `packaging/rc7.2/AITEST.sh`.
- DSH profile `rc7.2-bank` (or another explicitly named `rc7.2-*` profile). The protected `web` profile is forbidden.

The installer checks the DSH engine range declared by Skills Manager and Mnemon and then asks the local DSH CLI to install each bundled local package. It sets npm/pnpm offline flags; it never runs `npm install`, `npm pack`, `pip install`, or a public registry download on the bank host.

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

## Install into the isolated RC7.2 profile

Windows:

```powershell
python .\install.py install --rc72-home "D:\\RC7.2" --dsh-bin "C:\\path\\to\\dsh.cmd" --profile rc7.2-bank
```

Linux:

```bash
python3 ./install.py install --rc72-home "$HOME/RC7.2" --dsh-bin "$(command -v dsh)" --profile rc7.2-bank
```

Keep the extracted bundle until the install receipt is written. The installer copies all package files and the native Mnemon CLI into the RC7.2 package root, then links the local packages into the isolated profile. It never targets `web`.

## Mnemon

The native CLI is copied to `workspace-template/runtime/mnemon`. The RC7.2 launcher sets `MNEMON_CLI_PATH` for the DSH process. Mnemon's runtime memory and project documents are local. Auto-capture and skill self-evolution remain disabled by upstream defaults; third-party Memory Space providers remain unconfigured.

Memory is not the execution truth source. R1/event-stream remains authoritative for task state, test results and evidence.

## ModLens safe activation

ModLens is installed **disabled by default**. Its upstream default can select a public provider when no config exists, so this bundle deliberately prevents that.

1. Configure an approved internal OpenAI-compatible multimodal endpoint:
   `python install.py configure-modlens --internal-host-suffix <bank-internal-domain-suffix>`
2. The command prompts for endpoint/model and reads the API key through hidden input. It refuses endpoints outside the supplied internal DNS suffix. Existing config is preserved unless `--replace-existing` is explicitly supplied; any replaced config is backed up.
3. Enable the plugin only after configuration:
   `python install.py enable-modlens --rc72-home <RC72_ROOT> --internal-host-suffix <bank-internal-domain-suffix>`
4. Restart DSH. ModLens is pinned to the internal OpenAI-compatible provider, proxy inheritance is disabled, and reuse of Claude/Codex/OpenCode/Pi/Grok local credentials is false.

## Health and uninstall

```bash
python install.py health --rc72-home <RC72_ROOT> --profile rc7.2-bank
python install.py uninstall --rc72-home <RC72_ROOT> --profile rc7.2-bank
```

Uninstall removes the four plugin registrations and the bundled Mnemon executable only when its SHA-256 still matches the install receipt. It preserves `~/.mnemon` memory data and never touches the protected `web` profile.

## Qualification boundary

A GitHub build proves the artifact was assembled and hashed on the named platform. It does not prove activation on a bank DSH host. Host activation must pass against the bank's actual DSH version and isolated profile before field acceptance.
