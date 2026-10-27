import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { compileFunction } from 'node:vm';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import { loadChartContract } from '../../shared/tests/fund-chart-tests.mjs';

const require = createRequire(import.meta.url);
const contract = loadChartContract(ts);
const element = require('react').createElement;
const stock = { schema_version: 1, type: 'stock_price', symbol: 'sh600519' };
const sector = { schema_version: 1, type: 'sector_quote', sector_code: 'BK1234', sector_type: 'industry' };
const allocation = { schema_version: 1, type: 'fund_allocation', fund_code: '000001', account_id: null, action: 'increase', amount: 200 };
const fence = (value) => '```research-chart\n' + JSON.stringify(value) + '\n```';

function load(path, mocks = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const exports = {};
  compileFunction(code, ['exports', 'require'])(exports, (name) => mocks[name] ?? require(name));
  return exports;
}

test('research references reject identity, URLs, model series and invalid scenario arguments', () => {
  for (const card of [stock, sector, allocation]) assert.deepEqual(contract.parseResearchCard(JSON.stringify(card)), card);
  for (const card of [
    { ...stock, symbol: '600519' }, { ...stock, url: 'https://example.com' }, { ...stock, bars: [] },
    { ...sector, sector_code: 'fake' }, { ...sector, sector_type: 'all' },
    { ...allocation, amount: 0 }, { ...allocation, amount: '200' }, { ...allocation, amount: 1e10 },
    { ...allocation, account_id: -1 }, { ...allocation, account_id: 1.5 }, { ...allocation, user_id: 43 },
  ]) assert.equal(contract.parseResearchCard(JSON.stringify(card)), null);
  const raw = fence(stock);
  for (let end = 1; end < raw.length; end++) assert.equal(contract.splitFundAnalysisBlocks(raw.slice(0, end))[0].kind, 'text');
  assert.equal(contract.splitFundAnalysisBlocks(raw)[0].kind, 'research');
  assert.equal(contract.splitFundAnalysisBlocks('````text\n' + raw + '\n````')[0].kind, 'text');
});

test('private scenarios are read-only and query keys include current user and every parameter', async () => {
  let userId = 42;
  const queries = [];
  const calls = [];
  const { useAllocationResearchCard, useSectorResearchCard } = load('../hooks/useResearchCards.ts', {
    '@tanstack/react-query': { useQuery: (query) => { queries.push(query); return query; } },
    '@/api/client': { api: { get: async (path, params) => { calls.push([path, params]); return {}; } } },
    '@/api/queries': { queryKeys: { sectors: ['sectors'], portfolio: ['portfolio'] } },
    '@/stores/auth': { useAuthStore: (select) => select({ user: userId ? { id: userId } : null }) },
  });
  const first = useAllocationResearchCard(allocation);
  await first.queryFn();
  userId = 43;
  const next = useAllocationResearchCard(allocation);
  assert.notDeepEqual(first.queryKey, next.queryKey);
  assert.notDeepEqual(next.queryKey, useAllocationResearchCard({ ...allocation, account_id: 9, amount: 300 }).queryKey);
  await useSectorResearchCard(sector).queryFn();
  assert.deepEqual(calls, [
    ['/portfolio/allocation-preview', { fund_code: '000001', account_id: null, action: 'increase', amount: 200 }],
    ['/sectors/market', { keyword: 'BK1234', sector_type: 'industry', limit: 1 }],
  ]);
  userId = null;
  assert.equal(useAllocationResearchCard(allocation).enabled, false);
});

test('cards reuse MarketChart and display only backend prices, quotes and calculated weights', () => {
  const native = { View: ({ children }) => element('div', {}, children), Text: ({ children }) => element('span', {}, children), ScrollView: ({ children }) => element('div', {}, children) };
  const ui = { Card: native.View, SectionTitle: ({ title }) => element('h3', {}, title), Chip: ({ label }) => element('button', {}, label), Stat: ({ label, value }) => element('span', {}, `${label} ${value}`) };
  const calls = [];
  const { theme } = load('../constants/theme.ts', { 'react-native': { Platform: { OS: 'web', select: (options) => options.web ?? options.default } } });
  const { ResearchDataCard } = load('../components/ResearchDataCard.tsx', {
    'react-native': native, '@/components/ui': ui, '@/constants/theme': { theme },
    '@/utils/format': load('../utils/format.ts', { '@/constants/theme': { theme } }),
    '@/components/states': { Async: ({ query, children }) => children(query.data), EmptyState: ({ title }) => element('span', {}, title), ErrorState: () => null, describeError: String },
    '@/components/MarketChart': { MarketChart: ({ bars }) => { calls.push(['chart', bars]); return element('svg', {}, element('title', {}, '原有MarketChart')); } },
    '@/hooks/useMarket': {
      useMarketQuote: (symbol) => { calls.push(['quote', symbol]); return { data: { name: '后端股票', price: 123.45, change_pct: 2.3, currency: 'CNY', quote_time: '2026-10-12 15:00:00' } }; },
      useMarketHistory: (symbol, period, range) => { calls.push(['history', symbol, period, range]); return { data: { bars: [{ close: 1 }, { close: 2 }] } }; },
    },
    '@/hooks/useResearchCards': {
      useSectorResearchCard: () => ({ data: { sectors: [{ ...sector, name: '后端板块', price: 8250.66, change_pct: -2.37, quote_time: null, stale: true }], warnings: ['公开报价可能延迟'] } }),
      useAllocationResearchCard: () => ({ data: { captured_at: '2026-10-12T12:00:00', warnings: [], scenario: { available: true, before_weight_ratio: 0.4, after_weight_ratio: 0.5, before_target_value: 400, after_target_value: 600, before_fund_assets: 1000, after_fund_assets: 1200, assumption: '新增资金进入基金资产桶' } } }),
    },
  });
  assert.match(renderToStaticMarkup(element(ResearchDataCard, { card: stock })), /原有MarketChart/);
  assert.deepEqual(calls.slice(0, 2), [['quote', 'sh600519'], ['history', 'sh600519', 'day', '1y']]);
  const sectorHtml = renderToStaticMarkup(element(ResearchDataCard, { card: sector }));
  assert.match(sectorHtml, /后端板块/);
  assert.match(sectorHtml, /历史走势图暂未接入/);
  assert.doesNotMatch(sectorHtml, /<svg/);
  const html = renderToStaticMarkup(element(ResearchDataCard, { card: allocation }));
  assert.match(html, /40.00%/);
  assert.match(html, /50.00%/);
  assert.match(html, /不执行交易/);
});
