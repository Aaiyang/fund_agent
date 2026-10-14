import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const compiled = ts.transpileModule(readFileSync(new URL('../utils/researchProgress.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exports = {};
vm.runInNewContext(compiled, { exports });
const event = (role, status, run_id = 'run') => ({ kind: 'research_progress', run_id, stage: 'analysis', role, status });

test('parallel role progress merges in either completion order and isolates runs', () => {
  let progress = exports.mergeResearchProgress([], event('risk', 'started'));
  progress = exports.mergeResearchProgress(progress, event('fundamentals', 'started'));
  progress = exports.mergeResearchProgress(progress, event('risk', 'completed'));
  assert.equal(progress.length, 2);
  assert.match(exports.describeResearchProgress(progress), /基金研究员进行中/);
  assert.match(exports.describeResearchProgress(progress), /风险分析员已完成/);
  assert.equal(exports.mergeResearchProgress(progress, event('risk', 'failed', 'another')), progress);
});

test('review and revision display their public stage without hiding partial failures', () => {
  let progress = exports.mergeResearchProgress([], event('risk', 'failed'));
  assert.match(exports.describeResearchProgress(progress), /风险分析员未完成/);
  progress = exports.mergeResearchProgress(progress, { ...event(null, 'started'), stage: 'review' });
  assert.equal(exports.describeResearchProgress(progress), '交叉审核：进行中');
});

test('late callbacks cannot restart a completed role or move the displayed stage backwards', () => {
  let progress = exports.mergeResearchProgress([], event('risk', 'completed'));
  assert.equal(exports.mergeResearchProgress(progress, event('risk', 'started')), progress);
  progress = exports.mergeResearchProgress(progress, { ...event(null, 'started'), stage: 'review' });
  progress = exports.mergeResearchProgress(progress, event('fundamentals', 'completed'));
  assert.equal(exports.describeResearchProgress(progress), '交叉审核：进行中');
});
