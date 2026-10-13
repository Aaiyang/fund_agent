import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileFunction } from 'node:vm';
import ts from 'typescript';

const code = ts.transpileModule(readFileSync(new URL('../utils/personaEditor.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const helpers = {};
compileFunction(code, ['exports'])(helpers);
const { buildPersonaChanges, countPersonaFields } = helpers;

test('new user remains unknown; opening an editor does not create default preferences', () => {
  assert.equal(countPersonaFields({}), 0);
  assert.deepEqual(buildPersonaChanges('investment', {}, {}, '', ''), {});
  assert.deepEqual(buildPersonaChanges('assistant', {}, {}, '', ''), {});
  assert.deepEqual(buildPersonaChanges('goals', {}, {}, '', ''), {});
});

test('group save preserves other profile fields and skips untouched values', () => {
  const original = { risk_preference: 'conservative', investment_horizon_months: 36, response_language: 'zh-CN' };
  assert.deepEqual(buildPersonaChanges('assistant', original, { ...original, response_detail: 'detailed', risk_preference: 'aggressive' }, '', ''), {
    response_detail: 'detailed',
  });
});

test('removing the last exclusion explicitly deletes the setting', () => {
  assert.deepEqual(buildPersonaChanges('investment', { excluded_fund_types: ['qdii'] }, { excluded_fund_types: [] }, '', ''), {
    excluded_fund_types: null,
  });
});

test('clearing a goal and horizon submits null, not empty strings or guessed defaults', () => {
  assert.deepEqual(buildPersonaChanges('goals', { investment_goals: ['购房'], investment_horizon_months: 36 }, { investment_goals: [] }, ' ', ''), {
    investment_goals: null, investment_horizon_months: null,
  });
});

test('a typed new goal is included on save even if Add was not tapped', () => {
  assert.deepEqual(buildPersonaChanges('goals', {}, { investment_goals: ['  长期积累  '] }, '36', '  退休储备  '), {
    investment_goals: ['长期积累', '退休储备'], investment_horizon_months: 36,
  });
});

for (const value of ['0', '601', '-1', '1.5', '1e2', 'true', '十二']) {
  test(`invalid horizon ${value} cannot overwrite the stored profile`, () => {
    assert.throws(() => buildPersonaChanges('goals', {}, {}, value, ''), /整数月份/);
  });
}

test('duplicate, blank, too-long and excessive goals are rejected before submission', () => {
  for (const goals of [['重复', ' 重复 '], [''], ['字'.repeat(121)], ['1', '2', '3', '4', '5', '6']]) {
    assert.throws(() => buildPersonaChanges('goals', {}, { investment_goals: goals }, '', ''));
  }
});

test('explicit single-field correction does not erase goals or language', () => {
  const original = { risk_preference: 'conservative', investment_goals: ['长期积累'], response_language: 'en' };
  assert.deepEqual(buildPersonaChanges('investment', original, { ...original, risk_preference: null }, '', ''), { risk_preference: null });
  assert.deepEqual(original.investment_goals, ['长期积累']);
});
