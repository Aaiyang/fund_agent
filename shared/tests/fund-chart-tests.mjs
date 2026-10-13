import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { compileFunction } from 'node:vm';

export const fixture = JSON.parse(readFileSync(new URL('./fund-chart.fixture.json', import.meta.url), 'utf8'));
export const fence = (chart = fixture) => '```fund-chart\n' + JSON.stringify(chart) + '\n```';

export function loadChartContract(ts) {
  const holdingsSource = readFileSync(new URL('../fund-holdings.ts', import.meta.url), 'utf8');
  const holdingsCompiled = ts.transpileModule(holdingsSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const holdings = {};
  compileFunction(holdingsCompiled, ['exports'])(holdings);
  const research = {};
  const researchSource = readFileSync(new URL('../research-card.ts', import.meta.url), 'utf8');
  compileFunction(ts.transpileModule(researchSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText, ['exports'])(research);
  const source = readFileSync(new URL('../fund-chart.ts', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  compileFunction(compiled, ['exports', 'require'])(exports, (name) => {
    if (name === './research-card') return research;
    assert.equal(name, './fund-holdings');
    return holdings;
  });
  return { ...exports, ...holdings, ...research };
}

export function registerFundChartTests(ts) {
  const { parseFundChart, splitFundChartBlocks, fundChartGeometry, nearestChartPoint, CHART_SIZE } = loadChartContract(ts);

  test('valid backend schema becomes a chart while text before/after and multiple funds are preserved', () => {
    assert.deepEqual(parseFundChart(JSON.stringify(fixture)), fixture);
    const input = '持仓分析\n' + fence() + '\n后续建议\n' + fence({ ...fixture, fund_code: '000002' }) + '\n尾部';
    const blocks = splitFundChartBlocks(input);
    assert.deepEqual(blocks.map((block) => block.kind), ['text', 'chart', 'text', 'chart', 'text']);
    assert.equal(blocks[0].content, '持仓分析\n');
    assert.equal(blocks[2].content, '后续建议\n');
    assert.equal(blocks[4].content, '尾部');
    assert.equal(blocks[3].chart.fund_code, '000002');
  });

  test('every partial streamed block stays text; closing fence and restored history use the same renderer', () => {
    const input = fence();
    for (let end = 1; end < input.length; end++) {
      const blocks = splitFundChartBlocks(input.slice(0, end));
      assert.equal(blocks.length, 1);
      assert.equal(blocks[0].kind, 'text');
      assert.equal(blocks[0].content, input.slice(0, end));
    }
    assert.equal(splitFundChartBlocks(input)[0].kind, 'chart');
    assert.deepEqual(splitFundChartBlocks(input), splitFundChartBlocks(JSON.parse(JSON.stringify(input))));
  });

  test('reject unknown versions, extra fields, invalid values/dates and misleading endpoint windows', () => {
    const modifications = [
      (c) => { c.schema_version = 2; }, (c) => { c.metric = 'total_return'; },
      (c) => { c.source = 'https://example.com'; }, (c) => { c.script = 'alert(1)'; },
      (c) => { c.points[0].url = 'https://example.com'; }, (c) => { c.fund_code = 1; },
      (c) => { c.points[0].unit_nav = 0; }, (c) => { c.points[0].unit_nav = -1; },
      (c) => { c.points[0].unit_nav = '1.25'; }, (c) => { c.points[0].unit_nav = null; },
      (c) => { c.points[0].unit_nav = Infinity; }, (c) => { c.points[0].date = '2025-02-30'; },
      (c) => { c.requested_to = '2026-02-29'; }, (c) => { c.observed_from = '2025-10-12'; },
      (c) => { c.as_of = '2026-10-10'; }, (c) => { c.requested_to = '2026-10-08'; },
      (c) => { c.points.reverse(); }, (c) => { c.points[1].date = c.points[0].date; },
      (c) => { c.points = c.points.slice(0, 1); }, (c) => { c.points = Array(61).fill(c.points[0]); },
      (c) => { c.warnings = [42]; }, (c) => { c.warnings = Array(21).fill('warning'); },
      (c) => { c.title = 'x'.repeat(201); }, (c) => { c.warnings = ['x'.repeat(1001)]; },
      (c) => { delete c.points; }, (c) => { c.points = {}; },
    ];
    for (const modify of modifications) {
      const chart = structuredClone(fixture);
      modify(chart);
      const raw = JSON.stringify(chart);
      assert.equal(parseFundChart(raw), null, modify.toString());
      const invalid = '```fund-chart\n' + raw + '\n```';
      assert.deepEqual(splitFundChartBlocks(invalid), [{ kind: 'text', content: invalid, offset: 0 }]);
    }
    assert.equal(parseFundChart('x'.repeat(32769)), null);
    assert.equal(parseFundChart('null'), null);
    assert.equal(parseFundChart('{'), null);
    assert.equal(parseFundChart(JSON.stringify(fixture).replace('1.25', '1e999')), null);
  });

  test('fences respect Markdown nesting, indentation, CRLF and arbitrary chunk boundaries', () => {
    const nested = '````markdown\n' + fence() + '\n````';
    const tilde = '~~~markdown\n' + fence() + '\n~~~';
    for (const content of [nested, tilde, '    ' + fence(), '```json\n' + JSON.stringify(fixture) + '\n```']) {
      assert.deepEqual(splitFundChartBlocks(content), [{ kind: 'text', content, offset: 0 }]);
    }
    assert.equal(splitFundChartBlocks(fence().replaceAll('\n', '\r\n'))[0].kind, 'chart');
    const input = 'before\n' + fence() + '\nafter';
    let streamed = '';
    for (let at = 0; at < input.length; at += 17) streamed += input.slice(at, at + 17);
    assert.deepEqual(splitFundChartBlocks(streamed), splitFundChartBlocks(input));
  });

  test('time axis preserves gaps, unit NAV coordinates match tick labels and nearest point inspection', () => {
    const geometry = fundChartGeometry(fixture);
    assert.equal(geometry.points[0].x, CHART_SIZE.left);
    assert.equal(geometry.points.at(-1).x, CHART_SIZE.right);
    assert.ok(geometry.points[1].x - CHART_SIZE.left < 10);
    assert.ok(geometry.points[2].x > (CHART_SIZE.left + CHART_SIZE.right) / 2);
    const minTick = geometry.ticks[0];
    assert.equal(minTick.value, 1.2);
    assert.equal(minTick.y, geometry.points[1].y);
    assert.equal(nearestChartPoint(geometry.points, -100), 0);
    assert.equal(nearestChartPoint(geometry.points, 1000), 3);
    assert.equal(nearestChartPoint(geometry.points, geometry.points[2].x), 2);
  });

  test('constant and extreme finite positive values never create invalid SVG geometry', () => {
    for (const values of [[1, 1, 1, 1], [Number.MIN_VALUE, Number.MAX_VALUE, 1, Number.MAX_VALUE], [1e-10, 2e-10, 3e-10, 4e-10]]) {
      const chart = structuredClone(fixture);
      chart.points.forEach((point, i) => { point.unit_nav = values[i]; });
      assert.ok(parseFundChart(JSON.stringify(chart)));
      const geometry = fundChartGeometry(chart);
      assert.ok(!/NaN|Infinity/.test(geometry.path));
      for (const point of geometry.points) {
        assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
        assert.ok(point.y >= CHART_SIZE.top && point.y <= CHART_SIZE.bottom);
      }
      assert.ok(geometry.ticks.every((tick) => Number.isFinite(tick.value) && Number.isFinite(tick.y)));
    }
  });
}
