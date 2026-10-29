export const MODEL = 'Xenova/all-MiniLM-L6-v2';
export const REVISION = '751bff37182d3f1213fa05d7196b954e230abad9';
export const DIMENSION = 384;
export function collectionName(name) {
  if (typeof name !== 'string' || !/^[a-z][a-z0-9_]{0,35}$/.test(name)) throw new Error('知识库名称须为小写字母开头，限字母、数字、下划线，最多36位');
  return `sf_${name}`;
}
export function validateVector(vector) {
  if (!Array.isArray(vector) || vector.length !== DIMENSION || vector.some(x => typeof x !== 'number' || !Number.isFinite(x)) || !vector.some(x => x !== 0)) throw new Error('需要浏览器生成的384维有限非零向量');
  return vector;
}
export function chunks(text, size = 900, overlap = 120) {
  const normalized = text.replace(/\r\n/g, '\n').trim();
  const result = [];
  for (let start = 0; start < normalized.length; start += size - overlap) {
    result.push(normalized.slice(start, start + size));
    if (start + size >= normalized.length) break;
  }
  return result;
}
export function metrics(ids, relevant, k = 5) {
  const ranked = ids.slice(0, k);
  const hits = ranked.filter(id => relevant.includes(id)).length;
  const dcg = ranked.reduce((s, id, i) => s + (relevant.includes(id) ? 1 / Math.log2(i + 2) : 0), 0);
  const ideal = relevant.slice(0, k).reduce((s, _, i) => s + 1 / Math.log2(i + 2), 0);
  return { recall: hits / relevant.length, ndcg: dcg / ideal };
}
export function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const m = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[m] : (sorted[m - 1] + sorted[m]) / 2;
}
