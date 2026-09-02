---
description: 项目初始化向导（当前只允许 canonical truth + G2 intake）
agent: aitest-director
---

先用 `pfc_truth` target=`status` 检查 runtime。项目事实不足时明确列出 KNOWLEDGE_GAP；完成 governed scope/provenance 后通过 `aitest_director` action=`start_test` 创建/恢复 Mission。不要调用 legacy project-init action。
