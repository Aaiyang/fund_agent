import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { compileFunction } from 'node:vm';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const react = require('react');
const element = react.createElement;

function load(path, mocks = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const exports = {};
  compileFunction(code, ['exports', 'require'])(exports, (name) => mocks[name] ?? require(name));
  return exports;
}

// /portfolio/positions 每 (账户, 基金) 一行：022287 开在两个账户里。
const positions = [
  { fund_code: '022287', fund_name: '恒乐成长', account_id: 1, daily_return: 1.2, daily_profit_loss: 30, nav_date: '2026-10-13' },
  { fund_code: '000001', fund_name: '安泰债券', account_id: 2, daily_return: null, daily_profit_loss: null, nav_date: null },
  { fund_code: '022287', fund_name: '恒乐成长', account_id: 3, daily_return: 1.2, daily_profit_loss: 20, nav_date: '2026-10-13' },
];

function mountSheet(items) {
  const state = [];
  let cursor = 0;
  const rows = [];
  const fakeReact = { ...react, useState: (initial) => {
    if (state.length <= cursor) state.push(typeof initial === 'function' ? initial() : initial);
    const index = cursor++;
    return [state[index], (next) => { state[index] = typeof next === 'function' ? next(state[index]) : next; }];
  } };
  const native = {
    ActivityIndicator: () => null,
    KeyboardAvoidingView: ({ children }) => element('div', {}, children),
    Modal: ({ children, visible }) => (visible ? element('div', {}, children) : null),
    Platform: { OS: 'web' },
    Pressable: (props) => {
      if (props.accessibilityRole === 'checkbox') rows.push(props);
      return element('div', {}, props.children);
    },
    ScrollView: ({ children }) => element('div', {}, children),
    StyleSheet: { create: (input) => input, absoluteFill: {} },
    Text: ({ children, style }) => element('span', { style }, children),
    View: ({ children }) => element('div', {}, children),
  };
  const { FundPickerSheet } = load('../components/FundPickerSheet.tsx', {
    'react': fakeReact,
    'react-native': native,
    'react-native-safe-area-context': { useSafeAreaInsets: () => ({ bottom: 0 }) },
    '@/components/ui': {
      Button: ({ label }) => element('button', {}, label),
      Chip: ({ label }) => element('button', {}, label),
    },
    '@/constants/theme': load('../constants/theme.ts'),
    '@/hooks/usePortfolio': { usePositions: () => ({ isPending: false, data: { items } }) },
    '@/hooks/useWatchlist': { useWatchlist: () => ({ isPending: false, data: { items: [] } }) },
    '@/utils/fundPicker': load('../utils/fundPicker.ts'),
    '@/utils/format': load('../utils/format.ts'),
  });
  const render = () => {
    cursor = 0;
    rows.length = 0;
    return {
      html: renderToStaticMarkup(element(FundPickerSheet, { visible: true, onClose: () => undefined, onConfirm: () => undefined })),
      rows: rows.slice(),
    };
  };
  return { render };
}

test('one fund held in two accounts shows a single row that adds up both', () => {
  const view = mountSheet(positions).render();
  assert.deepEqual(view.rows.map((row) => row.disabled), [false, false]);
  assert.equal((view.html.match(/022287/g) ?? []).length, 1);
  assert.match(view.html, /涨幅对应收益合计 \+¥50\.00/);
  assert.match(view.html, /2 个账户/);
  // daily_return 是百分「点」：1.2 必须渲染成 +1.20%，不是 +120.00%
  assert.match(view.html, /\+1\.20%/);
  assert.doesNotMatch(view.html, /\+120\.00%/);
  assert.match(view.html, /截至 2026-10-13/);
  assert.match(view.html, /最新涨幅 未更新/);
});

test('one tap selects a fund and the very next tap clears it', () => {
  const sheet = mountSheet(positions);
  let view = sheet.render();
  view.rows[0].onPress();
  view = sheet.render();
  assert.match(view.html, /已选 1 只，还可选 2 只/);
  assert.match(view.html, /恒乐成长/);

  view.rows[0].onPress();
  view = sheet.render();
  assert.match(view.html, /最多可选3只/);
  assert.doesNotMatch(view.html, /已选/);
});

test('a full selection still lets the user undo any of the chosen rows', () => {
  const sheet = mountSheet([...positions, { fund_code: '000002', fund_name: '中信新材', account_id: 2, daily_return: 0.4, daily_profit_loss: 8, nav_date: '2026-10-13' }]);
  const tap = (index) => {
    const before = sheet.render();
    before.rows[index].onPress();
    return sheet.render();
  };
  let view = tap(0);
  view = tap(1);
  view = tap(2);
  assert.match(view.html, /已选 3 只，已达上限/);
  view.rows.forEach((row) => assert.equal(row.disabled, false));

  view = tap(1);
  assert.match(view.html, /已选 2 只，还可选 1 只/);
});
