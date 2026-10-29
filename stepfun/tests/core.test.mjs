import test from 'node:test';
import assert from 'node:assert/strict';
import { chunks, collectionName, validateVector, metrics, median } from '../core.mjs';
test('chunks preserve text and overlap across long documents', () => {
  const text = '0123456789'.repeat(250);
  const result = chunks(text);
  assert.equal(result.length, 4);
  assert.equal(result[0].slice(-120), result[1].slice(0, 120));
  assert.equal(result.at(-1).slice(-10), text.slice(-10));
  assert.deepEqual(chunks(' \r\n '), []);
});
test('database identifiers and vectors reject invalid inputs', () => {
  for (const value of ['x;DROP TABLE', '../test', '', 'A', 'a'.repeat(37)]) assert.throws(() => collectionName(value));
  assert.equal(collectionName('notes_2'), 'sf_notes_2');
  for (const value of [[], Array(384).fill(0), Array(384).fill(NaN), Array(384).fill('1')]) assert.throws(() => validateVector(value));
  assert.equal(validateVector(Array(384).fill(.1)).length, 384);
});
test('quality metrics use rank discounts and all relevant documents', () => {
  assert.deepEqual(metrics(['a', 'b'], ['a', 'b']), { recall: 1, ndcg: 1 });
  assert.equal(metrics(['a'], ['a', 'b']).recall, .5);
  assert.ok(metrics(['x', 'a'], ['a']).ndcg < 1);
  assert.equal(median([9, 1, 5, 3]), 4);
});
