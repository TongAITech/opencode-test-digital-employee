---
description: G3 标准案例设计评审并进入 Human Review
agent: aitest-evaluator
---

仅对当前 Router-bound Case Design 调用 `aitest_evaluator` action=`evaluate_case_design`，通过 frozen R3.4 做设计质量评审并创建 Human Review。本命令自身不执行 SUT；评审通过后的真实执行由 G4 Router-bound Executor 负责。不得确认 Defect；G5 confirmed-defect truth 继续 HOLD。
