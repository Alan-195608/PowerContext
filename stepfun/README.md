# 本地知库 · StepFun × seekdb

浏览器本地 embedding + seekdb 原生混合检索的迷你文本知识库。所有项目资产均在 `stepfun/` 中，基于官方 `2026-competition-ecosystem`（`d647275c`）开发。

## 启动

需要 Node.js 22+、Python 3、curl、Chrome / Edge 现代版本。默认使用 seekdb-js 嵌入式数据库，支持 macOS Apple Silicon、Linux x64/arm64、Windows x64；首次访问数据库会下载官方原生运行库。整个数据库与应用均在本机运行，不需要云端账号或推理 API key。

```bash
cd stepfun
npm ci
python3 scripts/fetch-model.py
npm run dev
```

打开 http://127.0.0.1:5173 。下载模型需要能访问 Hugging Face；下载脚本固定模型版本，实际下载后生成 `results/model-sizes.json`（文件字节数、SHA256、压缩比）。支持标准 `HTTPS_PROXY` 环境变量；不要在配置或日志中保存代理凭据。

生产运行：先完成模型下载，再 `npm run build`，然后 `NODE_ENV=production npm start`。模型文件会由 Vite 从 `public/models/` 复制至 `dist/models/`；不需要外部 CDN。模型和原生数据库缓存不提交 Git。

可选本地 seekdb server：设置 `SEEKDB_HOST=127.0.0.1`、`SEEKDB_PORT=2881`、`SEEKDB_DATABASE=test`、`SEEKDB_USER=root` 和 `SEEKDB_PASSWORD` 后启动。须预先创建数据库；凭据仅由 Node 服务读取。默认嵌入式路径为 `.seekdb/`，可用 `SEEKDB_PATH` 指定已有本地目录。

## 操作

1. 输入知识库名称（小写字母开头，最多36个字母/数字/下划线），选 INT8，点击“加载本地模型”。优先 WebGPU；不可用或初始化/预热失败自动降级 WASM，界面显示实际后端。
2. 选择 `.txt` / `.md` 文本文件，或粘贴资料，点击“向量化并导入”。界面显示进度和写入、刷新耗时。每次最多128个片段，单个文件最多2MB。文件按900字符切片、重叠120字符；模型最多256个 token，超出部分会截断，因此长英文密集文本建议先分段。
3. 输入问题，点击“混合检索”。返回数据库排序后的前5个原文片段、来源和片段 ID。查询、文档 embedding 都由浏览器 Worker 计算。
4. 导入是增量追加；重复导入相同来源、片段序号和内容不会新增记录。修改内容后再次导入会保留旧片段，适用于追加资料；本版不提供文件替换/删除操作。
5. 修改知识库名称即可切换，旧结果会清空。FP32 与 INT8 使用独立集合，切换精度后必须重新加载并导入对应资料，避免混用向量。
6. “强制 WASM”用于验证无 GPU 的工作路径。取消后重新加载会再次尝试 WebGPU。

模型为英文 MiniLM。评测使用英文语料；应用接收中文文本，但不承诺中文语义质量。如更换模型，必须同时更换固定版本、维数、集合命名并重新评测。

## 架构与数据库

- `embedding.worker.mjs`：Transformers.js 4.3.2，mean pooling + L2 normalize。`env.allowRemoteModels=false`，只能读取本地准备的模型文件；没有任何远程推理调用。
- `server.mjs`：Express 本地同源 API，唯一存储/检索后端是 seekdb-js 1.4.0；显式 `embeddingFunction:null`，服务端只接收浏览器生成的向量，不计算 embedding。
- `core.mjs`：固定模型身份、分片、输入验证、质量指标。
- `app.mjs`：导入、搜索、进度、状态隔离和可复现评测。通过 `textContent` 展示原文，避免把导入文本作为 HTML 执行。
- 集合名 `sf_<知识库名称>_<精度>`，384维 cosine HNSW，`beng` 全文索引；seekdb 存储 ID、原文、向量和 `{source,model,revision,dtype}` 元数据。
- `collection.hybridSearch()` 在同一次数据库混合查询中执行全文候选、向量候选和 RRF；每路20候选，最终5结果。应用没有获取两路结果再自行融合的逻辑。
- 每个导入请求先全量校验，再按64条 upsert，全部写完只调用一次 `refresh_index()`，随后通过 ID 回读确认持久化。同集合操作串行，失败可以用相同数据幂等重试。刷新调用沿用 SDK 的版本判断；不伪装不支持版本的刷新成功，检索可见性由真实验收验证。
- 服务仅监听本机，拒绝非同源网页请求。不适合未经认证直接部署到公网。

## 复现测量

```bash
npm test
npm run build
# 应用启动后，执行真实数据库验收
node scripts/acceptance.mjs
```

浏览器中展开“性能与质量评测”，点击“运行完整评测”。内置 `public/evaluation.json` 是自编12条短文档、8条有人工相关性标签的查询，没有预计算向量。依次运行5个配置，每组重复3轮导入与全部查询；首轮与后两轮的原始计时分开保留，以后两轮中位数汇总预热性能。每组新建独立集合，重复导入验证 upsert。评测集合会留存在本地数据库中，便于检查，不会自动删除用户数据。

测量包括模型本地文件加载、文档/查询向量化、写入、索引刷新、seekdb 检索及浏览器 API 往返端到端延迟。端到端截止收到/解析结果，DOM 排版与屏幕绘制不计入；模型文件可能已在 HTTP/浏览器缓存，不能把该加载耗时称为互联网冷下载时间。WebGPU 初始化包含实际预热调用，WASM 首次推理则记录在首轮向量化中，跨后端加载时间不作等价比较。

结束时原始记录保存到本机 `results/browser-benchmark.json`；也可点击导出 JSON。记录包含浏览器 UA、硬件并发数和所有轮次。`results/acceptance.json` 是真实数据库验收（使用合成向量，仅验证数据层，不能作为模型质量证据）。本次性能/质量结论见 [TECHNICAL.md](TECHNICAL.md)。样本很小，不能推断大规模或跨语言效果。

自动降级分支为 `navigator.gpu` 不存在、adapter 不存在或 WebGPU 初始化/预热抛错时选择 WASM。提交记录包含实际 WebGPU 与强制 WASM 的完整流程；强制路径不是物理禁用 GPU 的独立设备测试。Edge 和 GPU 驱动异常设备尚未单独实测。

## 模型与量化来源

使用 [Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2)，revision `751bff37182d3f1213fa05d7196b954e230abad9`，上游 [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)，Apache-2.0。通过下载脚本获取同一版本 `onnx/model.onnx`（FP32）和 `onnx/model_quantized.onnx`（上游提供的 INT8 量化 ONNX），前端用 `dtype:fp32/q8` 选择。采用上游已量化权重，没有训练模型，也不声称自行重做量化。可通过下载脚本及 SHA256 复现使用完全相同的量化产物。

SDK 用法依据 [seekdb-js 官方源码与示例](https://github.com/oceanbase/seekdb-js)；赛题参见[官方要求](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kw9wfx4bu9pyvat9)。
