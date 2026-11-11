# E：Scope HOLD真实目标域修订证据

原ce6add35保留失败：F213/6d3cf649bca841fded32e3b2021c357c663e17ad与D214/898098d2f432d86b1ac70d954578fdbaaa23919d（含a934初报告）完整读取；首次fetch猜错F分支名失败，随后通过PR元数据得到正确分支并读取报告全文。报告实际临时R1验证M1._persist(M2)丢Scoped M2字段及M1.start(T2)推进Scoped M2任务；本轮引用它们为设计反例，不冒称本轮未实现guard已运行通过。

本轮真实源码复核Control全部列内写分支、control_plane TaskScheduler.start/output/lease、GapRepairPlanner.plan及派生repair/repro/qualification任务。新增§2.1规范实际目标集合（self/input/被覆盖旧对象所属），批量首写前全预检，明确Attempt本链无直接append不虚构映射。既有有效unbound跨目标行为不一概硬化；已有零副作用错误保留，不可解析目标显式新TARGET_UNRESOLVED HOLD，absent Mission例外仅合法新bootstrap。

本轮仅设计/证据；diff检查通过，不运行不存在的产品保护测试，不改runtime/正式模型/R1/008/08–10。需B/D/F对新完整SHA审阅后才准入实现。已有并发、direct scheduler/raw、Field-start上游及mtime边界继续有效。
