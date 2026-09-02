---
description: 创建或恢复需求/版本测试 Mission
agent: aitest-director
---

收集 project/release/requirement 等 governed scope 与 provenance 后调用 `aitest_director` action=`start_test`。同 scope active Mission 会自动恢复；只有用户明确要求独立新 Mission 才设置 `force_new_mission=true`。
