---
description: 从 R1 Event Stream 继续当前 Mission
agent: aitest-director
---

调用 `aitest_director` action=`continue_test`，传已有 mission_id；若只有明确 scope，则传 scope。Runtime 负责恢复既有 Plan/Task/Attempt 并自动 advance；禁止重新规划来“恢复上下文”。
