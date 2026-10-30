import assert from 'node:assert/strict';
import test from 'node:test';
import {z} from 'zod';

test('ограниченная коллекция отклоняется до преобразования лишних элементов', () => {
  let visited = 0;
  const schema = z.array(z.string().transform(value => { visited++; return value; })).max(2);
  const rejected = schema.safeParse(Array(10000).fill('слишком много'));
  assert.equal(rejected.success, false);
  assert.equal(visited, 0);
  assert.deepEqual(schema.parse(['один', 'два']), ['один', 'два']);
  assert.equal(visited, 2);
});
