# 只读项目/投产日期目录组件

独立wb-directory，复用现表与RLS，无新迁移、项目创建、ACL授予、看板phase或R1事实。business_directory.DirectoryStore在真实PG只读快照内列可见项目及授权日期，签名cursor绑定完整可见快照/主体/ACL/日期修订。HTTP沿既有scope_handler可信Host入口，精确响应见06增量。

测试test_dsh_workbench_b_directory_postgres.py：继承B01恢复/权限回归，另验项目可见/空、增授撤权cursor、稳定日期ID与改期失效、真实HTTP权限/客户端principal拒绝、缺Host/DB503与恢复。fixture不代表行内Host；FIELD_NEEDS_BANK_TRANSFER。无08/09/10修改。
