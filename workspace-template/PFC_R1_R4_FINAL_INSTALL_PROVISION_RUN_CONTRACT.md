# PFC R1-R4 FINAL Install / Provision / Run Contract

## User phases

1. fresh extract 后只执行 `./INSTALL-PFC-AITEST.sh`。
2. 安装完成后执行 `cd /d/PFC`，再执行 `./start-pfc-ai-r1r4.sh`。

Product Owner 不需要编辑 JSON/config/env，不需要搬出内部 ID，不需要执行 debug CLI，也不需要运行 AITEST/FV cmd。

## Installation

Installer 验证 ZIP manifest、Git Bash、shell-resolved OpenCode exact `1.18.21`、portable Python/Browser、4 个 PFC Git repositories，然后把完整 workspace template provision 到 `D:\PFC\cfg-ai-test-workspace-r1r4`。它注册 PFC/BLOAN-PF1.0.0/FAT2/STBB19-234/240/242/5 SST/4 repositories/FAT2/Starlink single-environment durable baseline，并冻结旧 R3/Coverage/Case 状态；安装阶段不读取 Starlink。

安装先对 ZIP 内全部 package-owned 文本资产执行严格 UTF-8 audit；decode 失败只输出 exact file path、expected encoding、byte offset、detected/best-verified encoding 与 failure class，不输出 Python traceback。已有 stable workspace 的旧 `opencode.json` 属于外部输入，使用显式 UTF-8/GB18030 source-aware decoder，并在 staging 中重写为 UTF-8。整个 copy/config merge/install-bootstrap/pfc_truth/bridge self-check 都在 `.cfg-ai-test-workspace-r1r4.installing` 完成；失败自动清理 staging，成功后才 promote，已有 stable workspace 不被半成品污染。

## Runtime

Daily START 的 cwd、Harness `WORKSPACE_ROOT`、OpenCode subprocess cwd、`AGENTS.md`、`.opencode`、`ai-test`、runtime/config/adapters、durable DB 与 PFC profile 全部指向 stable workspace。ZIP 根目录不是 runtime workspace；`data/opencode-workspace` 不再作为最终包的运行目录。

OpenCode Web 顺序为：workspace → free port `1..65535` → valid `opencode.json` → `pfc_truth status` → `opencode web --help` → real shell-resolved subprocess → PID/listener/HTTP READY → explicit `/project/current?directory=...` → explicit `/session?directory=...` → verify `aitest-director` → open `/<base64url(directory)>/session/<id>`。Web READY 后才进行 auth/provider/model/LLM/R2；PFC Mission continuation 与 real execution 仍 gated/HOLD。

终端启动失败摘要仍是 mandatory；完整 startup trace 保留，Diagnostic ZIP 只是 optional。摘要不得打印 token/cookie/password/authorization header/secret。
