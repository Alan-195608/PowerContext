// Real seekdb integration. Synthetic vectors exercise storage/ranking only, not model quality.
import assert from 'node:assert/strict';
const base = process.env.APP_URL || 'http://127.0.0.1:5173';
const run = `accept_${Date.now().toString(36)}`;
const vector = Array(384).fill(0); vector[0] = 1;
const post = async (route, data) => {
  const response = await fetch(`${base}/api/${route}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const body = await response.json();
  assert.ok(response.ok, JSON.stringify(body)); return body;
};
const settings = { collection: run, dtype: 'q8' };
const doc = { id: 'incremental_one', text: 'quasarx unique fresh document about database indexing', source: 'one.txt', vector };
const first = await post('import', { ...settings, records: [doc] });
assert.equal(first.count, 1);
assert.equal((await post('import', { ...settings, records: [doc] })).count, 1);
const second = await post('import', { ...settings, records: [{ ...doc, id: 'incremental_two', text: 'novelxyz newly imported document about browser inference' }] });
assert.equal(second.count, 2);
const found = await post('search', { ...settings, query: 'novelxyz', vector });
assert.ok(found.result.ids[0].includes('incremental_two'));
const isolated = await post('search', { ...settings, collection: run + '_other', query: 'novelxyz', vector });
assert.equal(isolated.result.ids[0].length, 0);
const precision = await post('search', { ...settings, dtype: 'fp32', query: 'novelxyz', vector });
assert.equal(precision.result.ids[0].length, 0);
const malformed = await fetch(`${base}/api/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...settings, records: [doc, { ...doc, id: 'invalid', vector: [1] }] }) });
assert.equal(malformed.status, 400);
const attack = await fetch(`${base}/api/search`, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: 'https://example.com' }, body: '{}' });
assert.equal(attack.status, 403);
console.log(JSON.stringify({ status: 'passed', timestamp: new Date().toISOString(), storage: 'real seekdb', collection: run, checks: ['incremental write', 'idempotent import', 'search after refresh', 'collection isolation', 'precision isolation', 'invalid vector rejection', 'cross-site rejection'], first, second }, null, 2));
