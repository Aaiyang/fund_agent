/** Positions, asset summary, accounts and transactions (spec 3.2 / 3.6 / 3.8). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';
import { useUiStore } from '@/stores/ui';

export type PositionItem = components['schemas']['PositionItem'];
export type PortfolioSummary = components['schemas']['PortfolioSummary'];
export type AccountItem = components['schemas']['AccountItem'];
export type TransactionItem = components['schemas']['TransactionItem'];

/** Account writes change both the account list and every derived holding view. */
function invalidateAccounts(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.accounts }),
    client.invalidateQueries({ queryKey: queryKeys.portfolio }),
    client.invalidateQueries({ queryKey: queryKeys.transactionsAll }),
  ]);
}

/** Position writes also append adjustment records. */
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
 * What an order would do to the holding, priced on its confirm day before
 * anything is written. The arithmetic needs the NAV history, so it stays on the
 * server and the form just shows the answer.
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
      // The navigation keeps a selected account, and screens now default to it.
      // Leaving the choice pointing at a deleted id would make those screens ask
      // the server for an account it answers 404 for.
      const ui = useUiStore.getState();
      if (ui.accountId === accountId) ui.setAccountId(null);
      return invalidateAccounts(client);
    },
  });
}

/**
 * 同步持仓: restate what the holdings screen shows. `expected_version` is
 * required when updating an existing row; a stale version comes back as 409
 * (spec 7.11).
 */
export function useUpsertPosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fundCode, ...payload }: { fundCode: string } & components['schemas']['PositionUpsertRequest']) =>
      api.patch<PositionItem>(`/portfolio/positions/${fundCode}`, payload),
    onSuccess: () => invalidatePositions(client),
  });
}

/** 加减仓: record one order. The server re-projects the holding from the ledger. */
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
