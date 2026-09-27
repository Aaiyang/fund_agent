/**
 * Display formatting for money and returns.
 *
 * The API mixes two return units and the names are the only clue: fields
 * ending in `_return` (daily_return) are already percent *points* (2.2 means
 * +2.2%), while `_rate` and `return_1m`-style analytics are fractions
 * (0.022 means +2.2%). Use the matching helper instead of guessing.
 */

const CNY = '¥';

export function formatMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const fixed = Math.abs(value).toFixed(digits);
  const [whole, fraction] = fixed.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${value < 0 ? '-' : ''}${CNY}${grouped}${fraction ? `.${fraction}` : ''}`;
}

/** For signed amounts (当日收益/持有收益): always show the sign when non-zero. */
export function formatSignedMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  if (value === 0) return formatMoney(0, digits);
  return `${value > 0 ? '+' : ''}${formatMoney(value, digits)}`;
}

/** For fractions: profit_loss_rate, return_1m, position_ratio. */
export function formatRate(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatSignedRate(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`;
}

/** For percent points: the fund `daily_return` column. */
export function formatReturnPoints(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/** For a magnitude already in percent points, without a sign: 占净值比例. */
export function formatPoints(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value.toFixed(digits)}%`;
}

export function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return value.toFixed(digits).replace(/\.?0+$/, '') || '0';
}

/** Quoted price: grouped thousands and a fixed fraction, no currency sign. */
export function formatPrice(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const [whole, fraction] = Math.abs(value).toFixed(digits).split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${value < 0 ? '-' : ''}${grouped}.${fraction ?? ''}`;
}

/** Raw counts (成交量/成交额) in 万/亿, the way a quote screen groups them. */
export function formatCompact(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const absolute = Math.abs(value);
  if (absolute >= 1e8) return `${(value / 1e8).toFixed(digits)}亿`;
  if (absolute >= 1e4) return `${(value / 1e4).toFixed(digits)}万`;
  return String(Math.round(value));
}

/** For magnitudes the source already counts in 亿 (总市值/流通市值). */
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

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '--';
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return formatDate(value);
  const pad = (input: number) => String(input).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Red/green by Chinese market convention: up is red, down is green. */
export function trendColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return '#6B7280';
  return value > 0 ? '#D93026' : '#1E9E62';
}
