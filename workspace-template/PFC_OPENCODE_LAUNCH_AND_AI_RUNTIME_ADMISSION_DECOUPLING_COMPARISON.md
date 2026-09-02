# PFC V3.2 OpenCode launch and AI Runtime admission decoupling

本包只修复已确认的启动 admission coupling。银行现场已证明当前 Git Bash `opencode --version` 为 `1.18.21`，并且 `opencode web --hostname 127.0.0.1 --port <positive-port>` 可以启动。该 proven command、package-owned workspace、positive dynamic CLI port、terminal diagnostic、bounded STOP 与 R3 quarantine 均保持不变。

## State contract

| State | Meaning | Controls Web start? | Controls Mission continuation? |
|---|---|---:|---:|
| `OPENCODE_PROCESS_READY` | package-owned OpenCode process is alive | yes | no |
| `OPENCODE_AUTH_READY` | current Web has completed bank authentication | no | yes |
| `OPENCODE_PROVIDER_MODEL_READY` | Provider and Model are available | no | yes |
| `LLM_RUNTIME_READY` | real LLM response is verified | no | yes |
| `R2_SESSION_READY` | R2 session create/continue/resume is verified | no | yes |
| `PFC_MISSION_AI_READY` | all AI Runtime gates are satisfied | no | yes |

## Correct START order

`package-owned workspace` → `positive free port` → `valid generated config` → `opencode web --help` → real shell-resolved `opencode web` subprocess → process/listener/HTTP READY → browser → START returns success. Auth, Provider/Model, LLM and R2 are probed as state, not as Web startup admission.

## Correct post-auth order

The user completes authentication in the already-running Web and then runs `STATUS`. STATUS probes the same PID, port and package workspace without restarting. Provider/Model readiness permits the real LLM probe; LLM readiness permits R2 session create/continue/resume; only then can PFC Mission continue.

## Removed failure mode

Previous START entered an Auth/Provider/Model/LLM wait loop and could trigger STOP/RESTART/taskkill even though Web was usable. V3.2 removes that START blocking path: no Enter loop, no normal-auth taskkill, no default restart, no raw traceback.

## Preserved field-validation boundaries

Coverage 39 / Selected 33 / 3 cases / FV-2 remain `NOT_VERIFIED / QUARANTINED`; Starlink, Requirement Intelligence, Coverage, Cases and real execution are out of scope. `PFC_REAL_EXECUTION_ENTRY=HOLD`.
