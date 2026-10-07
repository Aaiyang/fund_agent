/**
 * query key 工厂。key 是失效判定的唯一真源：每个 mutation 都去失效
 * 它能站得住脚的最宽前缀。
 */

export const queryKeys = {
  funds: ['funds'] as const,
  fundSearch: (keyword: string) => ['funds', 'search', keyword] as const,
  fundDetail: (code: string) => ['funds', 'detail', code] as const,
  fundNav: (code: string, range: string) => ['funds', 'nav', code, range] as const,
  fundNavPages: (code: string, pageSize: number) => ['funds', 'nav-pages', code, pageSize] as const,
  fundHoldings: (code: string) => ['funds', 'holdings', code] as const,

  indexes: ['indexes'] as const,
  indexQuotes: ['indexes', 'quotes'] as const,
  indexHistory: (code: string, range: string) => ['indexes', code, range] as const,

  markets: ['markets'] as const,
  marketQuote: (symbol: string) => ['markets', 'quote', symbol] as const,
  marketHistory: (symbol: string, period: string, range: string) =>
    ['markets', 'history', symbol, period, range] as const,
  marketIntraday: (symbol: string, days: number) => ['markets', 'intraday', symbol, days] as const,
  marketCompany: (symbol: string) => ['markets', 'company', symbol] as const,

  watchlist: ['watchlist'] as const,
  watchlistGroups: ['watchlist', 'groups'] as const,

  portfolio: ['portfolio'] as const,
  portfolioSummary: (accountId: number | null) => ['portfolio', 'summary', accountId] as const,
  positions: (accountId: number | null) => ['portfolio', 'positions', accountId] as const,
  position: (accountId: number, code: string) => ['portfolio', 'position', accountId, code] as const,
  tradePreview: (
    accountId: number,
    code: string,
    operation: string,
    day: string,
    afterCutoff: boolean,
    amount: string,
    shares: string,
    target: string,
  ) => ['portfolio', 'trade-preview', accountId, code, operation, day, afterCutoff, amount, shares, target] as const,

  accounts: ['accounts'] as const,
  transactionsAll: ['transactions'] as const,
  transactions: (accountId: number | null, code: string | null) =>
    ['transactions', accountId, code] as const,

  imports: ['imports'] as const,
  importDetail: (importId: string) => ['imports', importId] as const,

  autoInvest: ['auto-invest'] as const,

  me: ['me'] as const,
};
