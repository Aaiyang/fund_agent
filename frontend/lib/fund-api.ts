import { API_BASE_URL, request } from '@/lib/api';

export type AccountItem = {
  id: number;
  name: string;
  source_app?: string | null;
  account_type: string;
  import_mode: string;
  last_imported_at?: string | null;
  created_at?: string | null;
};

export type PortfolioSummary = {
  total_market_value: number;
  total_cost: number;
  total_profit_loss: number;
  total_profit_loss_rate: number | null;
  daily_profit_loss: number;
  fund_count: number;
  data_updated_at: string | null;
};

export type PositionItem = {
  id?: number | null;
  account_id: number;
  fund_code: string;
  fund_name?: string | null;
  shares?: number | null;
  cost_amount?: number | null;
  average_cost_nav?: number | null;
  market_value?: number | null;
  profit_loss?: number | null;
  profit_loss_rate?: number | null;
  shares_derived?: boolean;
  cost_derived?: boolean;
  average_cost_nav_derived?: boolean;
  profit_derived?: boolean;
  daily_profit_loss?: number | null;
  daily_return?: number | null;
  unit_nav?: number | null;
  position_ratio?: number | null;
  nav_date?: string | null;
  purchase_date?: string | null;
  holding_days?: number | null;
  trade_count?: number;
  created_at?: string | null;
  version?: number;
  updated_at?: string | null;
};

export type WatchlistItem = {
  fund_code: string;
  fund_name: string;
  fund_type?: string | null;
  latest_nav?: number | null;
  nav_date?: string | null;
  daily_return?: number | null;
  weekly_return?: number | null;
  monthly_return?: number | null;
  quarterly_return?: number | null;
  semiannual_return?: number | null;
  annual_return?: number | null;
  is_held?: boolean;
  is_updated?: boolean;
  group_ids?: number[];
};

export type WatchlistGroup = {
  id: number;
  name: string;
  sort_order: number;
  fund_count?: number;
};

export type FundSearchItem = {
  fund_code: string;
  fund_name: string;
  fund_type?: string | null;
  latest_nav?: number | null;
  nav_date?: string | null;
  daily_return?: number | null;
  is_watchlisted?: boolean;
  is_held?: boolean;
};

export type FundDetail = {
  fund_code: string;
  fund_name: string;
  fund_type?: string | null;
  company?: string | null;
  manager_name?: string | null;
  inception_date?: string | null;
  asset_size?: string | null;
  latest_nav?: number | null;
  accumulated_nav?: number | null;
  nav_date?: string | null;
  daily_return?: number | null;
  is_watchlisted?: boolean;
  is_held?: boolean;
  performance?: {
    return_1m?: number | null;
    return_3m?: number | null;
    return_6m?: number | null;
    return_1y?: number | null;
    return_3y?: number | null;
    return_since_inception?: number | null;
    max_drawdown?: number | null;
    annualized_volatility?: number | null;
  } | null;
};

export type FundNavPoint = {
  nav_date: string;
  unit_nav: number;
  accumulated_nav?: number | null;
  daily_return?: number | null;
};

export type FundHoldingItem = {
  stock_code: string;
  stock_name?: string | null;
  symbol?: string | null;
  weight?: number | null;
  weight_change?: number | null;
  is_new?: boolean;
  price?: number | null;
  change_pct?: number | null;
};

export type FundHoldings = {
  fund_code: string;
  quarter?: string | null;
  previous_quarter?: string | null;
  items: FundHoldingItem[];
  industries?: Array<{ industry: string; weight?: number | null }>;
};

export type IndexQuote = {
  index_code: string;
  name: string;
  close: number;
  change_pct: number;
  trade_date: string;
};

export type SectorItem = {
  code: string;
  name: string;
  sector_type: string;
  change_pct?: number | null;
  leading_stock?: { code: string; name?: string | null; change_pct?: number | null } | null;
};

export type TransactionItem = {
  id: number;
  account_id: number;
  fund_code: string;
  fund_name?: string | null;
  transaction_type: string;
  trade_date: string;
  confirm_date?: string | null;
  shares?: number | null;
  nav?: number | null;
  amount?: number | null;
  fee?: number | null;
  source: string;
  external_transaction_id?: string | null;
  created_at?: string | null;
};

export type TradeOperation = 'BUY' | 'SELL' | 'AUTO_INVEST' | 'CONVERT';

export type TradeLeg = {
  fund_code: string;
  direction: 'BUY' | 'SELL';
  confirm_nav: number;
  confirm_nav_date: string;
  shares_delta: number;
  amount: number;
  shares_before: number;
  cost_before: number;
  shares_after: number;
  cost_after: number;
};

export type TradePreview = {
  operation: TradeOperation;
  trade_date: string;
  after_cutoff: boolean;
  confirm_date: string;
  legs: TradeLeg[];
};

export type TradeRequest = {
  account_id: number;
  operation: TradeOperation;
  trade_date: string;
  after_cutoff?: boolean;
  amount?: number | null;
  shares?: number | null;
  target_code?: string | null;
  idempotency_key: string;
};

export type AutoInvestPlan = {
  id: number;
  account_id: number;
  fund_code: string;
  fund_name?: string | null;
  amount: number;
  frequency: 'daily' | 'weekly' | 'biweekly' | 'monthly';
  run_day: number;
  start_date: string;
  end_date?: string | null;
  active: boolean;
  last_run_date?: string | null;
  next_due?: string | null;
};

export type ImportCandidate = {
  fund_code: string;
  fund_name: string;
  score: number;
};

export type ImportItem = {
  id: number;
  raw_fund_name?: string | null;
  matched_fund_code?: string | null;
  matched_fund_name?: string | null;
  market_value?: number | null;
  shares?: number | null;
  cost_amount?: number | null;
  average_cost_nav?: number | null;
  profit_loss?: number | null;
  profit_loss_rate?: number | null;
  confidence?: number | null;
  validation_status: string;
  validation_issues?: string[];
  user_action?: string | null;
  current_market_value?: number | null;
  current_version?: number | null;
  candidates?: ImportCandidate[];
};

export type ImportBatch = {
  id: string;
  account_id: number | null;
  import_type: string;
  status: string;
  image_count?: number;
  items_detected?: number;
  items_confirmed?: number;
  error_message?: string | null;
  created_at?: string | null;
  items?: ImportItem[];
};

export type ManualPositionInput = {
  fund_code?: string | null;
  fund_name?: string | null;
  market_value?: number | null;
  profit_loss?: number | null;
};

export type MarketQuote = {
  symbol: string;
  listing_code?: string | null;
  kind: string;
  name?: string | null;
  currency?: string | null;
  price?: number | null;
  prev_close?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  volume_unit?: string | null;
  amount?: number | null;
  turnover_rate?: number | null;
  amplitude?: number | null;
  pe?: number | null;
  pb?: number | null;
  float_market_cap?: number | null;
  total_market_cap?: number | null;
  week52_high?: number | null;
  week52_low?: number | null;
  quote_time?: string | null;
};

export type MarketBar = {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume?: number | null;
};

export type MarketHistory = {
  symbol: string;
  kind: string;
  period: 'day' | 'week' | 'month';
  range: string;
  bars: MarketBar[];
  total: number;
  period_return?: number | null;
};

export type MarketMinute = {
  time: string;
  price: number;
  volume?: number | null;
  amount?: number | null;
  average_price?: number | null;
  trade_date?: string | null;
};

export type MarketIntraday = {
  symbol: string;
  kind: string;
  days: 1 | 5;
  trade_date?: string | null;
  prev_close?: number | null;
  points: MarketMinute[];
  total: number;
};

export type MarketCompany = {
  symbol: string;
  company?: {
    symbol: string;
    name?: string | null;
    industry?: string | null;
    region?: string | null;
    list_date?: string | null;
    main_business?: string | null;
    description?: string | null;
    employees?: number | null;
    concepts?: string[];
  } | null;
};

export type NavHistory = {
  fund_code: string;
  range?: string | null;
  points: FundNavPoint[];
  total?: number;
  has_more?: boolean;
};

export type FundComparisonChartFund = {
  fund_code: string;
  window_change_ratio?: number | null;
  observed_max_drawdown_ratio?: number | null;
  annualized_nav_volatility_ratio?: number | null;
  aligned_count?: number;
  stale?: boolean;
};

export type FundComparisonChartRef = {
  version?: 1;
  fund_codes: string[];
  common_from: string;
  common_to: string;
  aligned_count?: number;
  funds: FundComparisonChartFund[];
};

export type FundComparisonSeriesFund = {
  fund_code: string;
  fund_name?: string | null;
  points?: Array<{ nav_date: string; change_ratio: number }>;
  period_returns?: {
    return_1m?: number | null;
    return_3m?: number | null;
    return_6m?: number | null;
    return_1y?: number | null;
  };
};

export type FundComparisonSeries = {
  common_from?: string | null;
  common_to?: string | null;
  aligned_count?: number;
  funds?: FundComparisonSeriesFund[];
  stale?: boolean;
  gaps?: string[];
  warnings?: string[];
};

export type SectorMarket = {
  requested_date: string;
  warnings: string[];
  sectors: Array<{
    sector_code: string;
    name: string;
    sector_type: 'industry' | 'concept';
    price: number | null;
    change_pct: number | null;
    quote_time: string | null;
    stale: boolean;
    error_code: string | null;
  }>;
};

export type AllocationPreview = {
  captured_at: string;
  warnings: string[];
  scenario: {
    available: boolean;
    reason?: string;
    assumption?: string;
    amount?: number;
    before_fund_assets?: number;
    after_fund_assets?: number;
    before_target_value?: number;
    after_target_value?: number;
    before_weight_ratio?: number | null;
    after_weight_ratio?: number | null;
  };
};

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const values = Object.entries(params).filter(
    (entry): entry is [string, string | number | boolean] =>
      entry[1] !== null && entry[1] !== undefined,
  );
  if (!values.length) return '';
  return (
    '?' +
    values
      .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
      .join('&')
  );
}

export async function listAccounts(token: string): Promise<AccountItem[]> {
  const data = await request<{ items: AccountItem[] }>('/accounts', {}, token);
  return data.items;
}

export async function createAccount(token: string, name: string): Promise<AccountItem> {
  return request<AccountItem>(
    '/accounts',
    {
      method: 'POST',
      body: JSON.stringify({ name, account_type: 'manual', import_mode: 'manual' }),
    },
    token,
  );
}

export async function getPortfolioSummary(
  token: string,
  accountId: number | null,
): Promise<PortfolioSummary> {
  const data = await request<{ summary: PortfolioSummary }>(
    `/portfolio/summary${query({ account_id: accountId })}`,
    {},
    token,
  );
  return data.summary;
}

export async function getPositions(
  token: string,
  accountId: number | null,
): Promise<PositionItem[]> {
  const data = await request<{ items: PositionItem[] }>(
    `/portfolio/positions${query({ account_id: accountId })}`,
    {},
    token,
  );
  return data.items;
}

export async function listWatchlist(
  token: string,
  groupId: number | null,
): Promise<WatchlistItem[]> {
  const data = await request<{ items: WatchlistItem[] }>(
    `/watchlist${query({ group_id: groupId })}`,
    {},
    token,
  );
  return data.items;
}

export async function listWatchlistGroups(token: string): Promise<WatchlistGroup[]> {
  const data = await request<{ items: WatchlistGroup[] }>('/watchlist/groups', {}, token);
  return data.items;
}

export async function removeWatchlistFund(token: string, code: string): Promise<void> {
  await request(`/watchlist/${code}`, { method: 'DELETE' }, token);
}

export async function addWatchlistFund(
  token: string,
  code: string,
  groupIds: number[] = [],
): Promise<void> {
  await request(
    '/watchlist',
    {
      method: 'POST',
      body: JSON.stringify({ fund_code: code, group_ids: groupIds }),
    },
    token,
  );
}

export async function searchFunds(token: string, keyword: string): Promise<FundSearchItem[]> {
  const data = await request<{ items: FundSearchItem[] }>(
    `/funds/search${query({ q: keyword })}`,
    {},
    token,
  );
  return data.items;
}

export async function getFundDetail(token: string, code: string): Promise<FundDetail> {
  return request<FundDetail>(`/funds/${code}`, {}, token);
}

export async function getFundNav(
  token: string,
  code: string,
  range = '1y',
): Promise<FundNavPoint[]> {
  const data = await request<{ points: FundNavPoint[] }>(
    `/funds/${code}/nav${query({ range })}`,
    {},
    token,
  );
  return data.points;
}

export async function getFundHoldings(token: string, code: string): Promise<FundHoldings> {
  return request<FundHoldings>(`/funds/${code}/holdings`, {}, token);
}

export async function getIndexQuotes(token: string): Promise<IndexQuote[]> {
  const data = await request<{ items: IndexQuote[] }>('/indexes/quotes', {}, token);
  return data.items;
}

export type ImportHistoryItem = {
  id: string;
  status: string;
  account_id: number;
  import_type: string;
  items_detected: number;
  items_confirmed: number;
  created_at: string;
  error_message?: string | null;
};

export async function getImportHistory(token: string): Promise<ImportHistoryItem[]> {
  const data = await request<{ items: ImportHistoryItem[] }>(
    '/holding-imports/history',
    {},
    token,
  );
  return data.items;
}

export async function getSectorBoard(
  token: string,
  kind: 'industry' | 'concept',
): Promise<SectorItem[]> {
  const data = await request<{ items: SectorItem[] }>(
    `/sectors/board${query({ kind, order: 'desc', sort: 'change_pct', limit: 10 })}`,
    {},
    token,
  );
  return data.items;
}

export async function updateAccount(
  token: string,
  accountId: number,
  name: string,
): Promise<AccountItem> {
  return request<AccountItem>(
    `/accounts/${accountId}`,
    { method: 'PATCH', body: JSON.stringify({ name }) },
    token,
  );
}

export async function deleteAccount(token: string, accountId: number): Promise<void> {
  await request(`/accounts/${accountId}`, { method: 'DELETE' }, token);
}

export async function getPosition(
  token: string,
  accountId: number,
  fundCode: string,
): Promise<PositionItem> {
  return request<PositionItem>(
    `/portfolio/positions/${fundCode}${query({ account_id: accountId })}`,
    {},
    token,
  );
}

export async function upsertPosition(
  token: string,
  fundCode: string,
  payload: {
    account_id: number;
    shares?: number | null;
    market_value?: number | null;
    average_cost_nav?: number | null;
    profit_loss?: number | null;
    purchase_date?: string | null;
    reset?: Array<'shares' | 'average_cost_nav' | 'profit_loss'>;
    expected_version?: number | null;
  },
): Promise<PositionItem> {
  return request<PositionItem>(
    `/portfolio/positions/${fundCode}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    token,
  );
}

export async function deletePosition(
  token: string,
  accountId: number,
  fundCode: string,
): Promise<void> {
  await request(
    `/portfolio/positions/${fundCode}${query({ account_id: accountId })}`,
    { method: 'DELETE' },
    token,
  );
}

export async function recordTrade(
  token: string,
  fundCode: string,
  payload: TradeRequest,
): Promise<PositionItem> {
  return request<PositionItem>(
    `/portfolio/positions/${fundCode}/trades`,
    { method: 'POST', body: JSON.stringify(payload) },
    token,
  );
}

export async function previewTrade(
  token: string,
  fundCode: string,
  params: {
    accountId: number;
    operation: TradeOperation;
    tradeDate: string;
    afterCutoff: boolean;
    amount: string;
    shares: string;
    targetCode: string;
  },
): Promise<TradePreview> {
  return request<TradePreview>(
    `/portfolio/positions/${fundCode}/trades/preview${query({
      account_id: params.accountId,
      operation: params.operation,
      trade_date: params.tradeDate,
      after_cutoff: params.afterCutoff,
      amount: params.amount === '' ? null : Number(params.amount),
      shares: params.shares === '' ? null : Number(params.shares),
      target_code: params.operation === 'CONVERT' ? params.targetCode.trim() : null,
    })}`,
    {},
    token,
  );
}

export async function getTransactions(
  token: string,
  accountId: number | null,
  fundCode: string | null,
): Promise<TransactionItem[]> {
  const data = await request<{ items: TransactionItem[] }>(
    `/transactions${query({ account_id: accountId, fund_code: fundCode })}`,
    {},
    token,
  );
  return data.items;
}

export async function listAutoInvestPlans(
  token: string,
  accountId: number | null,
): Promise<{ items: AutoInvestPlan[]; settled: number }> {
  const data = await request<{ items: AutoInvestPlan[]; settled?: number }>(
    `/auto-invest/plans${query({ account_id: accountId })}`,
    {},
    token,
  );
  return { items: data.items, settled: data.settled ?? 0 };
}

export async function createAutoInvestPlan(
  token: string,
  payload: {
    account_id: number;
    fund_code: string;
    amount: number;
    frequency: AutoInvestPlan['frequency'];
    run_day: number;
    start_date: string;
  },
): Promise<AutoInvestPlan> {
  return request<AutoInvestPlan>(
    '/auto-invest/plans',
    { method: 'POST', body: JSON.stringify(payload) },
    token,
  );
}

export async function updateAutoInvestPlan(
  token: string,
  planId: number,
  payload: { active?: boolean },
): Promise<AutoInvestPlan> {
  return request<AutoInvestPlan>(
    `/auto-invest/plans/${planId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    token,
  );
}

export async function deleteAutoInvestPlan(
  token: string,
  planId: number,
): Promise<void> {
  await request(
    `/auto-invest/plans/${planId}${query({ with_orders: false })}`,
    { method: 'DELETE' },
    token,
  );
}

export async function updateWatchlistFund(
  token: string,
  fundCode: string,
  groupIds: number[],
): Promise<void> {
  await request(
    `/watchlist/${fundCode}`,
    { method: 'PATCH', body: JSON.stringify({ group_ids: groupIds }) },
    token,
  );
}

export async function createWatchlistGroup(
  token: string,
  name: string,
): Promise<WatchlistGroup> {
  return request<WatchlistGroup>(
    '/watchlist/groups',
    { method: 'POST', body: JSON.stringify({ name }) },
    token,
  );
}

export async function updateWatchlistGroup(
  token: string,
  groupId: number,
  payload: { name?: string; fund_codes?: string[] },
): Promise<WatchlistGroup> {
  return request<WatchlistGroup>(
    `/watchlist/groups/${groupId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    token,
  );
}

export async function deleteWatchlistGroup(
  token: string,
  groupId: number,
): Promise<void> {
  await request(`/watchlist/groups/${groupId}`, { method: 'DELETE' }, token);
}

export async function createManualImport(
  token: string,
  accountId: number,
  positions: ManualPositionInput[],
): Promise<ImportBatch> {
  const data = await request<{ import_batch: ImportBatch }>(
    '/holding-imports/manual',
    {
      method: 'POST',
      body: JSON.stringify({ account_id: accountId, positions }),
    },
    token,
  );
  return data.import_batch;
}

export async function uploadScreenshots(
  token: string,
  accountId: number,
  files: File[],
): Promise<{ import_id: string }> {
  const form = new FormData();
  for (const file of files) form.append('files', file, file.name);
  const response = await fetch(
    `${API_BASE_URL}/holding-imports/screenshots${query({ account_id: accountId })}`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    },
  );
  if (!response.ok) throw new Error(`上传失败（${response.status}）`);
  return (await response.json()) as { import_id: string };
}

export async function getImportDetail(
  token: string,
  importId: string,
): Promise<ImportBatch> {
  const data = await request<{ import_batch: ImportBatch }>(
    `/holding-imports/${importId}`,
    {},
    token,
  );
  return data.import_batch;
}

export async function updateImportItem(
  token: string,
  importId: string,
  itemId: number,
  payload: {
    user_action?: string;
    fund_code?: string;
    market_value?: number | null;
  },
): Promise<ImportItem> {
  return request<ImportItem>(
    `/holding-imports/${importId}/items/${itemId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    token,
  );
}

export async function confirmImport(
  token: string,
  importId: string,
): Promise<{ applied: number; skipped: number }> {
  return request<{ applied: number; skipped: number }>(
    `/holding-imports/${importId}/confirm`,
    { method: 'POST' },
    token,
  );
}

export async function deleteImport(token: string, importId: string): Promise<void> {
  await request(`/holding-imports/${importId}`, { method: 'DELETE' }, token);
}

export async function getMarketQuote(
  token: string,
  symbol: string,
): Promise<MarketQuote> {
  return request<MarketQuote>(`/markets/${symbol}/quote`, {}, token);
}

export async function getMarketHistory(
  token: string,
  symbol: string,
  period: 'day' | 'week' | 'month',
  range: string,
): Promise<MarketHistory> {
  return request<MarketHistory>(
    `/markets/${symbol}/history${query({ period, range })}`,
    {},
    token,
  );
}

export async function getMarketIntraday(
  token: string,
  symbol: string,
  days: 1 | 5,
): Promise<MarketIntraday> {
  return request<MarketIntraday>(
    `/markets/${symbol}/intraday${query({ days })}`,
    {},
    token,
  );
}

export async function getMarketCompany(
  token: string,
  symbol: string,
): Promise<MarketCompany> {
  return request<MarketCompany>(`/markets/${symbol}/company`, {}, token);
}

export async function getFundNavPage(
  token: string,
  code: string,
  beforeDate: string | null,
  limit = 30,
): Promise<NavHistory> {
  return request<NavHistory>(
    `/funds/${code}/nav${query({ limit, before_date: beforeDate })}`,
    {},
    token,
  );
}

export async function getFundComparisonNav(
  token: string,
  chart: FundComparisonChartRef,
): Promise<FundComparisonSeries> {
  return request<FundComparisonSeries>(
    '/funds/compare/nav',
    {
      method: 'POST',
      body: JSON.stringify({
        fund_codes: chart.fund_codes,
        from_date: chart.common_from,
        to_date: chart.common_to,
      }),
    },
    token,
  );
}

export async function getSectorMarket(
  token: string,
  sectorCode: string,
  sectorType: 'industry' | 'concept',
): Promise<SectorMarket> {
  return request<SectorMarket>(
    `/sectors/market${query({
      keyword: sectorCode,
      sector_type: sectorType,
      limit: 1,
    })}`,
    {},
    token,
  );
}

export async function getAllocationPreview(
  token: string,
  fundCode: string,
  accountId: number | null,
  action: 'build' | 'increase' | 'reduce' | 'exit',
  amount: number,
): Promise<AllocationPreview> {
  return request<AllocationPreview>(
    `/portfolio/allocation-preview${query({
      fund_code: fundCode,
      account_id: accountId,
      action,
      amount,
    })}`,
    {},
    token,
  );
}
