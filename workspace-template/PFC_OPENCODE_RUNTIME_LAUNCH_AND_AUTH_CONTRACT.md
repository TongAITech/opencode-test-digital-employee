# PFC OpenCode Runtime Launch and Authentication Contract

用户只执行 `./START-PFC-FIELD-VALIDATION.sh`。Harness 负责枚举并选择 exact OpenCode binary，建立 package-owned workspace，按所选版本的 `web --hostname/--port` 能力启动 Web，捕获 PID 并等待 Web readiness。

认证未完成时，Harness 自动打开同一个 package-owned Web URL，进入可恢复的等待状态，用户只需在页面完成银行认证并回到窗口按 Enter。Harness 会复核 binary、version、PID、server、workspace、host/port 后，在同一个实例上继续 Provider/Model、真实 LLM 和 R2 session create/resume。

旧 4096、旧 workspace、其他 PID 或其他 OpenCode 不会被 attach、kill 或迁移。当前 R3 Coverage/Cases 继续 `NOT_VERIFIED / QUARANTINED`，真实执行继续 HOLD。
