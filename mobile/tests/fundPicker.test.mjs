import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileFunction } from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../utils/fundPicker.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exported = {};
compileFunction(compiled, ['exports'])(exported);
const { MAX_PICKER_FUNDS, dedupePickerFunds, togglePickerFund, pickerRowDisabled, pickerActionLabel, pickerHint, summarizeHoldings, composeResearchQuestion } = exported;

const fund = (code) => ({ code, name: `基金${code}` });

test('selection keeps tap order, cancels on re-tap and stops at the cap', () => {
  let selected = [];
  selected = togglePickerFund(selected, fund('000002'));
  selected = togglePickerFund(selected, fund('000001'));
  assert.deepEqual(selected.map((item) => item.code), ['000002', '000001']);

  selected = togglePickerFund(selected, fund('000002'));
  assert.deepEqual(selected.map((item) => item.code), ['000001']);

  const full = ['000001', '000002', '000003'].reduce((acc, code) => togglePickerFund(acc, fund(code)), []);
  assert.equal(full.length, MAX_PICKER_FUNDS);
  assert.deepEqual(togglePickerFund(full, fund('000004')), full);
});

test('only unselected rows lock once the cap is reached', () => {
  const full = ['000001', '000002', '000003'].reduce((acc, code) => togglePickerFund(acc, fund(code)), []);
  assert.equal(pickerRowDisabled(full, '000004'), true);
  // 已选中的行必须还能点，否则用户没法取消误选
  assert.equal(pickerRowDisabled(full, '000002'), false);
  assert.equal(pickerRowDisabled([], '000004'), false);
});

test('the same fund held in two accounts shows up once and never twice', () => {
  // /portfolio/positions 不带 account_id 时每(账户,基金)一行，不去重就会出现重复 key
  const rows = [
    { code: '022287', name: 'A' },
    { code: '000001', name: 'B' },
    { code: '022287', name: 'A' },
  ];
  assert.deepEqual(dedupePickerFunds(rows), [{ code: '022287', name: 'A' }, { code: '000001', name: 'B' }]);
  assert.deepEqual(dedupePickerFunds([]), []);
  const codes = dedupePickerFunds(rows).map((item) => item.code);
  assert.equal(new Set(codes).size, codes.length);
});

test('cross-account holdings keep one rate but add up the money', () => {
  const summary = summarizeHoldings([
    { daily_return: 1.2, daily_profit_loss: 30 },
    { daily_return: 1.2, daily_profit_loss: 20 },
  ]);
  assert.deepEqual(summary, { rate: 1.2, profit: 50, accounts: 2 });

  // 收益率是同源净值涨幅，缺行情时不能拿另一账户的百分比顶替金额口径
  assert.deepEqual(summarizeHoldings([{ daily_return: null, daily_profit_loss: null }]), {
    rate: null, profit: null, accounts: 1,
  });
  assert.deepEqual(summarizeHoldings([]), { rate: null, profit: null, accounts: 0 });
});

test('button label and hint follow how many funds are in scope', () => {
  assert.equal(pickerActionLabel(1), '分析');
  assert.equal(pickerActionLabel(2), '对比分析');
  assert.equal(pickerHint(0), '最多可选3只');
  assert.equal(pickerHint(2), '已选 2 只，还可选 1 只');
  assert.equal(pickerHint(3), '已选 3 只，已达上限');
});

test('question text reads naturally but carries both codes for the structured field', () => {
  const one = composeResearchQuestion([fund('022287')]);
  assert.match(one, /请分析这只基金/);
  assert.ok(one.includes('022287'));
  const two = composeResearchQuestion([fund('022287'), fund('000001')]);
  assert.match(two, /请对比这几只基金/);
  assert.ok(two.includes('022287') && two.includes('000001'));
});
