# F 独立验收 E01/E02 Evidence 测试夹具

接受 #291 精确提交 `a5ae9bf271e8dd83b0cd2cdca389c8dcd5e91dcc`。独立工作树连接真实 PostgreSQL 17.6，复跑质量接口 Evidence 夹具。

- 父提交 `388b21b4075fcdcacd9940227772a938dca379b0` 两项测试均在构造真实 R1 夹具时发生 NameError，HTTP 断言未执行。1.013 秒。
- 候选通过标准序列化器写入 Evidence 夹具，两项真实 PostgreSQL/HTTP 测试均通过，零跳过，2.333 秒。覆盖权限降级 409、随后重新读取 200、完全撤权 403、禁止返回 Evidence 和原 R1 字节一致。
- 同候选全量 E01/E02 PostgreSQL 组件 73 项通过，零跳过，46.704 秒。

验收范围为测试夹具修复及既有只读行为回归。
