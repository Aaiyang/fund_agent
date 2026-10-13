/** Only validated identifiers and read-only scenario arguments; never URLs or model series. */
export type ResearchCard =
  | { schema_version: 1; type: 'stock_price'; symbol: string }
  | { schema_version: 1; type: 'sector_quote'; sector_code: string; sector_type: 'industry' | 'concept' }
  | { schema_version: 1; type: 'fund_allocation'; fund_code: string; account_id: number | null; action: 'build' | 'increase' | 'reduce' | 'exit'; amount: number };

function keys(value: Record<string, unknown>, expected: string[]) {
  return Object.keys(value).length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

export function parseResearchCard(raw: string): ResearchCard | null {
  if (raw.length > 2048) return null;
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== 'object' || Array.isArray(value) || value.schema_version !== 1) return null;
    if (value.type === 'stock_price' && keys(value, ['schema_version', 'type', 'symbol'])
      && typeof value.symbol === 'string' && /^(?:(?:sh|sz|bj)\d{6}|hk\d{5}|us[A-Z][A-Z.]{0,10})$/.test(value.symbol)) return value;
    if (value.type === 'sector_quote' && keys(value, ['schema_version', 'type', 'sector_code', 'sector_type'])
      && typeof value.sector_code === 'string' && /^BK\d{4,6}$/.test(value.sector_code)
      && ['industry', 'concept'].includes(value.sector_type)) return value;
    if (value.type === 'fund_allocation' && keys(value, ['schema_version', 'type', 'fund_code', 'account_id', 'action', 'amount'])
      && typeof value.fund_code === 'string' && /^\d{6}$/.test(value.fund_code)
      && (value.account_id === null || (Number.isSafeInteger(value.account_id) && value.account_id > 0))
      && ['build', 'increase', 'reduce', 'exit'].includes(value.action)
      && typeof value.amount === 'number' && Number.isFinite(value.amount) && value.amount > 0 && value.amount <= 1_000_000_000) return value;
    return null;
  } catch { return null; }
}
