# A 连续施工阶段回归：真实运行只读界面

角色A，不替代独立F。当前轮次正向合入HTTP、日历及只读运行界面；不修改work/rc7.2，不构建最终离线ZIP。

| 精确测试源 | 真实执行 |
|---|---|
| b6d93e41b98796e82650645c019fe1e883030862，A合入后 | Node117/117；真实PostgreSQL/HTTP/Chromium8/8（34.995秒）；既有F反例由A复跑5/5（27.150秒，不新增独立签署）；轻量566发现、273执行通过、293明确跳过 |
| f1b6b24e233bae2adb43d2ae60dc84cfb6523c53，联合候选 | 真实PostgreSQL17.6/Psycopg3.2.13，223/223（113.722秒）；E01/E02/lineage/mount_auth 76/76（47.386秒） |
| 同f1远端 | W0 42869429579、真实浏览器42869429542、PG 42870060011、E 42870065289均SUCCESS |
| 同f1广泛平台资格 | ABCD-v4 run42870053745：Ubuntu/Windows × Python3.8/3.11四job已SUCCESS；完整继承RC7/RC7.2源码及Chromium job仍运行。未记录全量PASS，不移用7586a80c旧结论 |

b6与f1的rc7_admin/rc7_runtime/tools/tests/.github代码树差异为空，差异是台账与审查报告；这项核对不被当成跨SHA QA转签。上表各结果只属于其明确SHA，后续新功能与候选另验。

F当前组件报告已集成：HTTP47950777→904493cf/#183；日历1492a572→3ac4d157/#187；运行界面f1b6b24e→7bbaa5a6/#193。F实际新增受控文件Evidence哈希与NodeGate PASS仍HOLD、部分三路响应/来源漂移/外Mission Gate/R1坏Gate拒绝、非空筛选零请求、375px与无POST/legacy/storage等独立反例；fixture绑定不是正式生产创建。F首轮Evidence夹具缺release_id在HTTP前被拒，修夹具重跑记录保留，未修被测代码。

B/D独立V3复审先保留真实P1（来源字段/事务端口/authority域、首次PREPARE、结果分类），E新04ca9716修订后B94ee70bc/#192、Dcf74b3d3/#194及F35c43a55/#196仅准入纯组件。正式008/最终锁端口/HostFence/封闭writer/typed模型依旧需要具体增量审查与真实实现证据。

后续在独立分支继续：E纯codec #195旧c4facd2c被F发现不可hash SST输入异常边界P1，E已真实复现修复，新a9758687正在独立复验；原失败#197不删除。B正在实现只读真实PG完整来源预览，不提供正式admission。所有真实Host/SSO、现场Windows/离线与实际并发恢复仍FIELD_NEEDS_BANK_TRANSFER，RELEASE_NOT_APPROVED。
