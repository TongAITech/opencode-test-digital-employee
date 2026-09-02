# PFC Windows OpenCode CMD Shim Resolution and Real Web Launch Contract

本包只修复真实银行 Windows + Git Bash 已确认的 `PFC_WINDOWS_OPENCODE_CMD_SHIM_RESOLUTION_GAP=CONFIRMED`。

Harness 会枚举 `PATH/PATHEXT`、`where.exe opencode`、Git Bash `type -a opencode` 与已知银行安装路径；候选矩阵逐项记录 exact path、launcher type（`.EXE`/`.CMD`/`.BAT`）、实际版本和 source。`D:\Program Files\opencode\opencode.CMD` 是合法 launcher identity，不会因不是 `.EXE` 被丢弃。Windows `.CMD/.BAT` 会经由 `COMSPEC /d /s /c` 使用正确 quoting 调用；底层 target 可作为辅助证据，但不替换 selected launcher identity。

R1-R4 只使用本包冻结的兼容策略：expected/compatible version=`1.14.22`，source=`PFC_R1_R4_FROZEN_COMPATIBILITY_EVIDENCE`；不应用 R5 baseline。无兼容候选时明确 STOP，error=`OPENCODE_VERSION_MISMATCH`。

通过后 Harness 在包内 `data/opencode-workspace` 启动自己的 Web，使用新的 loopback 动态端口，绝不 attach/kill 旧 `127.0.0.1:4096` 或旧 workspace。只有 process/PID、selected launcher、version、Web listener、health/readiness、workspace 与 URL 全部一致，才记 `PFC_OPENCODE_REAL_WEB_LAUNCH=PASS`。

若银行认证未完成，START 保持等待并显示：`OpenCode 已启动。请在当前打开的页面完成银行认证。完成后回此窗口按 Enter。` 不退出；Enter 后重新验证同一 PID、port、workspace，再继续 Provider/Model、真实 LLM 与 R2 session。

用户唯一入口仍是 `./START-PFC-FIELD-VALIDATION.sh`。本包不读取 Starlink，不生成新的 Requirement Intelligence、Coverage 或 StandardTestCase；`PFC_R3_REQUIREMENT_SOURCE_REPAIR_ENTRY=HOLD`，`PFC_REAL_EXECUTION_ENTRY=HOLD`。
