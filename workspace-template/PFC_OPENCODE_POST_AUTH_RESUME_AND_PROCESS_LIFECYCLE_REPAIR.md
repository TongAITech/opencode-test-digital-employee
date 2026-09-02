# PFC post-auth resume and process lifecycle repair

本包只修复银行现场已确认的 post-auth lifecycle failure：同步 `taskkill /PID <pid> /T /F` 卡死。OpenCode 版本、Git Bash proven command、dynamic port、package workspace 和 R3 quarantine 均保持不变。

## Auth flow

Web READY → 用户认证 → Enter → 输出 `正在验证认证状态...` → 针对 same host/port/PID/workspace 的当前实例直接 probe Provider/Model。Provider ready 时不重启；仅当 runtime 明确返回 credentials/config reload required 时，才允许一次 managed restart，并自动再次 probe。不会循环要求 Enter。

## Process lifecycle

START 保留自己创建的 process handle、launcher PID 和 Web listener PID。停止优先使用 handle graceful termination，并以 bounded timeout 等待；Windows fallback 只允许对已确认 package-owned 的单个 PID 执行带 timeout 的 `taskkill /PID <pid> /F`，禁止 `/T` process-tree kill。任何 timeout/restart failure 都返回 controlled result，不向 Product Owner 输出 Python traceback。

## Scope

`./STOP-PFC-FIELD-VALIDATION.sh` 使用同一 bounded lifecycle。Coverage、StandardTestCase、Starlink、Requirement Intelligence 与真实执行继续 HOLD。
