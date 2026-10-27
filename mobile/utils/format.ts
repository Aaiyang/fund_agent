/**
 * 金额与收益的显示格式化。
 *
 * API 里混着两种收益单位，字段名是唯一的线索：以 `_return` 结尾的字段
 * （daily_return）已经是百分“点”（2.2 即 +2.2%），而 `_rate` 与
 * `return_1m` 这类分析值是比例（0.022 即 +2.2%）。按单位挑对 helper，别猜。
 */

import { theme } from '@/constants/theme';

const CNY = '¥';

/** `toFixed` 会把小到显示不出来的值连符号一起留着；派生数字正好可能
 * 落在这种残值上，而 “-0.00%” 会被读成一笔真实亏损。 */
function rounded(value: number, digits: number): string {
  const fixed = value.toFixed(digits);
  return Number(fixed) === 0 ? (0).toFixed(digits) : fixed;
}

export function formatMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const fixed = Math.abs(value).toFixed(digits);
  const [whole, fraction] = fixed.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  // 派生数字可能带着不足一分的残值；四舍五入成 0 之后，
  // 不能在 ¥0.00 前面留一个孤零零的负号。
  const sign = value < 0 && Number(fixed) !== 0 ? '-' : '';
  return `${sign}${CNY}${grouped}${fraction ? `.${fraction}` : ''}`;
}

/** 带符号金额（当日收益/持有收益）：非零就必须带符号。 */
export function formatSignedMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (value === 0) return formatMoney(0, digits);
  return `${value > 0 ? '+' : ''}${formatMoney(value, digits)}`;
}

/** 比例类字段：profit_loss_rate、return_1m、position_ratio。 */
export function formatRate(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${rounded(value * 100, digits)}%`;
}

export function formatSignedRate(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${rounded(value * 100, digits)}%`;
}

/** 百分点类字段：基金的 `daily_return` 列。 */
export function formatReturnPoints(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${rounded(value, digits)}%`;
}

/** 已经是百分点、但不加符号的量：占净值比例。 */
export function formatPoints(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return value.toFixed(digits).replace(/\.?0+$/, '') || '0';
}

/** 给可编辑的数字输入框用：削掉派生值带的浮点噪声
 * （市值 ÷ 净值会算出 1421.726208527931），也不补尾随的零。 */
export function toInputNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '';
  return String(Number(value.toFixed(digits)));
}

/** 行情价：千分位分组、固定小数位，不带货币符号。 */
export function formatPrice(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const [whole, fraction] = Math.abs(value).toFixed(digits).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${value < 0 ? '-' : ''}${grouped}.${fraction ?? ''}`;
}

/** 原始计数（成交量/成交额）按 万/亿 分组，行情界面惯用的切法。 */
export function formatCompact(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const absolute = Math.abs(value);
  if (absolute >= 1e8) return `${(value / 1e8).toFixed(digits)}亿`;
  if (absolute >= 1e4) return `${(value / 1e4).toFixed(digits)}万`;
  return String(Math.round(value));
}

/** 源头单位已经是 亿 的量（总市值/流通市值）。 */
export function formatYi(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(digits)}万亿`;
  return `${value.toFixed(digits)}亿`;
}

const CURRENCY_SIGNS: Record<string, string> = { CNY: '¥', HKD: 'HK$', USD: 'US$' };

export function currencySign(currency: string | null | undefined): string {
  return (currency && CURRENCY_SIGNS[currency]) || '';
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '--';
  return value.slice(0, 10);
}

/** 设备上的今天，按 API 要求的 YYYY-MM-DD。 */
export function localToday(): string {
  return formatDay(new Date());
}

/** 用户输入的串是不是真实存在的日历日，而不只是形状对的数字。 */
export function isCalendarDate(value: string): boolean {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!parts) return false;
  const [year, month, day] = parts.slice(1).map(Number);
  // 用 UTC 运算，免得位于格林威治以西时区的设备把自家合法的日期判死。
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() + 1 === month && parsed.getUTCDate() === day;
}

/** 把 YYYY-MM-DD 串转成本地 Date；供选择器使用，坏值兜底成今天。 */
export function parseDay(value: string): Date {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!parts) return new Date();
  const [year, month, day] = parts.slice(1).map(Number);
  return new Date(year, month - 1, day);
}

/** 平台选择器选出的 Date，转回 API 要求的 YYYY-MM-DD。 */
export function formatDay(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return formatDate(value);
  const pad = (input: number) => String(input).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/**
 * 会话列表用的紧凑时间：今天只给时:分，昨天标「昨天」，今年给月日，跨年才补年份。
 *
 * 整串日期放在一列里看不出先后，按"离今天多远"缩写才分得开。
 */
export function formatSessionTime(value: string | null | undefined): string {
  if (!value) return '--';
  // 库里存的是 naive UTC，补 Z 再按本地时区读回来（与 formatDateTime 同一口径）。
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return '--';
  const pad = (input: number) => String(input).padStart(2, '0');
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const now = new Date();
  const startOfDay = (input: Date) => new Date(input.getFullYear(), input.getMonth(), input.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (days <= 0) return `今天 ${clock}`;
  if (days === 1) return `昨天 ${clock}`;
  if (date.getFullYear() === now.getFullYear()) return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${clock}`;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 按中国市场的红绿惯例上色：涨是红，跌是绿。 */
export function trendColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return theme.flat;
  return value > 0 ? theme.up : theme.down;
}
