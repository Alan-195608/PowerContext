# 23:57 时间循环便利店

一个由 Dify 编排、AI 店员即兴回应、PowerContext 保存跨轮记忆的解谜小游戏。你被困在永远停在 23:57 的便利店，物品会在午夜清零，发现的秘密却能留到下一轮，帮助你改变结局。

**已完成真实 Dify 1.13.0 验证：两个 DSL 导入成功，12 次工作流运行成功；正式发布后的 `/v1/chat-messages` API 另完成 3 次验证。** 结果来自实际 Dify 服务、代码沙箱、插件守护进程、DeepSeek 模型和 PowerContext，没有替代服务。证据见 [完整验收汇总](evidence/dify/summary.json) 和 [正式 API 汇总](evidence/dify/production-summary.json)。

## 玩法与技术分工

每轮有三次行动，找齐收据和广播两条线索后，每轮获得额外一次行动。“开始”“状态”不消耗行动；“重来”清空本轮物品、进度和信任，保留发现的秘密。支持菜单中的明确行动，暂不支持自由语言动作判定。

- **Dify**：输入 → Code 编码 → HTTP 执行行动并召回记忆 → Code 提取权威结果 → LLM 店员对白 → Answer 展示。正式 AI 版六个节点均在真实 Dify 中运行。
- **PowerContext**：每个玩家对应独立 Scope。观察动作通过 `/v1/memory/remember` 保存发现，每次行动通过 `/v1/context/prepare` 召回；电闸和递牛奶的判定实际依赖召回结果，服务不可用会显式失败。
- **Python 后端**：确定性判定行动、物品、电闸、信任和结局；SQLite 保存本轮状态及请求去重。跨轮笔记从 PowerContext 读取，不从 SQLite 伪造。
- **真实模型**：生成氛围对白，不修改权威状态或决定胜负。模型配置使用扩展兼容模式并关闭思考输出，避免思考过程耗尽短对白的输出额度。

不需要 seekdb、Embedding、Rerank、外部知识库或自定义 Dify 插件。剧本和游戏代码为本作品编写；模型插件使用原始官方安装包。

## 交付文件

| 文件 | 用途 |
| --- | --- |
| `time-loop.yml` | 正式 AI Chatflow；Dify 1.13.0、DSL 0.6.0 |
| `time-loop-no-model.yml` | 五节点免模型版，用于独立检查流程、网络与记忆；与 AI 版无导入顺序依赖 |
| `game.py`、`start.sh`、`play.py` | 游戏服务、PowerContext 启动脚本、本地终端体验入口 |
| `plugins/` | 官方 `openai_api_compatible` 0.0.73 安装包、来源与校验值 |
| `deploy/` | 真实 Dify 部署、初始化和模型配置脚本；[详细运行说明](deploy/README.md) |
| `verify_dify.py` | 正式 Console API 导入、完整节点及玩法验收 |
| `verify_published.py` | 已发布应用的正式 `/v1/chat-messages` 验收 |
| `verify.py` | 游戏与 PowerContext 的补充行为测试 |
| `evidence/dify/` | Dify 导入响应、原始 SSE 事件数据、节点输出、发布结果、模型与运行环境记录 |
| `evidence/acceptance.json` | 后端补充测试记录，不能替代 Dify 验收 |

## 环境与完整启动

需要 Python 3.12、Git、uv、Docker 和至少 6 GiB 可用内存。PowerContext 固定为官方提交 `dab240063bfcfa7917898dc44da4baadb3747bd0`，使用 `cli,server` extras；应用运行只依赖 Python 标准库，部署脚本使用该环境已有的 httpx 和 PyYAML。Dify API/Web/Worker 为 1.13.0，Sandbox 为 0.2.12，模型为 `deepseek-flash`。

在本目录执行并保持终端运行：

```bash
GAME_HOST=0.0.0.0 bash start.sh
```

另开终端进入本目录：

```bash
.venv/bin/python deploy/prepare_stack.py
docker-compose -f .runtime/dify-stack/compose.yml --env-file .runtime/dify-stack/.env up -d
export MODEL_API_KEY='<自己的模型 API Key>'
.venv/bin/python deploy/install_model.py
unset MODEL_API_KEY
.venv/bin/python verify_dify.py
.venv/bin/python verify_published.py
```

有 Docker Compose 插件时可把 `docker-compose` 换为 `docker compose`。模型地址默认 `https://api.deepseek.com/v1`；通过 `MODEL_BASE_URL`、`MODEL_NAME` 修改。更换模型名称时，同时修改 DSL 的 LLM 节点。插件安装需要联网获取其 Python 依赖，模型 API 需要可达的网络及可用额度。

工作台入口为 `http://localhost:18771`，正式 API 为 `http://localhost:18770`。脚本初始化的本地验收管理员凭据在 `.runtime/console-account.json`，仅当前用户可读，不纳入提交。也可在现有工作台手动安装插件、配置模型、导入 DSL 并发布。

**本次实测的插件守护进程部署方式：** 原版 0.5.3 可执行文件从官方 ARM64 镜像层提取，未修改，使用 `deploy/Dockerfile.plugin-daemon` 放入已有 Dify API Python 基础镜像；没有使用原镜像中与本应用无关的图像及编译依赖层。来源层及二进制 SHA256 见 `evidence/dify/plugin-runtime.json`，实际服务镜像见 `runtime.json`。按同样方式复现见 [插件运行环境说明](deploy/README.md#插件守护进程的实测运行环境)；也可以直接运行默认官方完整 `0.5.3-local` 镜像。完整官方镜像的部署方式未在本次环境运行，不能与已验证的重打包方式混为一谈。

## 手动导入与验证样例

1. 在 Dify 工作室选择“导入 DSL”，导入 `time-loop.yml`。
2. 安装 `plugins/` 中的官方插件。在 OpenAI-API-compatible 中添加聊天模型 `deepseek-flash`，填写自己的 API Key 和 `https://api.deepseek.com/v1`，设为 chat 模式、扩展兼容模式、思考能力不支持；与自动配置脚本一致。
3. 环境变量 `GAME_URL` 默认 `http://host.docker.internal:18766`。它必须是 **Dify 服务端**可访问的游戏地址。Mac Docker/Colima 可用此地址；Linux Docker 需配置 host-gateway 或可达的宿主机地址。Dify Cloud 不能直接访问你本机的 localhost。
4. 为每位玩家生成不同的随机通行证，填写后按表格顺序输入。通行证是存档凭据，请保存并避免使用他人可猜测的值。

| 步骤 | 输入/操作 | 预期表现 |
| --- | --- | --- |
| 1 | 新通行证，开始 | 第 1 轮，笔记为空 |
| 2 | 看收据 | 收据秘密写入 PowerContext，笔记出现 1 条 |
| 3 | 听广播 | 广播秘密写入，笔记出现 2 条，获得额外行动 |
| 4 | 重来 | 第 2 轮，物品清空，笔记保留 |
| 5 | 新建 Dify 会话，填写同一通行证，状态 | 新 conversation_id 中仍可读取两条记忆 |
| 6 | 买牛奶 | 得到热牛奶 |
| 7 | 拉电闸 | 依靠广播记忆成功断电 |
| 8 | 递牛奶 | 收据记忆、牛奶、断电条件共同产生店员信任 |
| 9 | 开门 | 真结局“明天照常营业” |

另一通行证“开始”应无笔记，直接“开门”进入坏结局并重置本轮。使用新通行证可以恢复全新状态；“重来”保留记忆是玩法设计。终端入口 `python3 play.py` 可体验后端，恢复存档时设置 `PLAYER_TICKET`；终端运行不代表 Dify 验收。

## 运行证据与边界

`evidence/dify/00-no-model.json` 为五节点成功记录，`01-ai.json` 至 `11-bad-ending.json` 包含 AI 流程、两个不同会话、两个玩家和结局；每份记录保留 Dify 返回的 workflow_run_id、node_id、状态、HTTP 输出和模型 usage。`production-*.json` 来自发布后的正式 API，包含新会话记忆复用。`imports.json` 记录输入 DSL 的 SHA256；最终提交的 YAML 与被验证文件对应。

游戏服务为单进程演示设计，不支持多实例并发。客户端需复用同一 request_id 才能对网络重试去重，Dify HTTP 节点重试复用同一次 workflow_run_id。跨系统没有分布式事务，故障时线索可能先写入，状态尚未提交；重试会检查已存在标记。模型服务失败时，行动可能已提交，应先“状态”核对，避免重复扣行动。部署服务和 API Key 均由运行者提供，本地执行成功不代表赛事平台已经重新判定通过。

## 来源与提交位置

作品基于官方 `2026-competition-ecosystem` 的 `d647275c` 开发，全部提交资产位于 `dify/`。赛题来源：[官方 Dify 赛题](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6)。部署源文件来自 [Dify 1.13.0](https://github.com/langgenius/dify/tree/1.13.0/docker)，模型插件来源见 `plugins/README.md`。模型、运行环境和代码验证已使用 AI 辅助完成，实际日志可独立核查。
