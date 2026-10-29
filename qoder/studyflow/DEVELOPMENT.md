# Qoder 开发记录

主要开发工具：Qoder CLI CN 1.1.80。真实会话 ID：`311af779-cf67-4bf6-b7ed-faeabcda9186`，开发自 2026-10-28 开始，后续修复及验证于 2026-10-30 进行。

Qoder 完成需求拆解、真实 PowerContext SDK 调研、Python HTTP 服务、记录与召回、周报生成、中文前端、自动验证脚本和展示网站。Codex 负责任务组织、代码审查、局部输入与路径修复以及独立环境验证。没有将 Codex 操作伪称为 Qoder 开发。

开发时发现并修复了召回路径解析、记录时间持久化、多行内容保存、异步事件循环和独立环境部署等问题。使用 PowerContext 内置 Runtime 验证保存、主题隔离及跨进程重启读取。

会话文字与工具名称摘录：`evidence/qoder-session.md`。这是从本机真实 Qoder 会话导出的记录，不是截图或录屏；若评审严格要求对话截图，应在 Qoder 中打开上述会话补拍。账号 UID 应以 Qoder 个人资料显示值为准，不以账号昵称或头像路径推定。

独立验证使用 `powercontext[builtin]==1.2.0`，SDK 22/22、HTTP 55/55 通过，完整输出见 `evidence/`。无模型 API 调用，无真实用户提效统计。
