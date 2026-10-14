import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileFunction } from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../utils/tradeRequestKey.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
compileFunction(compiled, ['exports'])(exports);
const { tradeRequestKey } = exports;

test('a repeated submission keeps its key while changed orders get a different key', () => {
  const keys = new Map();
  const payload = { account_id: 7, amount: 100 };
  const first = tradeRequestKey(keys, payload);
  assert.equal(tradeRequestKey(keys, { ...payload }), first);
  assert.notEqual(tradeRequestKey(keys, { ...payload, amount: 200 }), first);
  keys.clear();
  assert.notEqual(tradeRequestKey(keys, payload), first);
  assert.ok(first.length <= 64);
});
