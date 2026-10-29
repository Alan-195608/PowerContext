# 研途 StudyFlow

学习与科研进度助手：记录进展、困难和下一步，在下次学习时召回历史，并导出带 Memory ID 来源的 Markdown 周报。

## 运行

需要 Python 3.11+、macOS 或 Linux。以下命令从本项目目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
bash start.sh
```

打开 http://127.0.0.1:8765 。也可用 `uv venv --python 3.12 .venv` 创建环境，然后 `uv pip install --python .venv/bin/python -r requirements.txt`。

默认不需要模型 API 或 API Key。服务仅监听本机，数据目录为 `data/`；设置 `STUDYFLOW_DATA_DIR` 可以指定其他数据目录。保留此目录可在重启后恢复记录。

## 验证样例

1. 添加主题“论文阅读”，进展“读完引言”，困难“尚不理解注意力公式”，下一步“逐项推导公式”。
2. 打开时间线和继续学习，选择“论文阅读”，应看到相同内容和 Memory ID。
3. 添加第二主题“数据库”，应与论文记录隔离。
4. 停止并重启服务，历史内容及创建时间应保持不变。
5. 生成最近七天周报并下载 Markdown，应包含保存的进展、困难、下一步及 Memory ID 引用。

“载入样例”会写入明确标注的示例学习记录，其中的实验结果为虚构教学数据，不是本作品实测效果。

## 自动验证

```bash
.venv/bin/python test_http.py
.venv/bin/python verify.py
```

测试使用临时数据目录。独立安装 PowerContext 1.2.0 后实测 HTTP 55/55、SDK 22/22 通过，输出位于 `evidence/`。

## 技术分工

核心依赖为 OceanBase PowerContext 1.2.0。服务使用真实 `open_builtin_runtime`、Scope 注册表、Memory remember/list API。每个主题对应独立 Scope，学习记录及创建时间保存在 PowerContext Memory 内；重启后读取同一数据库。周报和行动建议由已保存记录按确定性规则整理，不调用 LLM。SQLite 由 PowerContext 内置后端管理，应用不自行实现替代 SDK。

公开网站用于介绍作品及体验浏览器样例；真实 PowerContext 功能需按上述步骤本地启动。两种运行方式在页面明确区分。

## 开发与来源

主要代码、前端、测试及网站由 Qoder CLI 开发，Codex 负责组织任务、审查、局部修复及独立验证。真实会话摘录见 `evidence/qoder-session.md`。不包含虚构用户数量或提效数据。

PowerContext 来源：https://github.com/oceanbase/powercontext ，Apache-2.0。作品基于赛事 `2026-competition-ecosystem` 分支，全部资产位于 `qoder/studyflow/`。
