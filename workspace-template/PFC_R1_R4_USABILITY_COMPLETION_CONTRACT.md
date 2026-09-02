# PFC R1-R4 Ready Final Usability Completion Contract

## Two user phases

The Product Owner only runs `./INSTALL-PFC-AITEST.sh` once per extracted package, then `cd /d/PFC` and `./start-pfc-ai-r1r4.sh`. No manual JSON, environment variables, project selection, agent selection, or internal IDs are required.

## Provisioning and preflight

Installation materializes the complete project workspace at `D:\PFC\cfg-ai-test-workspace-r1r4`, including `AGENTS.md`, `.opencode/agents`, Test-Director, commands, skills, tools, `ai-test` runtime, adapters, profile, durable DB, and the canonical bridge. Missing mandatory material fails INSTALL.

START changes into that workspace, prints `pwd`, executes `pfc_truth status`, verifies all mandatory paths and OpenCode `1.18.21`, and only then launches Web. The launch shell itself performs `cd + pwd + exec opencode web`; the package root and `data/opencode-workspace` are never runtime workspaces.

## Config and state

The installer recursively merges the template with any existing stable-workspace `opencode.json`, preserves provider-independent fields (`agent`, `instructions`, `plugin`, `tool`, `permission`, `mcp`), applies only the runtime overlay, and makes CLI positive dynamic port the sole port authority. `server.port=0` is forbidden. All package-owned text is strict UTF-8; an encoding failure prints the exact path, expected encoding, byte offset, detected encoding, and failure class without a traceback. Existing stable-workspace `opencode.json` is external input and uses an explicit UTF-8/GB18030 decoder. Copy, merge, bootstrap, `pfc_truth`, and bridge self-check run in `.cfg-ai-test-workspace-r1r4.installing`; only a complete PASS is promoted to the stable workspace.

Workspace/Agent readiness is independent from authentication. OpenCode Web additionally requires explicit project/session directory proof; if that proof is unavailable, the package fails closed and keeps `OPENCODE_TUI` as the primary interactive surface. Authentication, provider/model, LLM, and R2 are later AI Runtime states. STOP checkpoints durable mission/session context; the next START can continue it.

Current-version truth is read from durable release/source/deployment state. Until that state is synchronized, the canonical answer is `CURRENT_VERSION_RECON_REQUIRED`; bootstrap/history values are not current truth. Coverage, StandardTestCase, R3, and real execution remain quarantined/HOLD.
