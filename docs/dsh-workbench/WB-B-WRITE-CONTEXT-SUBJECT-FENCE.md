# B 写入主体域恢复安全增量

B_DESIGN_ACCEPTED_FOR_SUBJECT_BINDING_ONLY：精确审查D/C合同6661e80de31292fbbc766c37fbe008bae41dfd65并接受接口与服务端顺序。不代D/C/F签署，不声明SSO/session epoch或现场能力。实现基线d0ee15ad，独立wb-write-context / work/dsh-wb-write-context。

真实P1：Alice成功提交后丢响应，Bob拥有同项目写权时重放原pending，可落到Bob新幂等域造成重复。修复新增只读GET /api/workbench/v1/write-context，可信Host provider先认证，返回{schema:'dsh-workbench/write-context/v1',write_context:'wctx1.<opaque HMAC>'}；不输出principal。以持久cursor secret为key，显式domain separation和可信principal规范JSON生成；不签权、不替代CSRF/Origin/项目ACL或正式租约。

所有资产POST/PATCH/DELETE/restore须X-DSH-Write-Context，Host mutation证明先独立校验，再常量时间比对当前主体域，全部在DB连接/业务变更/幂等回执读取前完成。缺token403 WRITE_CONTEXT_REQUIRED，错token409 WRITE_CONTEXT_CHANGED；无Host503，无效身份403，密钥配置无效503。读context不建立DB连接，不新增CORS，响应no-store，token不放URL/日志或localStorage。

Alice旧token在Bob主体下必须拒绝，即使Bob确有项目写权；这不能证明原Alice未提交，客户端须保持UNKNOWN/HOLD。旧pending无context不能补当前token；key轮换同样HOLD，不自动换UUID或改payload。稳定key真实停服重启后Alice可携原token/原request_id对账原回执，资产/outbox数不增加。C独立实现pending不可替换原token及scope隔离，本服务端不假设未来SSO来填缺口。

测试：独立真实PG/HTTP3/3安全用例通过，包括Alice提交→Bob拒且DB连接数不增→Alice同键原回执、缺/伪token/无provider/无key/CSRF/只读ACL独立拒绝、停止旧HTTP服务后同key重启/换key保持拒绝。首轮测试fixture在setUp预置Bob/B1污染继承B01测试，已隔离seed到新用例；真实功能仍须最终完整回归与F/C合源验收，不能以这3项代替全产品QA。

现有里程碑/六kind正常新写HTTP测试改为从只读端点取得context；无保护旁路。FIELD_NEEDS_BANK_TRANSFER，测试Host/CSRF仍为fixture；不修改R1或08/09/10。
