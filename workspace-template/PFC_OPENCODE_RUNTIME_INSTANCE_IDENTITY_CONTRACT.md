# PFC OpenCode Runtime Instance Identity Contract

本包的 START 只接受一个可复核的 `PFC_OPENCODE_INSTANCE_IDENTITY`：`binary_path`、`version`、`workspace_root`、`PID`、`host`、`port`、`launch_mode` 必须绑定到同一 OpenCode Web 实例。

启动前会枚举所有 PATH 中的 OpenCode 候选并记录版本；多个候选、未配置 approved version、版本不一致、端口上的旧实例或 workspace 无法证明时均为 STOP/REPAIR。URL 可达不等于实例正确。旧 workspace 不会迁移或复用。

认证、Provider/Model、LLM、R2 session/resume 使用已绑定 identity 的 endpoint；不会重新发现另一个 4096、另一个 PID 或另一个 workspace。所有 R3、Coverage、StandardTestCase 和真实执行仍保持 HOLD。
