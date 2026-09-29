/**
 * Display formatting for money and returns.
 *
 * The API mixes two return units and the names are the only clue: fields
 * ending in `_return` (daily_return) are already percent *points* (2.2 means
 * +2.2%), while `_rate` and `return_1m`-style analytics are fractions
 * (0.022 means +2.2%). Use the matching helper instead of guessing.
 */

const CNY = '¥';

/** `toFixed` keeps the sign of a value too small to display; a derived figure
 * can land on such a remainder, and "-0.00%" reads as a real loss. */
function rounded(value: number, digits: number): string {
  const fixed = value.toFixed(digits);
  return Number(fixed) === 0 ? (0).toFixed(digits) : fixed;
}

export function formatMoney(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  const fixed = Math.abs(value).toFixed(digits);
  const [whole, fraction] = fixed.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  // A derived figure can carry a sub-cent remainder; rounding it to zero must
  // not leave a lone minus sign in front of ¥0.00.
  const sign = value < 0 && Number(fixed) !== 0 ? '-' : '';
  return `${sign}${CNY}${grouped}${fraction ? `.${fraction}` : ''}`;
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
  return `${rounded(value * 100, digits)}%`;
}

export function formatSignedRate(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${rounded(value * 100, digits)}%`;
}

/** For percent points: the fund `daily_return` column. */
export function formatReturnPoints(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${rounded(value, digits)}%`;
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

/** For an editable numeric field: trim the float noise a derived value carries
 * (市值 ÷ 净值 gives 1421.726208527931) without padding out trailing zeros. */
export function toInputNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '';
  return String(Number(value.toFixed(digits)));
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

/** Today on the device, as the YYYY-MM-DD the API expects. */
export function localToday(): string {
  return formatDay(new Date());
}

/** Whether a typed string is a real calendar day, not just a shaped number. */
export function isCalendarDate(value: string): boolean {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!parts) return false;
  const [year, month, day] = parts.slice(1).map(Number);
  // UTC math keeps a device west of Greenwich from rejecting its own dates.
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() + 1 === month && parsed.getUTCDate() === day;
}

/** A YYYY-MM-DD string as a local Date, falling back to today for the pickers. */
export function parseDay(value: string): Date {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!parts) return new Date();
  const [year, month, day] = parts.slice(1).map(Number);
  return new Date(year, month - 1, day);
}

/** A Date picked by the platform, as the YYYY-MM-DD the API expects. */
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

/** Red/green by Chinese market convention: up is red, down is green. */
export function trendColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return '#6B7280';
  return value > 0 ? '#D93026' : '#1E9E62';
}
