# F 独立验收管理服务源码归档启动

F 接受 PR257 精确 `840629b3514caa444ac38f97c6454b3addd051bf` 的正常入口源码归档启动与默认拒绝行为。尾随路径参数有一项拒绝状态兼容差异，见下文。

F 分别从旧 `d15a9b275491c9bc6e99b486e94fc3c9727ca4c0` 和新候选复制各自声明的全部 `SOURCE_DIRS` 到临时目录，使用 `python3 -I -S` 在该目录启动子进程，确认无 `tools`。旧进程在正常 `create_server(ProductAdminApplication(...))` 阶段从默认 handler 导入 `tools.dsh_workbench.business_http`，以 ModuleNotFoundError 退出。新候选相同独立脚本实际通过。旧管理 `/api/meta` 返回 200 和正确产品标识，Workbench 静态入口 200。默认业务 GET、PATCH、POST、DELETE 均返回相应 503 HOST_IDENTITY_UNAVAILABLE，未支持的 POST/PUT 返回 405，挂载模式旧私有 GET/POST 返回 403。JSON 错误均为 no-store，临时 R1 字节不变。全程仅复制源码目录。

真实 PostgreSQL 17.6 ICU socket 55439 上的 HTTP/归档回归实际 **15/15**，13.24 秒。所运行文件为 `test_dsh_workbench_product_source_archive.py`、`test_dsh_workbench_mount_auth.py`、`test_dsh_workbench_http_transport.py`、`test_dsh_workbench_b_transport_postgres.py`、`test_dsh_workbench_b_project_metadata_http_postgres.py`。旧管理 `test_rc7_admin.py` **4/4**，1.00 秒。原生 Chromium 同源 `test_same_origin_workbench.py` 和 metadata `test_project_metadata_product_browser.py` **2/2**，9.13 秒。均零跳过。显式真实 PG handler 在正常浏览器和 HTTP 入口工作。Host 证明来自测试夹具。

## 剩余 P2 兼容差异

F 用完整旧源码和新候选分别启动默认无适配器 Workbench，发真实 `PATCH /api/workbench/v1/projects/P1/metadata;extra`。旧返回 405 METHOD_NOT_ALLOWED，新返回 503 HOST_IDENTITY_UNAVAILABLE。默认分流的 `urlparse(...).path` 去掉了尾随参数，而原业务 handler 用 `urlsplit(...).path` 保留。两种响应都拒绝，未运行有效业务写路径。正常入口的启动修复通过，逐路径状态完全等价仍有此例外。

报告仅覆盖源码归档与同源组件兼容。Windows 行内离线安装、正式 Host 和最终交付仍分别待验。F 仅提交报告。
