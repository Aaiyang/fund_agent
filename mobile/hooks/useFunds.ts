/** Fund search, detail, NAV history and refresh triggers (spec 3.4 / 3.5). */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, request } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type FundSearchItem = components['schemas']['FundSearchItem'];
export type FundDetail = components['schemas']['FundDetailResponse'];
export type NavHistory = components['schemas']['FundNavHistoryResponse'];
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
    queryKey: queryKeys.fundNavPages(code ?? ''),
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

/** Enqueue a provider sync; the fund detail/NAV queries refetch afterwards. */
export function useRefreshFund(code: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<components['schemas']['FundSyncStatusResponse']>(`/funds/${code}/refresh`, { method: 'POST' }),
    onSuccess: async () => {
      // The worker writes asynchronously; give it a moment, then re-read.
      await new Promise((resolve) => setTimeout(resolve, 2500));
      await client.invalidateQueries({ queryKey: queryKeys.funds });
    },
  });
}
