/**
 * Query-key factory. Keys are the single source of truth for invalidation:
 * every mutation invalidates the widest prefix it can justify.
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

  watchlist: ['watchlist'] as const,
  watchlistGroups: ['watchlist', 'groups'] as const,

  portfolio: ['portfolio'] as const,
  portfolioSummary: (accountId: number | null) => ['portfolio', 'summary', accountId] as const,
  positions: (accountId: number | null) => ['portfolio', 'positions', accountId] as const,
  position: (accountId: number, code: string) => ['portfolio', 'position', accountId, code] as const,

  accounts: ['accounts'] as const,
  transactionsAll: ['transactions'] as const,
  transactions: (accountId: number | null, code: string | null) =>
    ['transactions', accountId, code] as const,

  imports: ['imports'] as const,
  importDetail: (importId: string) => ['imports', importId] as const,

  me: ['me'] as const,
};
