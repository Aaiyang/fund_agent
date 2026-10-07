/** 自选基金与自选分组（spec 3.3）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { QueryClient } from '@tanstack/react-query';
import type { components } from '@/api/schema';

export type WatchlistFund = components['schemas']['WatchlistFundItem'];
export type WatchlistGroup = components['schemas']['WatchlistGroupItem'];

/** 加自选、删自选会连带改变搜索结果里的 is_watchlisted 标记。 */
function invalidateWatchlist(client: QueryClient) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.watchlist }),
    client.invalidateQueries({ queryKey: queryKeys.funds }),
  ]);
}

export function useWatchlist(groupId: number | null) {
  return useQuery({
    queryKey: [...queryKeys.watchlist, groupId],
    queryFn: () => api.get<components['schemas']['WatchlistResponse']>('/watchlist', { group_id: groupId }),
  });
}

export function useWatchlistGroups() {
  return useQuery({
    queryKey: queryKeys.watchlistGroups,
    queryFn: () => api.get<components['schemas']['WatchlistGroupsResponse']>('/watchlist/groups'),
  });
}

export function useAddWatchlistFund() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: components['schemas']['WatchlistAddRequest']) => api.post('/watchlist', payload),
    onSuccess: () => invalidateWatchlist(client),
  });
}

export function useRemoveWatchlistFund() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (fundCode: string) => api.del(`/watchlist/${fundCode}`),
    onSuccess: () => invalidateWatchlist(client),
  });
}

/** `group_ids` 是整体覆盖成员关系，传空数组就是把基金移出所有分组。 */
export function useUpdateWatchlistFund() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ fundCode, ...payload }: { fundCode: string } & components['schemas']['WatchlistUpdateRequest']) =>
      api.patch(`/watchlist/${fundCode}`, payload),
    onSuccess: () => invalidateWatchlist(client),
  });
}

export function useCreateWatchlistGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: components['schemas']['WatchlistGroupCreateRequest']) =>
      api.post<WatchlistGroup>('/watchlist/groups', payload),
    onSuccess: () => invalidateWatchlist(client),
  });
}

/** 带上 `fund_codes` 的同时也会把组内顺序定下来（spec 3.3 排序）。 */
export function useUpdateWatchlistGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ groupId, ...payload }: { groupId: number } & components['schemas']['WatchlistGroupUpdateRequest']) =>
      api.patch<WatchlistGroup>(`/watchlist/groups/${groupId}`, payload),
    onSuccess: () => invalidateWatchlist(client),
  });
}

export function useDeleteWatchlistGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (groupId: number) => api.del(`/watchlist/groups/${groupId}`),
    onSuccess: () => invalidateWatchlist(client),
  });
}
