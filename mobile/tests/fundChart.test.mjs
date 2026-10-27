import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import { compileFunction } from 'node:vm';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { fence, fixture, loadChartContract, registerFundChartTests } from '../../shared/tests/fund-chart-tests.mjs';

registerFundChartTests(ts);
const require = createRequire(import.meta.url);
const contract = loadChartContract(ts);
const element = require('react').createElement;
const reference = JSON.parse(readFileSync(new URL('../../shared/tests/fund-chart-reference.fixture.json', import.meta.url), 'utf8'));

function loadComponent(path, mocks = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  const exports = {};
  compileFunction(compiled, ['exports', 'require'])(exports, (name) => {
    if (name === '../../shared/fund-chart') return contract;
    return mocks[name] ?? require(name);
  });
  return exports;
}

const native = {
  View: ({ children }) => element('div', {}, children),
  Text: ({ children }) => element('span', {}, children),
  ScrollView: ({ children }) => element('div', {}, children),
  Pressable: ({ children, disabled }) => element('button', { disabled }, children),
};
const svg = { default: 'svg', Circle: 'circle', Line: 'line', Polyline: 'polyline', __esModule: true };
const platform = { OS: 'web', select: (options) => options.web ?? options.default };
const { theme } = loadComponent('../constants/theme.ts', { 'react-native': { Platform: platform } });
const format = loadComponent('../utils/format.ts', { '@/constants/theme': { theme } });
const { NavChart } = loadComponent('../components/NavChart.tsx', {
  'react-native': native, 'react-native-svg': svg, '@/constants/theme': { theme }, '@/utils/format': format,
  react: { ...require('react'), useState: (initial) => require('react').useState(initial === 0 ? 320 : initial) },
});
const ui = {
  Card: native.View, SectionTitle: ({ title }) => element('h3', {}, title),
  Chip: ({ label }) => element('button', {}, label),
  Stat: ({ label, value }) => element('span', {}, `${label} ${value}`),
  Button: ({ label }) => element('button', {}, label),
};
const states = loadComponent('../components/states.tsx', {
  'react-native': { ...native, ActivityIndicator: () => element('span', {}, '加载中') },
  '@/components/ui': ui, '@/constants/theme': { theme },
});
const ready = (data) => ({ data, isPending: false, isError: false, refetch: () => Promise.resolve() });
const navData = { points: [
  { nav_date: '2025-10-10', unit_nav: 1 }, { nav_date: '2026-10-10', unit_nav: 1.7 },
] };
let navQuery = ready(navData);
const requested = [];
const funds = {
  NAV_RANGES: ['1m', '3m', '6m', '1y', '3y', 'all'].map((key) => ({ key, label: key })),
  useFundDetail: (code) => {
    requested.push(['detail', code]);
    return ready({ fund_name: '后端基金名称', nav_date: '2026-10-10', performance: { return_1y: 0.7 } });
  },
  useFundNav: (code, range) => { requested.push(['nav', code, range]); return navQuery; },
};
const indexes = {
  DEFAULT_BENCHMARK: 'sh000300',
  useIndexCatalog: () => ready({ items: [{ index_code: 'sh000300', name: '沪深300' }] }),
  useIndexHistory: (code, range) => {
    requested.push(['index', code, range]);
    return ready({ name: '沪深300', points: [
      { trade_date: '2025-10-10', close: 4000 }, { trade_date: '2026-10-10', close: 4200 },
    ] });
  },
};
const performanceMocks = {
  'react-native': native, '@/components/NavChart': { NavChart }, '@/components/ui': ui,
  '@/components/states': states, '@/constants/theme': { theme }, '@/utils/format': format,
  '@/hooks/useFunds': funds, '@/hooks/useIndexes': indexes,
};
const { FundPerformanceCard } = loadComponent('../components/FundPerformanceCard.tsx', performanceMocks);
const { FundAnalysisChart } = loadComponent('../components/FundAnalysisChart.tsx', {
  '@/components/FundPerformanceCard': { FundPerformanceCard },
});
const { FundHoldingsCard } = loadComponent('../components/FundHoldingsCard.tsx', {
  'react-native': native, '@/constants/theme': { theme }, '@/utils/format': format,
});
const { MarkdownText } = loadComponent('../components/MarkdownText.tsx', {
  'react-native': native, '@/constants/theme': { theme }, '@/components/FundAnalysisChart': { FundAnalysisChart },
  '@/components/FundHoldingsCard': { FundHoldingsCard },
  '@/components/ResearchDataCard': { ResearchDataCard: () => element('div', {}, '研究卡片') },
  '@/components/ResearchEvidenceSheet': { ResearchEvidenceSheet: () => null },
  'expo-symbols': { SymbolView: () => null },
});

test('reference and legacy assistant charts both use API data and the detail NavChart', () => {
  for (const chart of [reference, { ...fixture, title: '<script>bad()</script>', points: fixture.points.map((p) => ({ ...p, unit_nav: 999 })) }]) {
    requested.length = 0;
    const html = renderToStaticMarkup(element(MarkdownText, { content: '## 潜力\n' + fence(chart) + '\n后续建议' }));
    assert.match(html, /<svg|<polyline/);
    assert.match(html, /业绩走势|后端基金名称|沪深300/);
    assert.match(html, /2026-10-10|未做分红复权|\+70.00%/);
    assert.match(html, /潜力|后续建议/);
    assert.doesNotMatch(html, /999|schema_version|bad\(\)|历史存在缺口/);
    assert.deepEqual(requested, [['detail', '000001'], ['nav', '000001', '1y'], ['index', 'sh000300', '1y']]);
  }
  const legacyAdapter = FundAnalysisChart({ chart: fixture });
  assert.equal(legacyAdapter.type, FundPerformanceCard);
  assert.deepEqual(legacyAdapter.props, { fundCode: '000001' });
});

test('v2 accepts only fund identifiers; malformed/partial content never fetches', () => {
  assert.deepEqual(contract.parseFundChart(JSON.stringify(reference)), reference);
  for (const chart of [
    { ...reference, fund_code: 1 }, { ...reference, fund_code: '../auth' },
    { ...reference, points: [] }, { ...reference, url: 'https://example.com' },
    { ...reference, costNav: 1 }, { ...reference, user_id: 2 }, { ...reference, schema_version: 3 },
  ]) assert.equal(contract.parseFundChart(JSON.stringify(chart)), null);
  const raw = fence(reference);
  for (let end = 1; end < raw.length; end++) assert.equal(contract.splitFundAnalysisBlocks(raw.slice(0, end))[0].kind, 'text');
  for (const content of [raw.slice(0, -3), fence({ ...reference, script: 'alert(1)' })]) {
    requested.length = 0;
    const html = renderToStaticMarkup(element(MarkdownText, { content }));
    assert.doesNotMatch(html, /<svg/);
    assert.match(html, /schema_version/);
    assert.deepEqual(requested, []);
  }
});

function find(node, predicate) {
  if (!node || typeof node !== 'object') return null;
  if (predicate(node)) return node;
  for (const child of [].concat(node.props?.children ?? [])) {
    const result = find(child, predicate);
    if (result) return result;
  }
  return null;
}

test('range and benchmark controls reselect API queries; retry and empty states remain available', () => {
  let state = 0;
  const calls = [];
  const { FundPerformanceCard: Probe } = loadComponent('../components/FundPerformanceCard.tsx', {
    ...performanceMocks,
    react: { useState: () => [['3m', 'sh000300', false][state++], (v) => calls.push(v)] },
  });
  const tree = Probe({ fundCode: '000002' });
  assert.deepEqual(requested.slice(-3), [['detail', '000002'], ['nav', '000002', '3m'], ['index', 'sh000300', '3m']]);
  find(tree, (n) => n.type === ui.Chip && n.props.label === '6m').props.onPress();
  const chartTree = find(tree, (n) => n.type === states.Async).props.children(navData);
  find(chartTree, (n) => n.type === NavChart).props.benchmarkPicker.onPick('sh000001');
  assert.deepEqual(calls, ['6m', 'sh000001', false]);
  navQuery = { isPending: true };
  assert.match(renderToStaticMarkup(element(FundPerformanceCard, { fundCode: '000001' })), /加载中/);
  navQuery = { isError: true, error: new Error('净值请求失败'), refetch: () => {} };
  const failedTree = Probe({ fundCode: '000001' });
  const asyncNode = find(failedTree, (n) => n.type === states.Async);
  const errorTree = states.Async(asyncNode.props);
  assert.equal(errorTree.type, states.ErrorState);
  let retries = 0;
  navQuery.refetch = () => { retries++; };
  errorTree.props.onRetry();
  assert.equal(retries, 1);
  navQuery = ready({ points: [] });
  assert.match(renderToStaticMarkup(element(FundPerformanceCard, { fundCode: '000001' })), /还没有净值数据/);
  navQuery = ready(navData);
});

test('existing hooks request the canonical endpoints with shared query keys', async () => {
  const queryKeys = loadComponent('../api/queries.ts').queryKeys;
  const requests = [];
  const api = { get: async (...args) => { requests.push(args); } };
  const mocks = {
    '@tanstack/react-query': { useQuery: (options) => options },
    'expo-router': {}, '@/api/client': { api }, '@/api/queries': { queryKeys },
  };
  const realFunds = loadComponent('../hooks/useFunds.ts', mocks);
  const realIndexes = loadComponent('../hooks/useIndexes.ts', { ...mocks, '@/hooks/useFunds': {} });
  const nav = realFunds.useFundNav('000001', '6m');
  const index = realIndexes.useIndexHistory('sh000300', '6m');
  await nav.queryFn(); await index.queryFn();
  assert.deepEqual(requests, [['/funds/000001/nav', { range: '6m' }], ['/indexes/sh000300/history', { range: '6m' }]]);
  assert.deepEqual(nav.queryKey, queryKeys.fundNav('000001', '6m'));
  assert.equal(realFunds.useFundNav(null, '1y').enabled, false);
});

const holdings = JSON.parse(readFileSync(new URL('../../shared/tests/fund-holdings.fixture.json', import.meta.url), 'utf8'));
const holdingsFence = (card = holdings) => '```fund-holdings\n' + JSON.stringify(card) + '\n```';
test('fund reference cards coexist with holdings, prose and research tables', () => {
  const html = renderToStaticMarkup(element(MarkdownText, { content: '## 关键结论\n' + fence(reference) + '\n## 持仓特点\n' + holdingsFence()
    + '\n| 指标 | 数值 |\n|---|---|\n| 最大回撤 | 数据不足 |' }));
  for (const value of ['业绩走势', '重仓股票占比', '测试股票A', '9.45%', '2026年2季度', '最大回撤']) assert.ok(html.includes(value));
  assert.doesNotMatch(html, /schema_version/);
});

test('holdings reject invalid weights, duplicates, extra fields and partial streamed fences', () => {
  for (const update of [
    (c) => { c.items[0].weight = -1; }, (c) => { c.items[0].weight = 101; },
    (c) => { c.items[0].weight = '9.45'; }, (c) => { c.items[0].url = 'https://example.com'; },
    (c) => { c.items[1].stock_code = c.items[0].stock_code; }, (c) => { c.schema_version = 2; },
    (c) => { c.items = []; }, (c) => { c.items = Array(11).fill(c.items[0]); },
  ]) {
    const data = structuredClone(holdings); update(data);
    assert.equal(contract.parseFundHoldings(JSON.stringify(data)), null);
    assert.equal(contract.splitFundAnalysisBlocks(holdingsFence(data))[0].kind, 'text');
  }
  const raw = holdingsFence();
  for (let end = 1; end < raw.length; end++) assert.equal(contract.splitFundAnalysisBlocks(raw.slice(0, end))[0].kind, 'text');
});

test('ordered items separated by blank lines keep one continuous numbering', () => {
  const merged = renderToStaticMarkup(element(MarkdownText, { content: '1. 第一点\n\n1. 第二点\n\n1. 第三点' }));
  assert.equal((merged.match(/>1\. /g) ?? []).length, 1);
  assert.ok(merged.includes('2. ') && merged.includes('3. '));

  const split = renderToStaticMarkup(element(MarkdownText, { content: '1. 甲\n\n普通段落\n\n1. 乙' }));
  assert.equal((split.match(/>1\. /g) ?? []).length, 2);
});

test('numbered citations render as superscript and the evidence stays behind one collapsed trigger', () => {
  const citations = {
    version: 1,
    citations: [{
      number: 1, evidence_id: 'ev_aaaaaaaaaaaaaaaa', label: '基金概况', tool: 'get_fund_snapshot',
      fund_codes: ['000001'], as_of: '2026-10-20', excerpt: '近一年净值上涨 12.30%',
    }],
    coverage: ['研究对象：000001'],
    sources: [],
    audit: { matched: 1, unknown: 0, uncited_lines: 0 },
  };
  const html = renderToStaticMarkup(element(MarkdownText, { content: '近一年上涨 12.30% [ev_aaaaaaaaaaaaaaaa]。', citations }));
  assert.ok(html.includes('¹'));
  assert.doesNotMatch(html, /ev_/);
  assert.ok(html.includes('证据 1 条'));

  const syntax = renderToStaticMarkup(element(MarkdownText, { content: '近一年上涨 12.30% [^1]。', citations }));
  assert.ok(syntax.includes('¹'));

  const streaming = renderToStaticMarkup(element(MarkdownText, { content: '近一年上涨 12.30% [ev_aaaaaaaaaaaaaaaa]。' }));
  assert.doesNotMatch(streaming, /ev_/);
});
