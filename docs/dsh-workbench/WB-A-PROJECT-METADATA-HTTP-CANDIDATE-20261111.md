# A：metadata同源HTTP候选（等待真实store准入）

状态：**DRAFT_TRANSPORT_CANDIDATE / REAL_STORE_DEPENDENCY_PENDING / NOT_PRODUCT_QA_ACCEPTED**。A在隔离worktree `a-project-metadata-http`实现，非F验收。依赖F238接受的纯codec63ea；真实009/store候选仍由B独立施工，当前没有产品改名成功的验收声明。

GET/PATCH精确metadata路由及显式metadata_store_factory组合口；默认未配置时503 METADATA_ADAPTER_UNAVAILABLE，零DB调用，不自动导入/启用未经审查的store。生产Host证明仍需真实接入；测试fixture headers不构成SSO或CSRF现场资格。

PATCH独立核可信mutation和原主体write-context，再当前PG项目授权，随后解析受限raw UTF8 JSON body。拒绝未知query、重复/无效长度、Transfer-Encoding、非JSON/错误charset、超过16KiB和不完整body；业务CAS/治理/旧回执/NO_CHANGE仍只能由真实store决定。store在原子rename事务再次检查权限；响应沿已有断线安全出口，不因送达失败重放写入。未知SQL异常仅稳定503。

已实际运行：新增负向HTTP1项包含9个subcase（0.516秒），原header/body断线4项（2.038秒），既有Host/Scope/Directory/write-context/草稿/里程碑及真实PG传输回归160项（66.407秒）通过。160是现有兼容回归，不是新增metadata业务160项；没有伪造成功receipt或业务oracle。当前新测试仅证明未配置路径与负向授权边界，不证明实际metadata framing/DB写入/恢复全面合格。

接续必须：B精确SQL/store/runner/profile审查；组合真实PG store与原生同源server执行正向改名/NO_CHANGE/重名/CAS/旧receipt/主体切换/撤权/丢响应、所有body/framing错误及重启恢复，保持原Scope/R1不变；F独立精确新HEAD。完成前不得将此候选合入为已启用产品功能，不新增最终离线ZIP。

## 隔离的真实数据库联调

组合B候选785790de与真实PG17.6上的009，原生HTTP用真实store完成四项联调（3.702秒）。覆盖改名、隐藏重名、CAS、NO_CHANGE、原主体及历史回执、非法请求、重复长度、不完整body、TCP响应丢失恢复，以及现有batch/R1保持。显式启用metadata adapter时，项目Directory使用含metadata revision的服务端摘要。真实HTTP验证A→B→A后旧游标409，同时返回原v1结构及相同批次目录。

B候选785790de随后在独立PG复验中证实治理并发P1：激活域与新增项目可并发提交，活动域完整分类缺一项。该依赖阻断合入及功能启用。四项HTTP通过只记录隔离联调，治理修复的新精确源必须重新组合并复验；旧失败保留。
