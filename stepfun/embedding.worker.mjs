import { pipeline, env } from '@huggingface/transformers';
import { MODEL, REVISION } from './core.mjs';
env.allowLocalModels = true;
env.localModelPath = '/models/';
env.allowRemoteModels = false;
let extractor;
self.onmessage = async ({ data }) => {
  const { id, op } = data;
  try {
    if (op === 'load') {
      if (extractor) await extractor.dispose();
      const started = performance.now();
      let backend = 'wasm', fallback = data.forceWasm ? '用户强制WASM' : 'WebGPU不可用';
      const progress_callback = event => self.postMessage({ id, progress: event });
      const options = { revision: REVISION, dtype: data.dtype, progress_callback };
      if (!data.forceWasm && navigator.gpu) {
        try {
          if (await navigator.gpu.requestAdapter()) {
            extractor = await pipeline('feature-extraction', MODEL, { ...options, device: 'webgpu' });
            // Actually execute: backend initialization can fail lazily.
            await extractor('warmup', { pooling: 'mean', normalize: true });
            backend = 'webgpu'; fallback = null;
          }
        } catch (error) {
          fallback = `WebGPU初始化失败，自动降级：${error.message}`;
          if (extractor) await extractor.dispose();
          extractor = null;
        }
      }
      if (backend === 'wasm') extractor = await pipeline('feature-extraction', MODEL, { ...options, device: 'wasm' });
      self.postMessage({ id, result: { backend, fallback, loadMs: performance.now() - started, dtype: data.dtype, model: MODEL, revision: REVISION } });
    } else if (op === 'embed') {
      if (!extractor) throw new Error('模型未加载');
      const started = performance.now();
      const output = await extractor(data.texts, { pooling: 'mean', normalize: true, truncation: true });
      self.postMessage({ id, result: { vectors: output.tolist(), ms: performance.now() - started } });
    }
  } catch (error) { self.postMessage({ id, error: error.message }); }
};
