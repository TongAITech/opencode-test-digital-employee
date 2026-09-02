---
description: G1-G4 Runtime/Truth 与当前 Mission 前置状态检查
agent: aitest-director
---

读取 canonical `aitest_director` status 与当前 Mission 的 `aitest_g4_director` status，确认 R1 Event Stream、Plan/Task、Router/Attempt/Session、G3 governed test assets、G4 capability/auth/approval prerequisites。只报告 durable truth 与缺口，不写 legacy runtime，不猜 Environment/API/Browser/DB/CAT binding。G5/G6 继续 HOLD。
