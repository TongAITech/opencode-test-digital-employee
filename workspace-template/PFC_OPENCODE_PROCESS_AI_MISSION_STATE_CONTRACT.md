# PFC OpenCode Process / AI Runtime / Mission State Contract

- OpenCode Process: shell-resolved `opencode` 1.18.21 + stable project workspace + positive port + live PID + listener + HTTP READY。
- AI Runtime: Auth → Provider/Model → real LLM → R2 session；这些状态在 Web READY 后独立观察，不阻塞 Web。
- PFC Mission: 只有 `PFC_MISSION_AI_READY` 才能继续；Coverage/Cases/R3 与 `PFC_REAL_EXECUTION_ENTRY=HOLD` 不变。
- Test-Director: 由 `.opencode/agents/aitest-director.md` discoverable；canonical `pfc.ts` 读取 durable SQLite truth。Conversation memory 不是项目 truth。
