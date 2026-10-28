# 23:57 时间循环便利店

你被困在永远停在 23:57 的便利店。物品会随午夜清零，发现的秘密却会写入 PowerContext。收集线索、进入下一轮，再用记忆改变结局。默认三次行动，找齐两条线索后获得额外一次行动；“开始”“状态”不消耗行动。“重来”清空本轮物品和进度，保留已发现的秘密。

## 技术分工

- Dify Chatflow：玩家输入 → JSON 安全编码 → HTTP 工具调用 → 提取权威结果 → 模型生成店员对白 → 展示结果。AI 的对白与确定性裁判结果分开展示。
- PowerContext：每个玩家独立 Scope；观察动作通过 `/v1/memory/remember` 保存发现；每次行动通过 `/v1/context/prepare` 召回线索。电闸和递牛奶的判定实际依赖召回结果，数据库断连会导致操作失败，不会伪装成记忆成功。
- Python 后端：规则判定、行动次数、牛奶与电闸状态。SQLite 仅保存本轮状态和请求去重结果，跨轮笔记仅从 PowerContext 获得。无需 seekdb、Embedding 或 Rerank。

输入仅接受菜单中的明确行动。AI 负责即兴对白，不支持自由语言动作判定，也不能修改胜负。两条线索都来自原创固定剧本，没有外部素材或知识库。

## 环境与版本

Python 3.12、Git、uv。后端和验证脚本仅用 Python 标准库。PowerContext 固定使用官方 `2026-competition` 提交 `dab240063bfcfa7917898dc44da4baadb3747bd0`，安装 `cli,server` extras（依赖由该提交声明，首次安装需联网）。DSL 以 Dify 1.13.0 的节点结构、DSL 0.3.0 为目标；**未在真实 Dify 实例导入验证**。DSL 生成脚本需要 PyYAML，已提交生成好的 YAML，运行作品无需执行生成脚本。

## 本地启动与体验

在本目录执行：

```bash
bash start.sh
```

脚本首次创建 `.venv` 并安装固定提交，启动 PowerContext 18765 和游戏服务 18766。PowerContext 使用独立的 `.runtime/powercontext`，不会改动已有个人记忆。Ctrl+C 结束本次服务。再次运行可继续存档。

另开终端进入本目录：

```bash
python3 play.py
```

终端会显示随机玩家通行证。恢复存档时设置 `PLAYER_TICKET` 为同一值再运行 `play.py`。通行证是持有即可访问存档的凭据，请使用随机值；可通过 `python3 -c 'import secrets; print(secrets.token_hex(16))'` 生成。每位玩家使用不同通行证。终端入口只验证游戏和记忆服务，不代表 Dify 已验收。

## Dify 导入和配置

1. 准备 Dify 自部署 1.13.0 或现有工作台。自部署参考 [官方部署说明](https://docs.dify.ai/en/self-host/quick-start/docker-compose)。本项目不包含 Dify 平台自身。
2. 在工作室选择“导入 DSL”，导入 `time-loop-no-model.yml`，此文件无需模型或插件，是排查网络和记忆链路的入口。
3. 应用环境变量 `GAME_URL` 默认 `http://host.docker.internal:18766`。Dify Docker 中的 localhost 是容器本身，必须填 Dify **服务端可访问**的游戏地址。Mac Docker 访问本机服务时，启动游戏前设置 `GAME_HOST=0.0.0.0`；Linux Docker 需增加 host-gateway 映射或设置可达的宿主机 IP。Dify 的 SSRF 代理必须允许这个受控的本地服务地址。后端不应直接暴露到公网。
4. 填写玩家通行证，发送“开始”，随后发送菜单中的行动。换一个新会话、保留相同通行证，发送“状态”应显示历史笔记。
5. 单独导入 `time-loop.yml` 作为正式 AI 版。它与免模型版是两个独立应用，没有导入顺序依赖。模型节点默认 OpenAI 插件路径 `langgenius/openai/openai`、`gpt-4o-mini`；请在工作台安装其可用版本、配置自己的模型凭据，然后重新选择模型。也可换成已配置的其他聊天模型。所需插件版本取决于目标工作台，尚无经过验证的固定插件版本；实际提交时应补录。
6. 调试成功后发布 Dify 应用，以发布的 WebApp 或 API 作为评审入口。AI 服务失败会使 AI 版回答失败，游戏行动可能已经提交；用“状态”核对，不要再次发送会扣行动的命令。可使用免模型版继续同一通行证的存档。

Dify 的模型凭据仅存工作台。启用 PowerContext 服务端鉴权时，在游戏进程环境设置 `POWERCONTEXT_TOKEN`，不把它送入模型。项目没有实际 API Key 或密码。

## 完整验证样例

初始条件：服务已启动，使用新生成的玩家通行证，没有笔记。按顺序输入：

| 步骤 | 输入 | 应观察到的表现 |
| --- | --- | --- |
| 1 | 开始 | 第 1 轮，笔记为空 |
| 2 | 看收据 | PowerContext 写入收据线索，笔记出现 1 条 |
| 3 | 听广播 | 写入广播线索，笔记出现 2 条，获得第 4 次行动额度 |
| 4 | 重来 | 第 2 轮；物品清空，笔记仍为 2 条 |
| 5 | 新建 Dify 会话，填相同通行证，输入 状态 | 不依赖旧会话历史仍能看到两条记忆 |
| 6 | 买牛奶 | 得到热牛奶，剩余 3 次行动 |
| 7 | 拉电闸 | 因召回广播线索而成功断电 |
| 8 | 递牛奶 | 因收据记忆、牛奶和断电条件同时满足而取得信任 |
| 9 | 开门 | 真结局“明天照常营业” |

坏结局：用另一通行证直接“开门”，进入下一轮，不能通关。玩家隔离：另一通行证“状态”应无笔记。恢复全新状态：使用新通行证；“重来”保留记忆是设计行为，不是彻底删除存档。

## 自动验证与证据

保持 PowerContext 启动，在本目录执行：

```bash
.venv/bin/python verify.py
```

验证脚本使用独立临时 SQLite、随机玩家、端口 18767 的真实 HTTP 游戏进程，实际调用 PowerContext，覆盖通关、失败、记忆持久化、进程重启、玩家隔离、请求幂等和非法输入。日志写入 `evidence/acceptance.json`，包含每个操作的真实返回值及 PreparedContext 召回内容。可重复运行，不覆盖已有玩家进度。

当前已验证：本地游戏 HTTP 和真实 PowerContext 读写。尚未验证：Dify 导入、Dify 节点执行、模型 API 输出、Docker 联网。日志中的这两项验证标志明确为 false，不能作为完整 Dify 运行证据。赛前需完成上面的 Dify 操作并补充节点截图/执行日志。

单进程游戏服务顺序处理请求，适合演示；不支持多实例并发部署。客户端必须复用相同 request_id 才能对网络重试去重，Dify HTTP 节点重试复用同一次 workflow_run_id。跨系统没有分布式事务：故障时显式线索可能先写入而游戏状态尚未提交，重试会检查已存在的标记；不会重复消耗已成功提交的同一请求。

## 提交位置和来源

本分支从官方 `2026-competition-ecosystem` 的 `d647275c` 创建，作品全部放在 `dify/`。赛题来源为 [官方 Dify 赛题](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/lhfslihtnnb8yqh6)。HTTP 节点字段参考 [Dify 1.13.0 官方源码](https://github.com/langgenius/dify/blob/1.13.0/api/core/workflow/nodes/http_request/entities.py)，PowerContext 接口参考固定提交中的 OpenAPI。未复用其他游戏 DSL。

提交时将本分支变更同步至参赛私有仓库的同名基础分支，在测评平台填写已推送分支或 commit hash。当前本地完成不代表已经提交测评。
