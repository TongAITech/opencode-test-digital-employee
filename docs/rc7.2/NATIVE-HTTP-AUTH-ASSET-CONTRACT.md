# RC7.2 Worker HTTP 认证材料与真实身份核验

状态：已实现父进程认证材料读取、实际身份探测、受限业务 HTTP 及历史审计。
宿主 AuthKeeper/4A 自动导出接线、其自身 Worker/Browser 生命周期和其余工具
调用边界仍在施工。本文件不代表这些路径完成，也不代表银行现场验收通过。

## 执行边界

`WorkerHTTPAuthAssetProvider` 仅绑定同一原生 Preparation 服务。N4 的冻结
Runner transport 可以明确选择 `WORKER_HEADER`，N1 所选 auth Fact 必须声明
相同模式及完整账号、角色集合、身份探测地址和非设备绑定属性。原始 Case
的 auth_role 必须属于该批准集合。缺少任一绑定均阻断，不降级为匿名请求。

当前实现使用单一 Authorization 头，实际 GET 身份探测与业务 API 同源。
身份探测响应中的实际账号和完整角色集合必须与冻结 N1 Fact 一致；不能以
导出材料中的自报角色替代实际核验。额外特权角色同样不被接受。代理和 HTTP
重定向禁用；身份响应限制 64 KiB。设备/浏览器绑定会话、Cookie、mTLS 和
跨源身份服务尚未由这个具体 Provider 实现，应走对应显式能力提供路径。

父进程在真实业务请求前后检查活跃 Dispatcher、当前签名权限、完整源契约、
资源所有权以及认证材料的范围、有效期和内容一致性。身份探测后持久化签名
回执，再次检查权限后才发起业务请求。业务效果发生后材料变更或到期，保留
UNKNOWN、已捕获响应和原资源占用；不自动重放，也不自动清理释放。

运行时不把认证头复制到子进程环境或 RPC 参数、R1、Runner 输出与业务证据。
父进程只向子进程提供绑定当前操作的原生请求能力。回执保存的是实际身份投影、原始身份响应
摘要、材料的域分离 HMAC 绑定和签名。历史审计验证冻结来源、范围、时序与
签名，不读取旧密钥文件，不恢复执行权限。该签名观测不声称是银行服务端签名。

## 冻结 N1 Fact

以下为所选 auth Fact 的 attributes 中非秘密的契约示例。真实地址、账号、
角色及来源必须由 N1 的原生证据与独立审核批准，不能在 N7 临时补写。

```json
{
  "authentication_mode": "WORKER_HEADER",
  "worker_http_auth": {
    "asset_ref": "bank-auth://business-checker",
    "principal": "approved-business-account",
    "roles": ["CHECKER"],
    "device_bound": false,
    "identity_probe": {
      "url": "https://approved-api.bank.example/identity",
      "principal_path": "$json.principal",
      "roles_path": "$json.roles"
    }
  }
}
```

以上示例不授予权限，也不是可代替真实证据的现场配置。N1 auth Fact 的
source_ref 必须属于该冻结契约的 authoritative_sources。实际身份探测仅
使用已批准的固定地址和字段投影，子进程不能传入替代 URL、请求头或账号。

## 宿主导出接口

由银行受信 AuthKeeper/4A 导出器写入宿主配置目录：

```text
<asset_root>/<runtime worker_id>/<runtime attempt_id>.json
```

导出 JSON 必须且只能含下列字段：

| 字段 | 来源/约束 |
|---|---|
| schema | `RC72_WORKER_HTTP_AUTH_V1` |
| preparation_id、release_id、source_commit、mission_id、workitem_id、attempt_id、worker_id、contract_id | 原生运行时本次分配，逐项精确相等 |
| auth_asset_ref | 冻结 N1 的 asset_ref |
| principal、role | 批准账号及本次 Case 的原始业务角色 |
| issued_at、expires_at | Unix 整数时间；必须已签发且尚未到期，布尔值无效 |
| headers | 仅一个 Authorization 字段；不能带换行、NUL 或替代地址 |

这份材料由宿主导出器产生，不交给 Agent 填写，不把 Captain/Coordinator
配置复制给 Worker，不随搬运包封装。若银行会话不可安全导出，不能把
`device_bound` 改为 false 绕过限制，应使用独立登录与 BrowserLease 路径。

## 当前验证范围

工程测试启动真实身份/业务 HTTP 服务，并运行批准的真实 pytest 子进程。
已覆盖完整 N7 独立验收、删除材料后的冷启动历史审计、跨 Worker/Attempt/
资产/角色拒绝、过期及头注入、实际账号/角色不符、额外特权角色、执行中
材料变化/到期、身份回执 fsync 后权限撤销，以及禁止匿名降级。真实银行
导出器、4A 登录挑战、设备绑定会话与其恢复仍需后续施工及现场验证。
