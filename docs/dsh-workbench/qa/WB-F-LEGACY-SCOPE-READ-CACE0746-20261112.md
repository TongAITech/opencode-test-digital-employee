# F 独立验收旧读取接口拒绝正式 Scope 标记

接受 #312 精确提交 `cace07465d9961346b44e0404a81f6b33be230a8` 的旧 Workbench E01/E02 读取围栏。独立工作树连接真实 PostgreSQL 17.6，E01/E02 组件共 74 项通过，零跳过，34.248 秒。独立旧 Scope 验证套件 34 项通过。

同一独立真实 PostgreSQL、HTTP 与临时 R1 对照探针覆盖 quality、graph、workitems 三条接口。旧 `9d1b11a77e76db5f9f0f2c50f15b563d2c3743eb` 对带对象 scope_binding、空对象 runtime_batch_mapping 或显式 null scope_binding 的三种冷回放记录，各接口均返回 200 并查询明细。新版本九次全部返回 403 FORBIDDEN，每次只查询 rc7_mission。两版普通平面绑定三条入口均返回 200，每次对照保留原 R1 字节。

验收限于上述三条读取入口及这两个标记的存在判定。正式事件注册、生产读写、权威来源及其他 Admin/Host 入口需分别验收。
