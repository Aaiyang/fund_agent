/** Fund references (v2) and legacy public NAV blocks (v1). Never execute content. */
import { parseFundHoldings, type FundHoldingsCard } from './fund-holdings';
import { parseResearchCard, type ResearchCard } from './research-card';

export type FundChartPoint = { date: string; unit_nav: number };
export type FundNavChart = {
  schema_version: 1;
  type: 'line';
  metric: 'unit_nav';
  range_key: '1y';
  sampling: 'weekly';
  fund_code: string;
  title: string;
  source: 'fund_service';
  requested_from: string;
  requested_to: string;
  observed_from: string;
  observed_to: string;
  as_of: string;
  points: FundChartPoint[];
  warnings: string[];
};

export type FundChartReference = {
  schema_version: 2;
  type: 'fund_performance';
  fund_code: string;
};
export type FundChart = FundNavChart | FundChartReference;

export type FundChartBlock =
  | { kind: 'text'; content: string; offset: number }
  | { kind: 'chart'; chart: FundChart; offset: number };

export type FundAnalysisBlock = FundChartBlock | { kind: 'holdings'; holdings: FundHoldingsCard; offset: number }
  | { kind: 'research'; card: ResearchCard; offset: number };

const MAX_JSON_LENGTH = 32_768;
const CHART_KEYS = [
  'schema_version', 'type', 'metric', 'range_key', 'sampling', 'fund_code',
  'title', 'source', 'requested_from', 'requested_to', 'observed_from',
  'observed_to', 'as_of', 'points', 'warnings',
];

function objectWithKeys(value: unknown, keys: string[]): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
}

function boundedText(value: unknown, max: number): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= max;
}

/** Reject invalid/unknown versions, extra fields and out-of-range or invented calendar dates. */
export function parseFundChart(raw: string): FundChart | null {
  if (raw.length > MAX_JSON_LENGTH) return null;
  try {
    const data: unknown = JSON.parse(raw);
    if (objectWithKeys(data, ['schema_version', 'type', 'fund_code'])
      && data.schema_version === 2 && data.type === 'fund_performance'
      && typeof data.fund_code === 'string' && /^\d{6}$/.test(data.fund_code)) {
      return data as FundChartReference;
    }
    if (!objectWithKeys(data, CHART_KEYS)) return null;
    if (data.schema_version !== 1 || data.type !== 'line' || data.metric !== 'unit_nav'
      || data.range_key !== '1y' || data.sampling !== 'weekly' || data.source !== 'fund_service') return null;
    if (typeof data.fund_code !== 'string' || !/^\d{6}$/.test(data.fund_code)
      || !boundedText(data.title, 200)) return null;
    if (!validDate(data.requested_from) || !validDate(data.requested_to)
      || !validDate(data.observed_from) || !validDate(data.observed_to) || !validDate(data.as_of)) return null;
    if (!(data.requested_from <= data.observed_from && data.observed_from < data.observed_to
      && data.observed_to <= data.requested_to && data.as_of === data.observed_to)) return null;
    if (!Array.isArray(data.warnings) || data.warnings.length > 20
      || !data.warnings.every((warning) => boundedText(warning, 1_000))) return null;
    if (!Array.isArray(data.points) || data.points.length < 2 || data.points.length > 60) return null;
    let previous = '';
    for (const point of data.points) {
      if (!objectWithKeys(point, ['date', 'unit_nav']) || !validDate(point.date)
        || point.date <= previous || point.date < data.observed_from || point.date > data.observed_to
        || typeof point.unit_nav !== 'number' || !Number.isFinite(point.unit_nav) || point.unit_nav <= 0) return null;
      previous = point.date;
    }
    if (data.points[0].date !== data.observed_from
      || data.points[data.points.length - 1].date !== data.observed_to) return null;
    return data as FundNavChart;
  } catch {
    return null;
  }
}

/** Only recognize complete top-level fences. Other code fences and unfinished streams stay intact. */
function splitBlocks(content: string, allowHoldings: boolean): FundAnalysisBlock[] {
  const result: FundAnalysisBlock[] = [];
  const lines = /[^\n]*(?:\n|$)/g;
  let fence: { marker: string; length: number; language: string; start: number; body: number } | null = null;
  let cursor = 0;
  let line: RegExpExecArray | null;
  while ((line = lines.exec(content)) && line[0]) {
    const match = /^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?\n?$/.exec(line[0]);
    if (!match) continue;
    const marker = match[1][0];
    const info = match[2].trim();
    if (!fence) {
      fence = {
        marker, length: match[1].length, language: marker === '`' ? info : '',
        start: line.index, body: lines.lastIndex,
      };
      continue;
    }
    if (marker !== fence.marker || match[1].length < fence.length || info) continue;
    if (fence.language === 'fund-chart' || (allowHoldings && ['fund-holdings', 'research-chart'].includes(fence.language))) {
      const raw = content.slice(fence.body, line.index);
      const chart = fence.language === 'fund-chart' ? parseFundChart(raw) : null;
      const holdings = fence.language === 'fund-holdings' ? parseFundHoldings(raw) : null;
      const card = fence.language === 'research-chart' ? parseResearchCard(raw) : null;
      if (chart || holdings || card) {
        if (cursor < fence.start) result.push({ kind: 'text', content: content.slice(cursor, fence.start), offset: cursor });
        if (chart) result.push({ kind: 'chart', chart, offset: fence.start });
        if (holdings) result.push({ kind: 'holdings', holdings, offset: fence.start });
        if (card) result.push({ kind: 'research', card, offset: fence.start });
        cursor = lines.lastIndex;
      }
    }
    fence = null;
  }
  if (cursor < content.length) result.push({ kind: 'text', content: content.slice(cursor), offset: cursor });
  return result;
}

export function splitFundChartBlocks(content: string): FundChartBlock[] {
  return splitBlocks(content, false) as FundChartBlock[];
}

export function splitFundAnalysisBlocks(content: string): FundAnalysisBlock[] {
  return splitBlocks(content, true);
}

/** Calendar-month display filtering only; this does not calculate performance or invent boundary points. */
export function fundChartRangePoints(chart: FundNavChart, months: 3 | 6 | 12): FundChartPoint[] {
  if (months === 12) return chart.points;
  const end = new Date(`${chart.requested_to}T00:00:00Z`);
  const target = end.getUTCMonth() - months;
  const cutoff = new Date(Date.UTC(end.getUTCFullYear(), target, 1));
  const lastDay = new Date(Date.UTC(end.getUTCFullYear(), target + 1, 0)).getUTCDate();
  cutoff.setUTCDate(Math.min(end.getUTCDate(), lastDay));
  const lower = cutoff.toISOString().slice(0, 10);
  return chart.points.filter((point) => point.date >= lower);
}

export const CHART_SIZE = { width: 640, height: 250, left: 72, right: 620, top: 16, bottom: 216 };

/** Normalize before arithmetic to keep geometry finite even for extreme finite NAV values. */
export function fundChartGeometry(chart: FundNavChart) {
  const { left, right, top, bottom } = CHART_SIZE;
  const maximum = Math.max(...chart.points.map((point) => point.unit_nav));
  const minimum = Math.min(...chart.points.map((point) => point.unit_nav)) / maximum;
  const span = 1 - minimum || 0.02;
  const padding = span * 0.08;
  const low = Math.max(0, minimum - padding);
  const high = 1 + padding;
  const start = Date.parse(`${chart.observed_from}T00:00:00Z`);
  const end = Date.parse(`${chart.observed_to}T00:00:00Z`);
  const points = chart.points.map((point) => ({
    ...point,
    x: left + (Date.parse(`${point.date}T00:00:00Z`) - start) / (end - start) * (right - left),
    y: bottom - (point.unit_nav / maximum - low) / (high - low) * (bottom - top),
  }));
  const ticks = (minimum === 1 ? [1] : [minimum, (minimum + 1) / 2, 1]).map((value) => ({
    y: bottom - (value - low) / (high - low) * (bottom - top),
    value: value * maximum,
  }));
  return { points, ticks, path: points.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ') };
}

export function nearestChartPoint(points: { x: number }[], x: number): number {
  return points.reduce((best, point, index) => Math.abs(point.x - x) < Math.abs(points[best].x - x) ? index : best, 0);
}

export function formatChartNav(value: number): string {
  if (value < 0.0001 || value >= 1_000_000) return value.toExponential(3);
  return value.toFixed(4);
}

export const FUND_CHART_NOTE = '周采样单位净值，未做分红复权，不代表含分红总回报；连线仅连接已公布数据点。';
