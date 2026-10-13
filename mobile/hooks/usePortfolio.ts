/** 持仓、资产汇总、账户与流水（spec 3.2 / 3.6 / 3.8）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';
import { useUiStore } from '@/stores/ui';

export type PositionItem = components['schemas']['PositionItem'];
export type PortfolioSummary = components['schemas']['PortfolioSummary'];
export type AccountItem = components['schemas']['AccountItem'];
export type TransactionItem = components['schemas']['TransactionItem'];

/** 账户有写入，账户列表和所有派生的持仓视图都要一起失效。 */
function invalidateAccounts(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.accounts }),
    client.invalidateQueries({ queryKey: queryKeys.chatPendingAction }),
    client.invalidateQueries({ queryKey: queryKeys.portfolio }),
    client.invalidateQueries({ queryKey: queryKeys.transactionsAll }),
  ]);
}

/** 持仓写入还会附带生成调整记录。 */
function invalidatePositions(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.portfolio }),
    client.invalidateQueries({ queryKey: queryKeys.transactionsAll }),
    client.invalidateQueries({ queryKey: queryKeys.funds }),
  ]);
}

export function usePortfolioSummary(accountId: number | null) {
  return useQuery({
    queryKey: queryKeys.portfolioSummary(accountId),
    queryFn: () =>
      api.get<components['schemas']['PortfolioSummaryResponse']>('/portfolio/summary', { account_id: accountId }),
  });
}

export type AccountSummaryRow = { accountId: number; summary: PortfolioSummary | null };

/**
 * 首页那种"每个账户一张汇总卡"要一次拿齐所有账户。
 *
 * 后端没有跨账户的批量汇总端点，所以逐只并发取；某一只失败只让那张卡显示
 * "没取到"，不能把整屏判成失败——其余账户的数字是真的。
 */
export function usePortfolioSummaries(accountIds: number[]) {
  const key = [...accountIds].sort((a, b) => a - b).join(',');
  return useQuery({
    queryKey: [...queryKeys.portfolio, 'summaries', key],
    queryFn: async (): Promise<AccountSummaryRow[]> => {
      const settled = await Promise.allSettled(
        accountIds.map((id) =>
          api.get<components['schemas']['PortfolioSummaryResponse']>('/portfolio/summary', { account_id: id }),
        ),
      );
      return settled.map((result, index) => ({
        accountId: accountIds[index],
        summary: result.status === 'fulfilled' ? result.value.summary : null,
      }));
    },
    enabled: accountIds.length > 0,
  });
}

export function usePositions(accountId: number | null) {
  return useQuery({
    queryKey: queryKeys.positions(accountId),
    queryFn: () => api.get<components['schemas']['PositionsResponse']>('/portfolio/positions', { account_id: accountId }),
  });
}

export function usePosition(accountId: number | null, fundCode: string | null) {
  return useQuery({
    queryKey: queryKeys.position(accountId ?? -1, fundCode ?? ''),
    queryFn: () => api.get<PositionItem>(`/portfolio/positions/${fundCode}`, { account_id: accountId }),
    enabled: Boolean(fundCode),
  });
}

export type TradeOperation = components['schemas']['TradeCreateRequest']['operation'];

/**
 * 这一单会对持仓产生什么影响：任何东西落库前，先按它的确认日定价算一遍。
 * 这笔账要用到净值历史，所以留在服务端算，表单只负责把答案显示出来。
 */
export function useTradePreview(input: {
  accountId: number | null;
  fundCode: string;
  operation: TradeOperation;
  tradeDate: string;
  afterCutoff: boolean;
  amount: string;
  shares: string;
  targetCode: string;
}) {
  const { accountId, fundCode, operation, tradeDate, afterCutoff, amount, shares, targetCode } = input;
  const sized = operation === 'BUY' || operation === 'AUTO_INVEST' ? amount !== '' : shares !== '';
  const converted = operation !== 'CONVERT' || /^\d{6}$/.test(targetCode.trim());
  const ready =
    accountId !== null &&
    /^\d{6}$/.test(fundCode) &&
    /^\d{4}-\d{2}-\d{2}$/.test(tradeDate.trim()) &&
    sized &&
    converted;
  return useQuery({
    queryKey: queryKeys.tradePreview(
      accountId ?? -1,
      fundCode,
      operation,
      tradeDate,
      afterCutoff,
      amount,
      shares,
      targetCode,
    ),
    queryFn: () =>
      api.get<components['schemas']['TradePreviewResponse']>(`/portfolio/positions/${fundCode}/trades/preview`, {
        account_id: accountId,
        operation,
        trade_date: tradeDate,
        after_cutoff: afterCutoff,
        amount: amount === '' ? null : Number(amount),
        shares: shares === '' ? null : Number(shares),
        target_code: operation === 'CONVERT' ? targetCode.trim() : null,
      }),
    enabled: ready,
    staleTime: 60_000,
  });
}

export function useAccounts() {
  return useQuery({
    queryKey: queryKeys.accounts,
    queryFn: () => api.get<components['schemas']['AccountsResponse']>('/accounts'),
  });
}

export function useCreateAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: components['schemas']['AccountCreateRequest']) => api.post<AccountItem>('/accounts', payload),
    onSuccess: () => invalidateAccounts(client),
  });
}

export function useUpdateAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, ...payload }: { accountId: number } & components['schemas']['AccountUpdateRequest']) =>
      api.patch<AccountItem>(`/accounts/${accountId}`, payload),
    onSuccess: () => invalidateAccounts(client),
  });
}

export function useDeleteAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (accountId: number) => api.del(`/accounts/${accountId}`),
    onSuccess: (_data, accountId) => {
      // 导航层记着选中的账户，各页面现在都默认按它取数。
      // 选中项若还指向已删除的 id，那些页面就会去问服务端一个只回
      // 404 的账户。
      const ui = useUiStore.getState();
      if (ui.accountId === accountId) ui.setAccountId(null);
      return invalidateAccounts(client);
    },
  });
}

/**
 * 同步持仓：照实转述持仓页面上的数字。更新已存在的行必须带
 * `expected_version`，版本过期会回 409（spec 7.11）。
 */
export function useUpsertPosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fundCode, ...payload }: { fundCode: string } & components['schemas']['PositionUpsertRequest']) =>
      api.patch<PositionItem>(`/portfolio/positions/${fundCode}`, payload),
    onSuccess: () => invalidatePositions(client),
  });
}

/** 加减仓：记一笔订单。服务端会拿流水把持仓重新投影一遍。 */
export function useRecordTrade() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      fundCode,
      ...payload
    }: { fundCode: string } & components['schemas']['TradeCreateRequest']) =>
      api.post<PositionItem>(`/portfolio/positions/${fundCode}/trades`, payload),
    onSuccess: () => invalidatePositions(client),
  });
}

export function useDeletePosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, fundCode }: { accountId: number; fundCode: string }) =>
      api.del(`/portfolio/positions/${fundCode}`, { account_id: accountId }),
    onSuccess: () => invalidatePositions(client),
  });
}

export function useTransactions(accountId: number | null, fundCode: string | null) {
  return useQuery({
    queryKey: queryKeys.transactions(accountId, fundCode),
    queryFn: () =>
      api.get<components['schemas']['TransactionsResponse']>('/transactions', {
        account_id: accountId,
        fund_code: fundCode,
      }),
  });
}
