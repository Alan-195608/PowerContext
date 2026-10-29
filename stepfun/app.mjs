import { chunks, MODEL, REVISION, metrics, median } from './core.mjs';
const $ = id => document.getElementById(id);
const worker = new Worker(new URL('./embedding.worker.mjs', import.meta.url), { type: 'module' });
let sequence = 0, model = null, busy = false, report = null;
const pending = new Map();
worker.onmessage = ({ data }) => {
  const task = pending.get(data.id);
  if (!task) return;
  if (data.progress) { if (data.progress.status === 'progress') $('progress').textContent = `${data.progress.file} · ${Math.round(data.progress.progress || 0)}%`; return; }
  pending.delete(data.id);
  data.error ? task.reject(new Error(data.error)) : task.resolve(data.result);
};
worker.onerror = event => { for (const task of pending.values()) task.reject(new Error(event.message)); pending.clear(); };
function inference(op, args) { return new Promise((resolve, reject) => { const id = ++sequence; pending.set(id, { resolve, reject }); worker.postMessage({ id, op, ...args }); }); }
async function api(route, body) {
  const response = await fetch(`/api/${route}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || response.statusText);
  return result;
}
function updateControls() {
  for (const id of ['load', 'benchmark', 'collection', 'precision', 'wasm', 'files', 'text']) $(id).disabled = busy;
  for (const id of ['import', 'search']) $(id).disabled = busy || !model;
}
async function action(fn) {
  if (busy) return;
  busy = true; updateControls();
  try { await fn(); } catch (error) { $('status').textContent = `操作未完成：${error.message}`; $('progress').textContent = error.message; }
  finally { busy = false; updateControls(); }
}
async function load(dtype, forceWasm) {
  model = null;
  $('backend').textContent = '加载模型中…';
  try {
    model = await inference('load', { dtype, forceWasm });
    $('backend').textContent = `${model.backend.toUpperCase()} · ${dtype === 'q8' ? 'INT8' : 'FP32'}`;
    $('progress').textContent = `${(model.loadMs / 1000).toFixed(1)}秒完成加载。${model.fallback || 'WebGPU已验证'}`;
    $('status').textContent = '模型已就绪，可以导入文档。不同精度使用独立集合。';
    return model;
  } catch (error) { $('backend').textContent = '模型加载失败'; throw error; }
}
$('load').onclick = () => action(() => load($('precision').value, $('wasm').checked));
for (const id of ['precision', 'wasm']) $(id).onchange = () => { model = null; $('backend').textContent = '配置已改变，需重新加载'; $('results').replaceChildren(); updateControls(); };
$('collection').oninput = () => { $('results').replaceChildren(); $('status').textContent = `当前知识库：${$('collection').value}。搜索只返回此库和当前精度的资料。`; };
async function digest(value) { return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))), x => x.toString(16).padStart(2, '0')).join(''); }
async function importRecords(records, collection, batchSize = 8, writeBatch = 128) {
  const vectors = [];
  let embedMs = 0;
  const started = performance.now();
  for (let i = 0; i < records.length; i += batchSize) {
    const output = await inference('embed', { texts: records.slice(i, i + batchSize).map(r => r.text) });
    vectors.push(...output.vectors); embedMs += output.ms;
    $('progress').textContent = `向量化 ${Math.min(i + batchSize, records.length)} / ${records.length}`;
  }
  let result = { writeMs: 0, refreshMs: 0 };
  const encoded = records.map((r, i) => ({ ...r, vector: vectors[i] }));
  for (let i = 0; i < encoded.length; i += writeBatch) {
    const part = await api('import', { collection, dtype: model.dtype, records: encoded.slice(i, i + writeBatch) });
    result = { ...part, writeMs: result.writeMs + part.writeMs, refreshMs: result.refreshMs + part.refreshMs };
  }
  return { ...result, embedMs, importE2eMs: performance.now() - started };
}
$('import').onclick = () => action(async () => {
  const collection = $('collection').value;
  const docs = [];
  for (const file of $('files').files) {
    if (file.size > 2_000_000) throw new Error('单个文件限2MB');
    docs.push({ source: file.name, text: await file.text() });
  }
  if ($('text').value.trim()) docs.push({ source: '粘贴笔记', text: $('text').value });
  const records = [];
  for (const doc of docs) for (const [i, text] of chunks(doc.text).entries()) records.push({ id: await digest(`${doc.source}\n${i}\n${text}`), text, source: doc.source });
  if (!records.length || records.length > 128) throw new Error('每次需导入1至128个片段，请分批导入');
  const result = await importRecords(records, collection);
  $('progress').textContent = `已写入并刷新 ${result.imported} 个片段 · 当前库共 ${result.count} 个`;
  $('status').textContent = `向量化 ${result.embedMs.toFixed(0)}ms · 写入 ${result.writeMs.toFixed(0)}ms · 刷新 ${result.refreshMs.toFixed(0)}ms`;
});
async function search(query, collection) {
  const start = performance.now();
  const { vectors, ms: queryEmbedMs } = await inference('embed', { texts: [query] });
  const response = await api('search', { collection, dtype: model.dtype, query, vector: vectors[0] });
  return { ...response, queryEmbedMs, e2eMs: performance.now() - start };
}
function render(result) {
  $('results').replaceChildren();
  const ids = result.ids?.[0] || [];
  if (!ids.length) { $('results').textContent = '没有结果，请先向当前知识库导入资料。'; return; }
  ids.forEach((id, i) => {
    const article = document.createElement('article'); article.className = 'result';
    const title = document.createElement('h3'); title.textContent = `${i + 1}. ${result.metadatas?.[0]?.[i]?.source || '文档'}`;
    const text = document.createElement('p'); text.textContent = result.documents?.[0]?.[i] || '';
    const meta = document.createElement('small'); meta.textContent = `片段 ${id} · seekdb RRF 排序`;
    article.append(title, text, meta); $('results').append(article);
  });
}
$('search').onclick = () => action(async () => {
  const collection = $('collection').value, query = $('query').value.trim();
  if (!query) throw new Error('请输入查询');
  const response = await search(query, collection);
  render(response.result);
  $('status').textContent = `查询向量化 ${response.queryEmbedMs.toFixed(0)}ms · seekdb ${response.searchMs.toFixed(0)}ms · 端到端 ${response.e2eMs.toFixed(0)}ms`;
});
$('query').onkeydown = e => { if (e.key === 'Enter') $('search').click(); };
$('benchmark').onclick = () => action(async () => {
  report = { schema: 'stepfun.benchmark.v1', timestamp: new Date().toISOString(), userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, deviceMemory: navigator.deviceMemory, model: MODEL, revision: REVISION, runs: [] };
  $('export').disabled = false;
  const dataset = await fetch('/evaluation.json').then(r => r.json());
  try {
    for (const config of [{ dtype: 'fp32', forceWasm: true, batch: 1 }, { dtype: 'q8', forceWasm: true, batch: 1 }, { dtype: 'q8', forceWasm: true, batch: 8, writeBatch: 1 }, { dtype: 'q8', forceWasm: true, batch: 8, writeBatch: 128 }, { dtype: 'q8', forceWasm: false, batch: 8 }]) {
      const collection = `bench_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`;
      const runtime = await load(config.dtype, config.forceWasm);
      const run = { config, runtime, collection, imports: [], queries: [] }; report.runs.push(run);
      $('benchstatus').textContent = `运行 ${config.dtype}/${runtime.backend}/batch=${config.batch}…`;
      for (let repeat = 0; repeat < 3; repeat++) {
        run.imports.push({ repeat, ...await importRecords(dataset.documents, collection, config.batch, config.writeBatch || 128) });
        for (const item of dataset.queries) {
          const output = await search(item.text, collection);
          const ids = output.result.ids?.[0] || [];
          run.queries.push({ repeat, query: item.text, relevant: item.relevant, ids, ...metrics(ids, item.relevant), queryEmbedMs: output.queryEmbedMs, searchMs: output.searchMs, e2eMs: output.e2eMs });
        }
      }
      run.summary = {
        writeRefreshMedianMs: median(run.imports.slice(1).map(r => r.writeMs + r.refreshMs)),
        recallAt5: run.queries.reduce((s, q) => s + q.recall, 0) / run.queries.length,
        ndcgAt5: run.queries.reduce((s, q) => s + q.ndcg, 0) / run.queries.length,
        warmQueryE2eMedianMs: median(run.queries.filter(q => q.repeat > 0).map(q => q.e2eMs)),
        warmSearchMedianMs: median(run.queries.filter(q => q.repeat > 0).map(q => q.searchMs)),
        documentsPerSecond: dataset.documents.length * 1000 / median(run.imports.slice(1).map(r => r.embedMs)),
      };
      $('benchstatus').textContent = JSON.stringify(report.runs.map(r => ({ config: r.config, backend: r.runtime.backend, summary: r.summary })), null, 2);
    }
    report.completed = true;
  } catch (error) { report.error = error.message; throw error; }
  finally { await api('benchmark', report); $('precision').value = model?.dtype || 'q8'; $('wasm').checked = model?.backend === 'wasm'; }
});
$('export').onclick = () => {
  const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })); link.download = 'stepfun-benchmark.json'; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);
};
