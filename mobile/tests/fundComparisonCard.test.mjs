import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { compileFunction } from 'node:vm';
import test from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const element = require('react').createElement;

function load(path, mocks = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  const exports = {};
  compileFunction(code, ['exports', 'require'])(exports, (name) => mocks[name] ?? require(name));
  return exports;
}

const native = {
  View: ({ children }) => element('div', {}, children),
  Text: ({ children }) => element('span', {}, children),
  Pressable: ({ children }) => element('button', {}, children),
};
const svg = { default: 'svg', Circle: 'circle', Line: 'line', Polyline: 'polyline' };
const platform = { Platform: { OS: 'web', select: (options) => options.web ?? options.default } };
const { theme } = load('../constants/theme.ts', { 'react-native': platform });
const format = load('../utils/format.ts', { '@/constants/theme': { theme } });
const ui = {
  Card: ({ children }) => element('div', {}, children),
  SectionTitle: ({ title }) => element('h3', {}, title),
  Badge: ({ label }) => element('span', {}, label),
  Chip: ({ label }) => element('button', {}, label),
};
const states = {
  Async: ({ query, children, empty }) => {
    const placeholder = empty?.(query.data);
    return placeholder ?? children(query.data);
  },
  EmptyState: ({ title }) => element('span', {}, title),
};
const comparison = load('../components/ComparisonChart.tsx', {
  'react-native': native, 'react-native-svg': svg, '@/constants/theme': { theme }, '@/utils/format': format,
});
const chartQuery = {
  data: {
    common_from: '2025-10-13',
    common_to: '2026-10-13',
    aligned_count: 2,
    funds: [
      { fund_code: '000001', fund_name: '基金A', points: [
        { nav_date: '2025-10-13', change_ratio: 0 }, { nav_date: '2026-10-13', change_ratio: 0.123 },
      ], period_returns: { return_1m: 0.0123, return_3m: -0.0345, return_6m: 0.0567, return_1y: 0.123 } },
      { fund_code: '000002', fund_name: '基金B', points: [
        { nav_date: '2025-10-13', change_ratio: 0 }, { nav_date: '2026-10-13', change_ratio: -0.03 },
      ], period_returns: { return_1m: -0.02, return_3m: 0.01, return_6m: null, return_1y: -0.03 } },
    ],
  },
  isPending: false,
  isError: false,
  refetch: () => Promise.resolve(),
};
const { FundComparisonCard } = load('../components/FundComparisonCard.tsx', {
  'react-native': native,
  'react-native-svg': svg,
  '@/constants/theme': { theme },
  '@/utils/format': format,
  '@/components/ui': ui,
  '@/components/states': states,
  '@/components/ComparisonChart': {
    ComparisonChart: comparison.ComparisonChart,
    COMPARISON_COLORS: comparison.COMPARISON_COLORS,
  },
  '@/hooks/useFunds': { useFundComparisonNav: () => chartQuery },
});

test('comparison card renders the shared window, both funds and the report-time metric table', () => {
  const html = renderToStaticMarkup(element(FundComparisonCard, {
    chart: {
      version: 1,
      fund_codes: ['000001', '000002'],
      common_from: '2025-10-13',
      common_to: '2026-10-13',
      aligned_count: 240,
      funds: [
        {
          fund_code: '000001', window_change_ratio: 0.123, observed_max_drawdown_ratio: -0.084,
          annualized_nav_volatility_ratio: 0.182, aligned_count: 240, stale: false,
        },
        {
          fund_code: '000002', window_change_ratio: -0.03, observed_max_drawdown_ratio: -0.15,
          annualized_nav_volatility_ratio: 0.22, aligned_count: 240, stale: true,
        },
      ],
    },
  }));

  assert.match(html, /同期收益对比/);
  assert.match(html, /共同窗口 2025-10-13 至 2026-10-13/);
  assert.match(html, /基金A/);
  assert.match(html, /基金B/);
  assert.match(html, /\+12\.30%/);
  assert.match(html, /-8\.40%/);
  assert.match(html, /18\.20%/);
  assert.match(html, /240 天/);
  assert.match(html, /数据可能不是最新/);
  assert.match(html, /累计收益/);
  assert.match(html, /回撤/);
  assert.match(html, /阶段收益（共同窗口内）/);
  assert.match(html, /\+1\.23%/);
  assert.match(html, /-3\.45%/);
  assert.match(html, /--/);
});

test('comparison chart drawdown mode reports the drop from the running peak', () => {
  const points = [
    { nav_date: '2026-01-01', change_ratio: 0 },
    { nav_date: '2026-02-01', change_ratio: 0.2 },
    { nav_date: '2026-03-01', change_ratio: -0.1 },
  ];
  const funds = [
    { fund_code: '000001', fund_name: '基金A', points },
    { fund_code: '000002', fund_name: '基金B', points },
  ];
  const html = renderToStaticMarkup(element(comparison.ComparisonChart, { funds, mode: 'drawdown' }));
  assert.match(html, /-25\.00%/);
});
