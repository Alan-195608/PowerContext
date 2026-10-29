import express from 'express';
import { SeekdbClient, Schema, VectorIndexConfig, FulltextIndexConfig } from 'seekdb';
import { collectionName, validateVector, DIMENSION, MODEL, REVISION } from './core.mjs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { writeFile, mkdir } from 'node:fs/promises';
const root = path.dirname(fileURLToPath(import.meta.url));
const client = new SeekdbClient(process.env.SEEKDB_HOST ? {
  host: process.env.SEEKDB_HOST, port: Number(process.env.SEEKDB_PORT || 2881),
  user: process.env.SEEKDB_USER || 'root', password: process.env.SEEKDB_PASSWORD || '',
  database: process.env.SEEKDB_DATABASE || 'test',
} : { path: process.env.SEEKDB_PATH || path.join(root, '.seekdb'), database: 'test' });
const app = express();
app.use((req, res, next) => {
  // Local service: forbid requests from arbitrary websites to the local DB proxy.
  if (req.headers.origin && req.headers.origin !== `http://${req.headers.host}` && req.headers.origin !== `https://${req.headers.host}`) return res.status(403).json({ error: '跨站请求被拒绝' });
  next();
});
app.use(express.json({ limit: '12mb' }));
const queues = new Map();
async function withCollection(body, operation) {
  const { dtype } = body;
  if (!['fp32', 'q8'].includes(dtype)) throw new Error('无效模型精度');
  const name = `${collectionName(body.collection)}_${dtype}`;
  const previous = queues.get(name) || Promise.resolve();
  const current = previous.catch(() => {}).then(async () => {
    const collection = await client.getOrCreateCollection({ name, embeddingFunction: null, schema: new Schema({
      vectorIndex: new VectorIndexConfig({ hnsw: { dimension: DIMENSION, distance: 'cosine' }, embeddingFunction: null }),
      fulltextIndex: new FulltextIndexConfig('beng'),
    }) });
    return operation(collection);
  });
  queues.set(name, current);
  try { return await current; } finally { if (queues.get(name) === current) queues.delete(name); }
}
app.get('/api/health', async (req, res) => {
  res.json({ collections: await client.countCollection(), model: MODEL, revision: REVISION, storage: 'seekdb' });
});
app.post('/api/import', async (req, res) => {
  const { records } = req.body;
  if (!Array.isArray(records) || !records.length || records.length > 128) throw new Error('每次导入1至128个片段');
  // Validate the entire request before any writes.
  for (const record of records) {
    if (typeof record.id !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(record.id) || typeof record.text !== 'string' || !record.text.trim() || record.text.length > 2000 || typeof record.source !== 'string' || record.source.length > 250) throw new Error('无效文档片段');
    validateVector(record.vector);
  }
  res.json(await withCollection(req.body, async collection => {
    let start = performance.now();
    for (let i = 0; i < records.length; i += 64) {
      const batch = records.slice(i, i + 64);
      await collection.upsert({ ids: batch.map(r => r.id), documents: batch.map(r => r.text), embeddings: batch.map(r => r.vector), metadatas: batch.map(r => ({ source: r.source, model: MODEL, revision: REVISION, dtype: req.body.dtype })) });
    }
    const writeMs = performance.now() - start;
    start = performance.now();
    await collection.refresh_index();
    const refreshMs = performance.now() - start;
    // Verify persistence before acknowledging import, even if the server has no refresh procedure.
    const persisted = await collection.get({ ids: records.map(r => r.id), include: ['documents'] });
    if (persisted.ids.length !== records.length) throw new Error('写入确认失败，请使用相同文档重试');
    return { count: await collection.count(), imported: records.length, writeMs, refreshMs };
  }));
});
app.post('/api/search', async (req, res) => {
  const { query, vector } = req.body;
  if (typeof query !== 'string' || !query.trim() || query.length > 1000) throw new Error('查询长度须为1至1000字符');
  validateVector(vector);
  res.json(await withCollection(req.body, async collection => {
    const start = performance.now();
    const result = await collection.hybridSearch({
      query: { whereDocument: { $contains: query }, nResults: 20 },
      knn: { queryEmbeddings: [vector], nResults: 20 },
      rank: { rrf: { rankConstant: 60 } }, nResults: 5,
      include: ['documents', 'metadatas', 'distances'],
    });
    return { result, searchMs: performance.now() - start };
  }));
});
app.post('/api/benchmark', async (req, res) => {
  if (req.body.schema !== 'stepfun.benchmark.v1' || !Array.isArray(req.body.runs)) throw new Error('无效测量记录');
  await mkdir(path.join(root, 'results'), { recursive: true });
  await writeFile(path.join(root, 'results/browser-benchmark.json'), JSON.stringify(req.body, null, 2) + '\n');
  res.json({ saved: true });
});
app.use('/api', (req, res) => res.status(404).json({ error: '未知API' }));
if (process.env.NODE_ENV === 'production') app.use(express.static(path.join(root, 'dist')));
else {
  const { createServer } = await import('vite');
  const vite = await createServer({ root, server: { middlewareMode: true }, appType: 'spa' });
  app.use(vite.middlewares);
}
app.use((error, req, res, next) => { console.error(error.message); res.status(400).json({ error: error.message }); });
const server = app.listen(Number(process.env.PORT || 5173), '127.0.0.1', () => console.log('本地知库 http://127.0.0.1:' + (process.env.PORT || 5173)));
process.on('SIGINT', async () => { await client.close(); server.close(); process.exit(0); });
