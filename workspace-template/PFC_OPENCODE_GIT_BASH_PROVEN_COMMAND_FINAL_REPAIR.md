# PFC Ready Package V3 — Git Bash proven-command final repair

银行现场已重复证明当前 Git Bash 中 `opencode --version` 返回 `1.18.21`。本包的唯一 runtime admission 是当前 shell 命令 `opencode`；`command -v opencode` 只记录 resolved path evidence，不构成 absolute-file、file-type、extension 或 candidate admission。

| Launch chain | Final contract |
|---|---|
| Admission | 同一 Git Bash 执行 `command -v opencode` 与 `opencode --version`；版本必须精确为 `1.18.21`，否则 `OPENCODE_VERSION_MISMATCH` 并停止 |
| Runtime binding | 只使用 shell-resolved `opencode`；禁止 absolute path pinning、file-type validator、CMD/PS1 extension 判断、candidate enumeration、multi-version resolution 与 fallback |
| Workspace | `cd <package-root>/data/opencode-workspace`；禁止 `D:\PFC\cfg-ai-test-workspace-v16` |
| Port/config | 选择 `1..65535` free loopback port；生成 package-owned config；不写 `server.port`，CLI `--port` 是唯一 authority |
| Web launch | 在同一 shell resolution 中执行 `opencode web --hostname 127.0.0.1 --port <positive-port>`；真实 subprocess，capture PID/stdout/stderr/exit code |
| Readiness/browser | process alive → listener → HTTP ready → browser；任一失败不打开 browser |
| Authentication | Web READY 后只提示一次认证；Enter 后同一 server/instance 自动复探；若需 reload credentials，最多自动重启一次并再次复探，不再 Enter loop |
| Provider/Model/LLM/R2 | 只读取当前 Web instance 的 live Provider/Model；发送最小真实 message；验证 session create/continuation/resume 后停止 |

本包不是 Recon 包，不进入 Starlink、Requirement Intelligence、Coverage、Cases 或真实执行；`PFC_REAL_EXECUTION_ENTRY=HOLD`。
