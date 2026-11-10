# E01 PostgreSQL / HTTP / R1 只读组件

基线：`e901b2d8bda2e53f12a3c90028deeb54071f6741`，包含 B06 `f144f1a1` 与 F138 接受报告。
实现：E01Service、B06 server 可选 quality_service_factory；GET `/api/workbench/v1/projects/{p}/release-dates/{date}/quality?batch_id=...&mission_id=...`。HostIdentity 仅由服务端 provider 派生，缺 provider 503，拒绝客户端 principal。接口只读，不提供命令写入口。

先完成真实 PostgreSQL B06 授权和所有分页，再读已有 R1 的有界不可变字节副本，重放正式 TruthRuntime；最小唯一 Mission 身份校验 project+batch 后才查询关联明细。未绑定 legacy Mission/跨域/缺失统一403；R1缺失、截断、过大、不可用503，不创建原文件。原始R1绝无append/修复写入。末尾再次检查真实PG ACL、关联/权限修订，变化拒绝。

truth_revision为被读取完整R1字节的sha256，as_of为响应构建时UTC时间；业务source_refs保留，R1引用来自正式scoped projection。Evidence仅在显式受控根目录回读file引用并复算hash，不访问网络；HASH_VERIFIED_ONLY不是provenance或Gate通过。NodeGate仍UNKNOWN、发布HOLD，E02正式Gate投影与后续控制面仍待施工。

真实本地结果：PostgreSQL17.6，`WB_PG_TEST_DSN='host=/tmp/dsh-pg-371f43f0 port=55432 dbname=postgres' ../pg-environment-venv/bin/python -m unittest discover -s tests -p 'test_dsh_workbench_e01_postgres.py'` **35/35 PASS**（包含继承B06回归）；E既有合同 **82/82 PASS**。新增真HTTP/R1读取、全页、撤权、缺Host、原始R1字节不变、缺文件恢复、新server冷启动、legacy无绑定403、截断503及本地hash篡改/路径越界反例。

首次联调503揭示真实B06行继承envelope身份，而旧DTO要求每行project/batch；已在可信服务边界显式展开授权envelope以兼容DTO，不凭名称或release_id推断。最初2失败日志保留于本机`/tmp/wb-e01-pg.log`随后被最终回归覆盖，故历史失败仅作本说明而非可下载证据。

测试使用持久synthetic R1和显式服务端Host测试provider，不是银行现场。没有修改Mission模型或正式事实边界；旧Mission缺绑定继续拒绝。F独立QA待验，DSH1.18.26、Windows、现场与完整自主执行NOT_RUN。08/09/10由A唯一维护。
