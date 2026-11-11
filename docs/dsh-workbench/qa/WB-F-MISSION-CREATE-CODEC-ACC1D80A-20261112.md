# F 独立验收正式 Mission 创建编码

接受 #298 精确提交 `acc1d80a2f6456c957e7fefb4a70d7a4a27f113d` 的独立请求和 PREPARE 选择编码。独立 Ruby JSON 递归编码与 SHA-256 实现生成 994 字节请求及 318 字节选择，逐字节匹配两个规范向量。摘要分别为 `70dd4f7c9fc1836ab5086d8ef9d4b8ce3e0d87a31602933a592294661c91f89a` 与 `6cc12d22e5b1601c2605dd6c530bdb14875262a2b23b59b29947c250f80ad7c7`。最大有符号 64 位修订精确保持。

独立边界覆盖同键改 goal、转义同名键、固定首尾空白规则和 FEFF、384 字节键与超限、修订溢出。官方本地套件 7 项全部通过，含 NUL、非法 UTF-8、65,536 字节上限和超限。精确 [CI 43070260523](https://github.com/TongAITech/opencode-test-digital-employee/actions/runs/43070260523) checkout 日志确认 Python 3.8 与 3.11 各 31 项通过。

集成边界：独立探针确认相互一致但含首尾空白的已分配 Mission 和运行 release ID 在纯编码保持原样，实际 Mission 构造器会修剪。正式分配与事件入口须在构造请求摘要或生成事件前拒绝会被修改的分配标识。此次验收只覆盖纯编码；正式回执、分配、数据库事务及 Host/R1 写入需分别验收。
