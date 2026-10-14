import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const exports = {};
const source = readFileSync(new URL('../api/client.ts', import.meta.url), 'utf8');
vm.runInNewContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, {
  exports, process: { env: {} },
  require(name) {
    assert.equal(name, '@/api/tokenStore');
    return {};
  },
});

test('fund selection and continuation failures show recovery guidance while retaining error codes', () => {
  for (const code of [
    'fund_selection_resume_failed_check_status',
    'fund_selection_resume_timeout_check_status',
    'agent_continue_failed_check_status',
    'agent_continue_timeout_check_status',
  ]) {
    const error = exports.apiError(503, 'Service Unavailable', JSON.stringify({ detail: code }));
    assert.equal(error.code, code);
    assert.equal(error.status, 503);
    assert.match(error.message, /研究/);
    assert.match(error.message, /继续|重试/);
    assert.ok(!error.message.includes('_check_status'));
  }
});

test('unrelated API errors preserve server messages and validation details', () => {
  assert.equal(exports.apiError(400, '', '{"detail":"余额不足"}').message, '余额不足');
  const validation = exports.apiError(422, '', '{"errors":[{"message":"缺少代码"},{"message":"金额无效"}]}');
  assert.equal(validation.code, 'validation_error');
  assert.equal(validation.message, '缺少代码；金额无效');
});
