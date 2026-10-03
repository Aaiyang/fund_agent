/** Fund search, detail, NAV history and refresh triggers (spec 3.4 / 3.5). */

import { useFocusEffect } from 'expo-router';
import { useCallback } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, request } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type FundSearchItem = components['schemas']['FundSearchItem'];
export type FundDetail = components['schemas']['FundDetailResponse'];
export type FundHoldingItem = components['schemas']['FundHoldingItem'];
export type FundHoldings = components['schemas']['FundHoldingsResponse'];
export type NavHistory = components['schemas']['FundNavHistoryResponse'];
export type FundNavRefresh = components['schemas']['FundNavRefreshResponse'];
export type NavRange = '1m' | '3m' | '6m' | '1y' | '3y' | 'all';

export const NAV_RANGES: { key: NavRange; label: string }[] = [
  { key: '1m', label: '1月' },
  { key: '3m', label: '3月' },
  { key: '6m', label: '6月' },
  { key: '1y', label: '1年' },
  { key: '3y', label: '3年' },
  { key: 'all', label: '成立来' },
];

export function useFundSearch(keyword: string) {
  return useQuery({
    queryKey: queryKeys.fundSearch(keyword.trim()),
    queryFn: () => api.get<components['schemas']['FundSearchResponse']>('/funds/search', { q: keyword.trim() }),
    enabled: keyword.trim().length > 0,
    placeholderData: (previous) => previous,
  });
}

export function useFundDetail(code: string | null) {
  return useQuery({
    queryKey: queryKeys.fundDetail(code ?? ''),
    queryFn: () => request<FundDetail>(`/funds/${code}`),
    enabled: Boolean(code),
  });
}

export function useFundNav(code: string | null, range: NavRange) {
  return useQuery({
    queryKey: queryKeys.fundNav(code ?? '', range),
    queryFn: () => api.get<NavHistory>(`/funds/${code}/nav`, { range }),
    enabled: Boolean(code),
  });
}

/**
 * Cursor paging over the whole NAV history: 30 newest rows first, then older
 * pages as the list reaches its bottom. `before_date` is exclusive, so pages
 * never repeat a trading day.
 */
export function useFundNavPages(code: string | null, pageSize = 30) {
  return useInfiniteQuery({
    // pageSize is a request input, so it belongs in the key.
    queryKey: queryKeys.fundNavPages(code ?? '', pageSize),
    queryFn: ({ pageParam }) =>
      api.get<NavHistory>(`/funds/${code}/nav`, { limit: pageSize, before_date: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => {
      if (!lastPage.has_more) return undefined;
      const dates = lastPage.points.map((point) => point.nav_date);
      return dates.length ? dates.reduce((oldest, value) => (value < oldest ? value : oldest)) : undefined;
    },
    enabled: Boolean(code),
  });
}

/**
 * Top-ten holdings with quotes, polled while the page is open. 30s is the
 * balance between "实时涨幅" feeling live and hitting the source 3x harder;
 * the backend caches the quarterly disclosure for an hour and only the quote
 * fetch repeats.
 */
export function useFundHoldings(code: string | null) {
  return useQuery({
    queryKey: queryKeys.fundHoldings(code ?? ''),
    queryFn: () => request<FundHoldings>(`/funds/${code}/holdings`),
    enabled: Boolean(code),
    refetchInterval: 30_000,
  });
}

/** Enqueue a provider sync; the fund detail/NAV queries refetch afterwards. */
export function useRefreshFund(code: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<components['schemas']['FundSyncStatusResponse']>(`/funds/${code}/refresh`, { method: 'POST' }),
    onSuccess: async () => {
      // The worker writes asynchronously; give it a moment, then re-read.
      await new Promise((resolve) => setTimeout(resolve, 2500));
      // Watchlist and holding rows render the same NAV, so they are stale too.
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.funds }),
        client.invalidateQueries({ queryKey: queryKeys.watchlist }),
        client.invalidateQueries({ queryKey: queryKeys.portfolio }),
      ]);
    },
  });
}

/** Refresh every held + watchlisted fund's latest NAV in one batched request. */
export function useRefreshLatestNavs() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<components['schemas']['FundNavRefreshResponse']>('/funds/refresh-latest', { method: 'POST' }),
    onSuccess: async () => {
      // The endpoint stores the new NAVs before it answers, so this re-read is
      // the result the refresh was for rather than another attempt at it.
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.portfolio }),
        client.invalidateQueries({ queryKey: queryKeys.watchlist }),
        client.invalidateQueries({ queryKey: queryKeys.funds }),
      ]);
    },
  });
}

/**
 * Ask for fresh NAVs whenever the calling screen gains focus.
 *
 * Nothing else fires here: react-query's refetch-on-focus binds a browser
 * `visibilitychange` event that does not exist on native, and a tab stays
 * mounted after its first visit, so switching tabs is not a remount either.
 */
export function useNavRefreshOnFocus() {
  // Only `mutate` belongs in the dependency list. It is memoized against a
  // stable observer, while the rest of the result object is rebuilt on every
  // state change — depending on that would re-run this effect from its own
  // invalidation and refresh forever.
  const { mutate, isPending, data } = useRefreshLatestNavs();
  useFocusEffect(
    useCallback(() => {
      mutate();
    }, [mutate]),
  );
  return { isPending, result: data };
}

/**
 * One honest line about the batch refresh; silence is the normal outcome.
 *
 * A cooldown (`throttled`) response ran no request at all and changed nothing,
 * and `ok` with zero updates would read as a failure — so both say nothing.
 */
export function navRefreshNotice(pending: boolean, result?: FundNavRefresh): string | null {
  if (pending) return '正在刷新净值…';
  if (!result || result.status === 'ok' || result.status === 'throttled') return null;
  if (result.status === 'partial') {
    return `已更新 ${result.updated ?? 0} 只，${result.missing?.length ?? 0} 只已单独排队`;
  }
  if (result.status === 'deferred') return '净值抓取超时，显示的是上次数据';
  return '净值数据源不可用，显示的是上次数据';
}
