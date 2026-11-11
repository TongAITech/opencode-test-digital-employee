# F 独立复验正式创建回执恢复

候选 [#307](https://github.com/TongAITech/opencode-test-digital-employee/pull/307) 精确提交 `2f9a8141453c0106cf11ce54430edd17922723a6`。接受范围为固定字节快照的独立回执恢复组件。

- 隔离工作区运行本地正式事件及回执测试 9 通过。核实 [CI 43071261629](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43071261629) 两个 job 实际检出精确候选，Python 3.8 和 3.11 各通过 42 项。
- Ruby 独立重建请求摘要、正式事件原字节和回执。向量含中文、内部换行、非 BMP 字符及 bigint 最大值。716 字节回执逐字一致，摘要为 `2ca61c539aa8f00f608538a06ba3946a00021f7d0ea6f4ec31de668e9f3d75be`。临时账本冷读复算结果一致、原文件字节不变、合法缺键与空账本返回空结果。
- 十类独立正式冲突逐项拒绝，包括原 K、Mission、运行 release、运行批次、操作、映射、绑定、回执、event_id 和 seq。另验证跨旧事件的归一化 Mission、event_id 和 seq 冲突、外权威记录，以及首个有效命中后的缺类型、重复 JSON 键与截断尾部。错误均未返回回执。
- 调用端仍须核验请求键的完整引用域、当前查询权限、固定物理账本来源与完整语义资格。该组件的空结果只适用于输入快照；生产查无结果、原权威不可用及正式创建准入仍依 V3 分别处理。
