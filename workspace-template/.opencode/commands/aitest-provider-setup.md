---
description: 模型认证待完成时的设置指引（不接收或保存密钥）
agent: aitest-director
---

OpenCode PROCESS_READY 与模型 AUTH_READY 是两个独立状态。认证待完成时 OpenCode 与 G2.1 Control Loop 仍保持运行；Mission 等待模型就绪。

可以使用安装目录的 `./AITEST.sh` 菜单 5 选择：
- REUSE_APPROVED_HOST_PROVIDER：选取已发现的宿主 opencode.json / opencode.jsonc，输入批准记录和 provider/model，例如 wizard-local/aicoder-plus。仅在明确授权后检查配置；不读取宿主 auth.json，不更改宿主配置，不复制凭据。已有本地 SDK / 插件路径按原模式复用，不要求 /v1。
- PACKAGE_LOCAL_PROVIDER_BINDING：配置已批准服务地址及模型 ID。地址保持原样。凭据由启动进程的已批准环境变量提供。
- AUTH_REQUIRED：保留未绑定状态；OpenCode 仍可以启动。

不要把 API key、password、token 输入对话或配置表单。内联凭据、文件凭据引用、未安装插件会保持 BANK_PROVIDER_BINDING_REQUIRED。批准的插件可能执行自定义认证逻辑；真实行内 wizard-local 的兼容性和认证必须现场验证。完成绑定后重新打开对话使新的环境变量及配置生效。

这是一份设置指引，不是模型认证成功或银行验证 PASS 的证明。模型未就绪时不需要创建 Session、切换 Agent 或手工计划；就绪后直接输入自然语言测试请求。
