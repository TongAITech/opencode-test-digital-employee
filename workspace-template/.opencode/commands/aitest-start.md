---
description: 初始化或恢复当前 AI 测试 Mission（G2 canonical）
agent: aitest-director
---

先读取 canonical status。对用户明确提出的测试目标，构造 source-aware R2.2 request，调用 `aitest_director` action=`start_test`。Runtime 会按 scope 自动 RESUME 同一 active Mission；不得因新会话重新创建 Mission。
