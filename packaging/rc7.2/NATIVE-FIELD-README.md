# RC7.2 Native Linux / macOS Field Package

This package is built natively for one exact OS and CPU architecture. Do not copy its runtime binaries to another OS/architecture.

## Linux support boundary

- Package variants: Linux x86_64 and Linux ARM64.
- Build baseline: glibc >= 2.34 and kernel >= 4.18.
- Intended candidates: RHEL/CentOS Stream 9 family, compatible Kylin/UOS releases whose glibc/kernel meet the baseline.
- CentOS 7/8 and Rocky 8 are outside the glibc >= 2.34 baseline; Kylin/UOS require per-distribution validation, native dependencies and bank qualification.
- Chromium requires the documented host shared libraries; use \`bash packaging/rc7.2/AITEST.sh --verify-only\` and \`ldd\` diagnostics on the target before field launch.

## macOS support boundary

- Separate native packages: Intel x86_64 and Apple Silicon ARM64.
- macOS 14 or later.
- A macOS package is not a Linux package and cannot be used on Ubuntu/Kylin/UOS.

## Install and verify

1. Transfer the artifact ZIP from GitHub Actions and extract it.
2. Verify the inner archive checksum with \`sha256sum -c\` (Linux) or \`shasum -a 256 -c\` (macOS).
3. Extract the \`.tar.gz\`.
4. Run: \`bash packaging/rc7.2/AITEST.sh --verify-only\`
5. For a real launch, set \`PFC_RC72_DSH_HOST_BIN\` to the absolute path of the approved native DSH CLI and run \`bash start-rc7.2.sh\`.

The package does not contain the bank-controlled DSH main executable, credentials, model secrets, 4A certificates, CAT or database connectivity. It never claims BANK_FINAL or bank field PASS.

## Offline tools carried by each native build

- Python 3.11 + requests / pytest / document processing / PDF / OCR-CV packages
- Node.js 24.9.0 + npm + Playwright 1.65.0 + offline Chromium
- BrowserSkill CLI and extension 0.4.1
- Java 17 + Maven 3.9.16 + seeded Maven local repository
- Allure 2.46.2
- k6 2.3.0
- OWASP ZAP 2.17.0
- ripgrep 15.2.0
- CodeGraph 0.21.0 native binary
- DSH core plugin vendor archive (BrowserSkill DSH plugin and Agent Teams included)

Native release assets with published checksums (Node.js, BrowserSkill, CodeGraph, ripgrep, k6, Allure, ZAP, Java and Maven) are SHA-256/SHA-512 verified before packaging. npm/pip dependencies are resolved for the current native platform and the package manifest plus CHECKSUMS.sha256 bind every delivered file.

## dsh-alpha status

The package contains the pinned dsh-alpha integration metadata and an offline installer contract, but does NOT redistribute upstream dsh-alpha source because the upstream repository currently declares no license and commercial bank redistribution permission is not established. The installer fails closed until a bank-approved source archive and explicit commercial-use + redistribution authorization record are supplied. No source is silently copied into the bank package.

Upstream pin: \`songofhawk/dsh-alpha\`, version \`0.2.2\`, commit \`f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4\`.

## Acceptance boundary

A successful package build verifies a relocated clean-extracted package (Python and Chromium smoke), native executable formats, architecture, full SHA-256 coverage, Python/Node/BSK/CodeGraph/k6/ripgrep/Java/Maven/Allure/ZAP launchability, offline Playwright Chromium, and package-local tool binding. It does not prove the bank DSH CLI, Agent Teams, model providers, 4A, business Journey, database/CAT, Q3 or BANK_FINAL.

## Five additional licensed plugins

Offline native payload `rc7_release/vendor/dsh-additional-plugins-payload.zip` is mandatory: `@michengai/dsh-skills-manager@1.4.1`, `dsh-mnemon@0.5.44`, `dsh-archify@0.1.0`, `@liustack/modlens@3.27.3`, and `graph-memory@1.6.0-beta.17` pinned to GitHub commit `5841b1987c3967998818764c9d4238add5f3aa7c`.

The separate `dsh-error-handling` MIT Skill is carried in `.dsh/skills/dsh-error-handling`. The existing five core + four optional plugins are mandatory on this field variant. To install the five additions into a bank-approved isolated DSH profile (only after a target-side compatibility check), set `PFC_RC72_DSH_HOST_BIN` and run `bash packaging/rc7.2/install-additional-plugins.sh`. All plugin source licenses are included. Profile load/tool invocation and restart/rollback are mandatory BANK_FINAL gates. The DSH alpha source is not bundled pending commercial redistribution authorization.
