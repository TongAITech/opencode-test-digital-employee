# V1.12 install and daily start contract

ArchitectureBaseline remains v7 / FROZEN / UNCHANGED. G1–G5 remain CLOSED / FROZEN;
G6 remains HOLD. The R1 Event Stream is the only durable Runtime Truth.

First use on Windows x64, from Git Bash in the extracted delivery directory:

```bash
./INSTALL.sh
```

The default installation is `/d/PFC/AITest`. An explicitly selected location is
supported as `./INSTALL.sh --target /d/PFC/AITest-new`. Every existing destination,
including an empty directory or a broken link, is refused before copying. There
is no overwrite, upgrade, data deletion, or automatic incomplete-install cleanup.
An incomplete new installation retains `.AITEST_INSTALLING` and cannot be started.

The installer verifies every entry in `FILE_SHA256.json`, cross-checks the offline
registry, payload inventory, runtime lock, and build provenance, then copies only
the sealed delivery files. Unlisted transport files are never imported. It checks
the copied bytes again before invoking the Python at the final installation path.
The Python self-check verifies Windows x64, Python version, package-owned API,
pytest, Playwright, greenlet and PDF imports, then initializes the canonical
`data/state/runtime-spine.db`. OpenCode, Chromium, CodeGraph, ripgrep, k6, Java and
ZAP are installed and hash-verified; tool execution is separately proven by Windows
qualification. The installer never starts OpenCode or the Control Loop and never
requests model, Starlink, 4A, CAT or DB authentication. It does not run an online
dependency installer or read host OpenCode credentials.

`data/state`, `data/logs`, `data/evidence`, `data/imports`, `data/exports` and isolated
OpenCode directories are created. `workspace-template/bindings/installation.json`
declares outstanding bank bindings without inventing approval. The original
`BUILD_PROVENANCE.json` and `OFFLINE_PAYLOAD_REGISTRY.json` remain unchanged.

The delivery `INSTALL_MANIFEST.json` has status `NOT_INSTALLED`. Installation
replaces only that file with a unique installation identity, final paths, source
HEAD, original manifest digest, checksum-inventory digest, and self-check result.
Daily integrity permits this single generated overlay only after validating the
identity. Changing the installation location requires a new installation; copying
an initialized runtime to a different directory does not silently rebind its data.

Daily use is exclusively from the installed runtime:

```bash
cd /d/PFC/AITest
./AITEST.sh
```

Model readiness is evaluated after OpenCode process startup. A pending model or
bank binding is a setup/HumanGate state and does not prevent opening OpenCode.
The extracted ZIP directory is a transport location, not an initialized Runtime.

Contract tests are synthetic installer fault-injection evidence. Windows
qualification must separately run this shell installer with the default path and
then execute the installed packaged Python and daily launcher. These checks do not
claim real BLOAN, provider, 4A, Starlink, CAT or DB acceptance.
