# A 联合源码完整回归

[run42957130347](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/42957130347) 在精确 `71a50aeeb92ba74468f05d00cb6d33af8a143ef7` 上五个 job 全部 SUCCESS。实际逐 job checkout 日志均定位 71a50ae。四个原生矩阵为 Ubuntu/Windows × Python 3.8/3.11。完整 Ubuntu/真实 Chromium job 的继承 RC7 与 RC7.2 pytest 汇总为 **3111 passed, 4 skipped, 39 warnings, 3224.52 秒**。

已读取本次完整 job 的 JUnit XML。四个跳过分别为实际 Windows disposable 用户与镜像安装、两个旧 Windows CMD final 入口拒绝测试、一个 Windows CMD 入口调用测试。它们仍记为跳过，不能由四个不同原生矩阵 job 自动核销。

先前精确16ae40e8完整 run42893372170 维持 FAILURE（3110通过、1失败、4跳过）。F243复现旧测试失败并限定接受正常调度器fixture修复；新完整回归独立证明精确71a，不转签后续提交。

本次源码联合回归不涵盖尚在隔离分支的009治理修复、metadata HTTP/UI或正式Mission typed实现。真实行内DSH、Windows离线安装与实际Teams仍待现场验收，最终发布门禁保持未完成。
