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

test('role outcomes count failures without reading a skipped role as one', () => {
  const outcomes = [
    { role: 'fundamentals', status: 'failed' },
    { role: 'risk', status: 'failed' },
    { role: 'portfolio', status: 'skipped' },
  ];
  // 分母只算这轮真该出结论的两个角色，"无需执行"单独说一句。
  assert.equal(exports.describeRoleOutcomes(outcomes), '2 个角色里 2 个失败 · 1 个无需执行');
  assert.equal(exports.describeRoleOutcomes(outcomes, 'failed'), '2 个角色里 2 个失败 · 1 个无需执行 · 交叉审核未完成');
  assert.equal(
    exports.describeRoleOutcomes([{ role: 'risk', status: 'partial' }, { role: 'portfolio', status: 'skipped' }], 'partial'),
    '1 个角色里 1 个有待确认项 · 1 个无需执行 · 交叉审核有待确认项',
  );
  assert.equal(exports.describeRoleOutcomes([{ role: 'risk', status: 'completed' }]), '1 个角色已完成');
  // 全跳过不是"没有信息"，恰恰是要说出口的一句实话。
  assert.equal(exports.describeRoleOutcomes([{ role: 'risk', status: 'skipped' }]), '1 个角色本轮无需执行');
  assert.equal(
    exports.describeRoleOutcomes([{ role: 'risk', status: 'skipped' }], 'failed'),
    '1 个角色本轮无需执行 · 交叉审核未完成',
  );
  assert.equal(exports.describeRoleOutcomes([]), undefined);
});

test('live outcomes come from the last round per role and ignore in-flight roles', () => {
  const revision = (role, status) => ({ kind: 'research_progress', run_id: 'run', stage: 'revision', role, status });
  let progress = exports.mergeResearchProgress([], event('risk', 'started'));
  progress = exports.mergeResearchProgress(progress, event('risk', 'completed'));
  progress = exports.mergeResearchProgress(progress, event('fundamentals', 'started'));
  // 对象是在 vm 上下文里造的，deepEqual 会比原型，这里只比内容。
  assert.equal(JSON.stringify(exports.roleOutcomesFromProgress(progress)), '[{"role":"risk","status":"completed"}]');
  progress = exports.mergeResearchProgress(progress, revision('risk', 'partial'));
  assert.equal(JSON.stringify(exports.roleOutcomesFromProgress(progress)), '[{"role":"risk","status":"partial"}]');
});

test('the activity line is prefixed with the role and stays single-line', () => {
  assert.equal(exports.describeResearchActivity({ role: 'risk', text: '先核净值 再算回撤' }), '风险分析员 · 先核净值 再算回撤');
  assert.equal(exports.describeResearchActivity({ role: null, text: '比对三份发现' }), '比对三份发现');
});
