# F 复验源码归档路径分类修订

F 接受 PR257 精确 `90bdfafc792fb3ed03bd5f6ca1f96f9140166bf2` 的源码归档兼容修复。F258 保留旧 `d15a9b27` 缺 tools 无法启动和 `840629b3` 尾随参数状态错误两项记录。

同一个 F 独立探针从各自 checkout 复制声明的 SOURCE_DIRS，在归档内用 `python3 -I -S` 启动，并确认不存在 tools。此次新增断言 `PATCH /api/workbench/v1/projects/P1/metadata;extra` 为 405 METHOD_NOT_ALLOWED。精确 840 归档实际返回 503 HOST_IDENTITY_UNAVAILABLE 并触发断言，精确 90 归档返回 405，整套独立矩阵通过。矩阵还核旧 admin 正常启动、/api/meta 200、Workbench 静态页、业务 GET/PATCH/POST/DELETE 503、未支持方法 405、挂载旧私有 GET/POST 403、no-store 和 R1 字节不变。修订使默认 route classifier 与原业务 handler 均以 urlsplit 保留尾随路径参数。

精确 90 独立 pytest 执行归档测试、挂载认证测试及旧 admin 测试 **10/10**，7.08 秒。实际 PG17.6 ICU socket 55439 和原生 Chromium 执行同源与 metadata 浏览器 **2/2**，9.75 秒。均零跳过。显式同源 handler 正常，Host 使用测试夹具。F 只复制源码目录并提交验收报告。正式 Windows 离线安装和最终交付仍待现场验证。
