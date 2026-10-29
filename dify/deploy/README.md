# 真实 Dify 环境与验收

需要 Docker（支持 ARM64 或 AMD64）和至少 6 GiB 可用内存。本目录的脚本使用 Dify 正式镜像，不替换其工作流引擎、代码沙箱、模型插件或节点实现。

## 1. 启动游戏和 PowerContext

在 `dify/` 目录执行：

```bash
GAME_HOST=0.0.0.0 bash start.sh
```

保持终端运行。这会创建 `.venv` 并安装固定 PowerContext 提交。游戏绑定地址需要让 Docker 容器可达，数据和日志保存在 `.runtime`。不要把 18765/18766 端口暴露到公网。

## 2. 启动 Dify

另开终端，进入同一目录：

```bash
.venv/bin/python deploy/prepare_stack.py
docker-compose -f .runtime/dify-stack/compose.yml --env-file .runtime/dify-stack/.env up -d
```

也可将 `docker-compose` 换成 `docker compose`。原始官方 Compose 已附在 `deploy/upstream-compose.yaml`，脚本从中选择本应用需要的服务，随机生成本地部署凭据；无需额外下载 YAML。镜像和插件 Python 依赖仍需联网获取。

- 工作台：`http://localhost:18771`
- 正式 API：`http://localhost:18770`
- Dify API/Web/Worker：`1.13.0`
- Sandbox：`0.2.12`
- Plugin Daemon：`0.5.3-local`
- PostgreSQL：`15-alpine`；Redis：`6-alpine`

`prepare_stack.py` 保留沙箱镜像内的配置文件。沙箱启用 Dify 代码节点要求的网络能力；游戏 HTTP 请求由 API 服务直接访问受控本地后端。该配置用于本地隔离验收环境，不含公网发布配置。

## 3. 配置真实模型

```bash
export MODEL_API_KEY='<自己的模型 API Key>'
export MODEL_BASE_URL='https://api.deepseek.com/v1'
export MODEL_NAME='deepseek-flash'
.venv/bin/python deploy/install_model.py
unset MODEL_API_KEY
```

脚本首次运行会通过正式 Console API 初始化一个本地验收管理员，凭据保存在仅当前用户可读的 `.runtime/console-account.json`。它上传附带的官方 `openai_api_compatible` 0.0.73 安装包，等待安装完成，并通过 Dify 的模型配置接口验证真实服务。不会创建假模型接口，也不会把 Key 写入交付文件。

使用现有 Dify 工作台时，也可手动安装插件、填入相同模型和地址，再导入 `time-loop.yml`。若更换模型名称，应同时修改 DSL 的 LLM 节点。

## 4. 完整验收

```bash
.venv/bin/python verify_dify.py
```

此脚本只通过 Dify 的正式 HTTP 接口导入 DSL、发起对话、读取 SSE 事件并发布工作流。验证五节点免模型版和六节点 AI 版的成功状态，执行完整谜题、跨新会话读回记忆、玩家隔离和坏结局。失败时断言中止，不生成 PASS 汇总。

证据保存在 `evidence/dify/`：导入响应、每次请求的原始 SSE 事件数据、模型输出、节点状态和发布响应。浏览器截图不替代这些执行记录。

`verify.py` 是独立的游戏后端补充测试，不能替代 `verify_dify.py`。

## 停止服务

```bash
docker-compose -f .runtime/dify-stack/compose.yml --env-file .runtime/dify-stack/.env down
```

游戏和 PowerContext 终端按 Ctrl+C。停止服务保留已有存档与 Dify 数据。重跑验收使用随机玩家通行证，避免依赖旧存档。

## 插件守护进程的实测运行环境

本次验证使用原版 0.5.3 守护进程可执行文件，基于 Dify API 1.13.0 的 Python 环境构建运行镜像。可执行文件和入口脚本未修改，来源和校验值保存在 `evidence/dify/plugin-runtime.json`。

如需复现同一运行方式，在第 2 步生成配置后执行：

```bash
.venv/bin/python deploy/build_plugin_runtime.py
printf '\nPLUGIN_DAEMON_IMAGE=dify-loop-plugin-daemon:0.5.3\n' >> .runtime/dify-stack/.env
docker-compose -f .runtime/dify-stack/compose.yml --env-file .runtime/dify-stack/.env up -d
```

构建脚本默认从官方 `langgenius/dify-plugin-daemon:0.5.3-local` 镜像提取 `/app/main` 和 `/app/entrypoint.sh`。镜像从公开官方注册表获取；不从非官方二进制下载站获取程序。若已从 containerd 导出 ARM64 的官方最后一层，也可使用 `--layer path/to/archive.tar.gz`：脚本先核对固定 SHA256，再只提取这两个指定文件。该归档不是必须提交的数据，可以从官方镜像重新获取。

本次镜像层下载中断，因而采用已经完整下载且校验通过的官方最后一层进行构建。运行方式与默认完整镜像不同，实际验收证据针对该构建方式。

完成完整工作流验收后，可继续验证已发布的应用：

```bash
.venv/bin/python verify_published.py
```

它创建当前本地测试应用的 API Key，保存在 `.runtime/service-api-key.json`，不写入证据；通过正式 `/v1/chat-messages` 测试真实模型回答和新会话记忆复用。
