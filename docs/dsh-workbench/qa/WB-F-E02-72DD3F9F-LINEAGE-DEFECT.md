# F E02 正式图谱系独立缺陷

唯一被测源72dd3f9f9314ac916a8384ec3f659a18b79625b2，PR149。F隔离worktree、真实临时PG库/nonowner角色与合成持久R1，未写生产R1。

F-E02-01/P1：graph仅核记录release_id与Mission相同，未验证NodeGate→NodeDelivery→MissionNode的Mission/节点/Scope连通。独立临时R1构造M2的FOREIGN_NODE、FOREIGN_DELIVERY，另M1的GATE1(decision PASS)引用这两个外Mission身份；三条均release B1且通过RC72字段合同。请求M1 graph返回该PASS gate，没有谱系503；F期待BusinessError503的测试1/1 FAIL。

复现tests/f_e02_lineage_attack.py指定FAttack.test_f_gate_foreign_node_same_release_rejected，设置WB_PG_TEST_DSN、PYTHONPATH=.:tests，用PG venv Python -m unittest执行。仅同release不足以证明Mission/Scope正确，HOLD总发布结论也不能掩盖错误的正式Gate关联。应只读校验node/delivery/gate/transition/back-edge的引用连通与类型/Mission/Scope，workitems的ETU/Attempt绑定同样检查；不能篡改R1修复数据或伪造状态。

已通知E及A，当前E02_REVIEWED_WITH_BLOCKERS，未给组件接受。修复须新精确源、独立原反例和正向真实谱系复验，不搬运旧CI结果。未改实现或08/09/10。
