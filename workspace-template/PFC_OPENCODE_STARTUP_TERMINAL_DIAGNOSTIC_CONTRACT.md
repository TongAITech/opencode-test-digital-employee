# PFC OpenCode Startup Terminal Diagnostic Contract

`PFC_OPENCODE_STARTUP_TERMINAL_DIAGNOSTIC=MANDATORY`。START 失败时当前 Git Bash 直接打印 compact、可拍照摘要：candidates path/launcher type/version、selected exact path/version、workspace、host/port、launch command、PID/process state、exit code、failure class、stdout/stderr tail、listener、legacy instance、auth phase、human-readable next action。

完整 `logs/startup/<timestamp>-<unique>/` 继续保留；Diagnostic ZIP 为 `OPTIONAL` artifact。终端摘要不得打印 token、cookie、password、authorization header 或 secret。
