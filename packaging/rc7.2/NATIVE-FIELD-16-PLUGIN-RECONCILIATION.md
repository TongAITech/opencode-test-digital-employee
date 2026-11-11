# RC7.2 Native Linux/macOS — 16-component reconciliation and release gates

> Audit recorded on 2026-11-12 for PR #270. This is a **source-and-CI reconciliation**, not a bank field qualification. Always reread the current remote HEAD and bind actual artifacts and logs to their own SHA before changing a status.

## Scope and current identity

- PR: https://github.com/TongAITech/opencode-test-digital-employee/pull/270
- Work branch: `work/rc7.2-native-linux-macos-20261112`
- Target: `work/rc7.2-field-validation-transport-20261111`
- First curl conflict fix commit: `acee5d18bb983efa66242d6d8e135b2662a842ba`; this commit superseded `4f06e7fa`.
- Next dsh-archify GitHub source build fix: `22ac99bd63a3cd98d11f65b4ea690432ab66dad2`.
- Build matrix triggered on that SHA: https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43116631310
- Prior matrix evidence: https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43116035276

**Gate terminology**: `ACQUIRED_ON_OLD_SHA` = build log showed payload acquisition, **not** that the final archive contains it; `CODE_ONLY` = implementation/source reference, not validated complete; `HOLD` = deliberate licensing/compatibility block; `FIELD_PENDING` = no authorized native bank DSH host and no bank restart/restore evidence. Never convert these to `PASS` without an exact-SHA run and artifact evidence.

## 16-component check matrix

| # | Component | Required version / identity | Current grounded status | Completion requirement |
|---|---|---|---|---|
| 1 | dsh-routing-suite | resolved 0.1.2 on old CI | ACQUIRED_ON_OLD_SHA | Exact-HEAD offline payload + DSH profile activation + route tool smoke |
| 2 | @wxg-prc-cpg/browser-skill-dsh-plugin | 0.4.1 | ACQUIRED_ON_OLD_SHA | Native BSK CLI/ext 0.4.1 and actual browser tool execution |
| 3 | dsh-context | resolved 0.83.1 on old CI | ACQUIRED_ON_OLD_SHA | Offline install, peer compatibility and tool invocation |
| 4 | dsh-plugin-bridge | resolved 0.5.2 on old CI | ACQUIRED_ON_OLD_SHA | Offline activation, native host compatibility |
| 5 | @nanmicoder/dsh-agent-teams | resolved 0.1.29 on old CI | ACQUIRED_ON_OLD_SHA | Join/schedule/teardown/restart/session recovery without regressions |
| 6 | @perrylink/dsh-plugin-doctor | resolved 0.7.11 on old CI | ACQUIRED_ON_OLD_SHA | DSH profile and self-diagnosis tool execution |
| 7 | dsh-vision-router | resolved 3.2.0 on old CI | ACQUIRED_ON_OLD_SHA | Check native sharp and peer dependencies at field host |
| 8 | dsh-plugin-anydoc | resolved 0.1.0 from GitHub on old CI | ACQUIRED_ON_OLD_SHA | Verify source license and actual document tool invocation |
| 9 | dsh-memento | resolved 0.5.30 on old CI | ACQUIRED_ON_OLD_SHA | Session write/read/restart evidence |
| 10 | dsh-error-handling | separate Skill, not npm | CODE_ONLY | Pinned Skill snapshot, LICENSE, packed path, field load |
| 11 | @michengai/dsh-skills-manager | 1.4.1, Apache-2.0 declared | CODE_ONLY | Production dependency closure and license files, archive inspect, DSH load |
| 12 | dsh-mnemon | 0.5.44, MIT declared | CODE_ONLY | Production dependency closure, archive inspect, DSH load |
| 13 | dsh-archify | 0.1.0, MIT declared, GitHub pin `8fc7ba557981af978578e2dd13e6c6ad8df53a7d` | FIX_SUBMITTED_NOT_VALIDATED | Build Skill staging, license/ZIP/deps and DSH activation |
| 14 | @liustack/modlens | 3.27.3, MIT declared | CODE_ONLY | Production dependency closure, archive inspect, DSH load |
| 15 | graph-memory | 1.6.0-beta.17, GitHub pin `5841b1987c3967998818764c9d4238add5f3aa7c` | CODE_ONLY | Built JS entrypoints, transitive dependencies, offline tool smoke |
| 16 | dsh-alpha | 0.2.2, GitHub pin `f417e90ddd0e20f08b82e0b79a8c29fdad45c8f4` | **HOLD — LICENSE_HOLD_NOT_BUNDLED** | Explicit commercial use + redistribution authorization; approved archive; separate install and real load |

Do not count #16 as installed. The correct outcome for an unauthorized bank distribution is a fail-closed **HOLD** and no upstream source bytes. All other statuses remain provisional until archive-level and field-level verification.

## Build failures established so far

1. Run 43115649654, commit `4f06e7fa`: both Linux jobs failed when Rocky 9 attempted to install full `curl` alongside `curl-minimal`; macOS jobs cancelled by newer push; zero artifacts.
2. Commit `acee5d18` changed both dependency-install statements to `curl-minimal`; prior prepared blobs are superseded by live HEAD.
3. Run 43116035276, commit `acee5d18`: Linux x86_64, Linux ARM64 and macOS ARM64 reached plugin acquisition and failed on npm `E404` for `dsh-archify@0.1.0`; macOS Intel cancelled by newer push; zero artifacts.
4. Commit `22ac99bd` introduced source-commit acquisition for dsh-archify; build 43116631310 had begun but had **no confirmed completed native packages** at the time of this audit. Review the final jobs and logs, never infer PASS from queued/running.
5. PR #270 description still cites Rocky Linux 8 / glibc 2.28. Actual CI and scripts use Rocky Linux 9 / glibc >= 2.34. Update PR copy before delivery.

## P0 checks before accepting any native Artifact

- Build exits 0 and uploads a nonempty **matching-SHA** `.tar.gz`, `.sha256`, evidence and tool version inventory; failed jobs cannot provide an accepted artifact.
- Every ZIP and archive has an exact inventory and platform-native executable inspection. No Windows PE signatures or .exe/.dll/.cmd/.bat/.ps1/.msi files, including nested npm payloads.
- Python 3.11 can run after moving the extracted tree to a different absolute path; imported OCR/CV native extensions match the platform. Node/npm/pnpm, BrowserSkill CLI/extension, Chromium and offline Playwright smoke actually execute without network.
- Java 17, Maven 3.9.16 offline seeded test, Allure 2.46.2, CodeGraph 0.21.0, ripgrep 15.2.0, ZAP 2.17.0, k6 actual execution. **k6 1.8.2 in native script differs from user-stated Windows 2.3.0**; explicitly resolve or document a tested capability exception before final signoff.
- All five new licensed plugins' production/transitive dependencies, source identity, licenses, native binary closure and offline activation verified, not just tarball pack or manifest hash.
- DSH CLI plugin-profile syntax must be tested against an approved **matching native DSH host**. No repository-only simulation may count as profile load, actual tool invocation or Agent Teams regression PASS.
- Native clean re-extract and full file checksum validation must be repeated on that architecture; restart, session restore, rollback and authorization-gated flows remain separate.
- Preserve previous enhancement GAPs. Exclude dsh-weknora (not deployed), dsh-qa (independent workbench), restricted GitNexus/PolyForm assets and unauthorized dsh-alpha upstream source.

## Compatibility and final gates

Linux x86_64 and ARM64 are built in Rocky 9 userspace; advertised baseline **glibc >= 2.34**, kernel >= 4.18, target native library prerequisites and target-host preflight. Candidate RHEL/CentOS Stream 9/Kylin/UOS systems require their own qualification; CentOS 7/8 and Rocky 8 are not certified by these builds. macOS Intel/ARM64 require separate native archives and macOS >= 14. No Windows binaries may be renamed to masquerade as native.

Native build PASS is distinct from `FIELD_VERIFIED` and `BANK_FINAL`. The latter remain false until the approved bank native DSH host, model/4A/BrowserSkill/Agent Teams, actual tools, offline restart/recovery and R1 evidence pass applicable Q3–Q9 gates.

## Next evidence update template

For each target, append: `target | source_sha | run_id | job_id | job_conclusion | artifact_id | artifact_size_bytes | tar_sha256 | clean_unpacked | tool_smoke | plugin_16 | licensing_hold | field_q3_q9 | evidence_url | open_gap`. Use `FAIL`, `SKIP`, `HOLD` distinctly. Never manufacture missing values.
