# PFC v1.9.4 Golden Usage → Final Implementation Mapping

本文件只记录可核验的使用行为与施工映射。施工 workspace 没有旧 `start-pcc-ai-v19.sh` 原文件，因此旧脚本的逐行 PATH/environment 未取得的项明确标记为 `NOT_PRESENT_IN_BUILD_WORKSPACE`；不伪造逐行内容，也不把 R5 v1.18.20 baseline 混入 R1-R4。

## Bank-proven behavior

银行现场已确认：离线包 → 安装/配置 → 稳定 `D:\PFC` 工程工作区 → 在项目目录启动 OpenCode；旧 v1.9.4 实际使用 Git Bash shell-resolved `opencode web --hostname 127.0.0.1 --port 4096`，现场 Web 能启动，且 v1.9.4 使用的是 1.18.x runtime。当前现场普通 PATH 的 `opencode --version` 为 `1.18.21`，本最终包将该版本作为 exact admission。

## Usage-chain comparison

| Chain point | v1.9.4 Golden Usage | Final implementation |
|---|---|---|
| Package vs workspace | 离线包先安装/配置，包不是长期项目目录 | `PFC-R1-R4-READY-FINAL.zip` 只负责安装；runtime 只在 `D:\PFC\cfg-ai-test-workspace-r1r4` |
| PATH/OpenCode resolution | Git Bash shell-resolved `opencode` 能运行 | 安装先真实 `opencode --version`；要求 `1.18.21`；`command -v` 只记录 evidence，绝不阻塞 shell PASS |
| Working directory | 稳定 `D:\PFC` project context | daily START `cd` stable workspace；Harness 的 OpenCode cwd 为 stable workspace |
| Provisioning | AGENTS/.opencode/skills/tools/runtime 与 Test-Director 可发现 | installer 复制 AGENTS、`.opencode`、`ai-test`、portable runtime、adapter、durable DB、PFC profile，并运行 `install-bootstrap` |
| OpenCode invocation | `opencode web --hostname 127.0.0.1 --port 4096` | `opencode web --hostname 127.0.0.1 --port <valid-positive-dynamic-port>`；CLI 是唯一 port authority |
| Interaction | OpenCode 发现 Test-Director/testing context，使用 durable truth | `opencode.json` default agent 为 `aitest-director`；canonical `pfc.ts` 读写 durable DB；Mission 不依赖 conversation memory |
| Auth ordering | Web 先成功，认证随后 | Web process/listener/HTTP READY 后才进入 AI Runtime；auth/provider/model/LLM/R2 不阻塞 Web |
| R3/Execution | 未完成内容不可伪造完成 | Coverage 39 / Selected 33 / 3 cases / FV-2 保持 `NOT_VERIFIED / QUARANTINED`；real execution `HOLD` |

## Exact old-script items not available

- `start-pcc-ai-v19.sh` 原文：`NOT_PRESENT_IN_BUILD_WORKSPACE`。
- 旧脚本完整 PATH setup：`NOT_PRESENT_IN_BUILD_WORKSPACE`。
- 旧脚本完整 environment diff：`NOT_PRESENT_IN_BUILD_WORKSPACE`。
- 旧脚本精确 OpenCode launcher 文件位置：`NOT_PRESENT_IN_BUILD_WORKSPACE`。

因此本包采用已获银行证明的行为映射，以及可复用的 offline Provision 资产：`install.sh`/`install.ps1` 的 workspace provisioning 语义、`workspace-template/AGENTS.md`、`.opencode` agents/commands/skills/tools、`ai-test/runtime`、portable Python/Browser、PFC profile 与 canonical bridge。未知的旧脚本文本没有被猜测。

## Why previous V2/V3 was wrong

此前包把 package 本身当 workspace，或使用 `<package>/data/opencode-workspace` 直接启动；因此 OpenCode 只看到 bare Web，Test-Director 与 PFC testing context 没有进入稳定项目工作区。本轮删除 package-data runtime 作为长期入口，改成 install/provision 后从 stable workspace 启动。
