# PFC post-auth process lifecycle contract

- Same-instance auth reprobe: first and mandatory after Enter
- Unnecessary restart: removed
- Restart trigger: explicit runtime credentials/config reload only
- Restart maximum: one
- STOP: package-owned handle/PID, graceful first, bounded timeout, single-PID fallback without `/T`
- Stop timeout: controlled error, no hang, no raw traceback
- Proven runtime contract: Git Bash `opencode`, version `1.18.21`
