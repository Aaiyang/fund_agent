export type FundHoldingsCard = {
  schema_version: 1;
  type: 'holdings';
  fund_code: string;
  source: 'fund_service';
  report_date: string;
  items: { stock_code: string; stock_name: string; weight: number }[];
  warnings: string[];
};

/** Fixed public disclosure card, never personal positions or executable content. */
export function parseFundHoldings(raw: string): FundHoldingsCard | null {
  if (raw.length > 16_384) return null;
  try {
    const card: unknown = JSON.parse(raw);
    const keys = ['schema_version', 'type', 'fund_code', 'source', 'report_date', 'items', 'warnings'];
    if (!card || typeof card !== 'object' || Array.isArray(card)) return null;
    const data = card as Record<string, unknown>;
    if (Object.keys(data).length !== keys.length || !keys.every((key) => Object.prototype.hasOwnProperty.call(data, key))) return null;
    if (data.schema_version !== 1 || data.type !== 'holdings' || data.source !== 'fund_service'
      || typeof data.fund_code !== 'string' || !/^\d{6}$/.test(data.fund_code)
      || typeof data.report_date !== 'string' || !data.report_date.trim() || data.report_date.length > 80) return null;
    if (!Array.isArray(data.warnings) || data.warnings.length > 20
      || !data.warnings.every((item) => typeof item === 'string' && item.trim() && item.length <= 1_000)) return null;
    if (!Array.isArray(data.items) || data.items.length < 1 || data.items.length > 10) return null;
    const seen = new Set<string>();
    for (const item of data.items) {
      if (!item || typeof item !== 'object' || Array.isArray(item) || Object.keys(item).length !== 3
        || typeof item.stock_code !== 'string' || !item.stock_code.trim() || item.stock_code.length > 32
        || typeof item.stock_name !== 'string' || !item.stock_name.trim() || item.stock_name.length > 100
        || typeof item.weight !== 'number' || !Number.isFinite(item.weight) || item.weight < 0 || item.weight > 100
        || seen.has(item.stock_code)) return null;
      seen.add(item.stock_code);
    }
    return data as FundHoldingsCard;
  } catch {
    return null;
  }
}
