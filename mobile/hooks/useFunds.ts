/** 基金搜索、详情、净值历史与刷新触发（spec 3.4 / 3.5）。 */

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
 * 全量净值历史的游标分页：先给最新 30 条，列表滚到底再取更早的页。
 * `before_date` 不含边界，所以相邻的页不会重复同一个交易日。
 */
export function useFundNavPages(code: string | null, pageSize = 30) {
  return useInfiniteQuery({
    // pageSize 是请求入参，所以也要进 queryKey。
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
 * 前十大重仓股带行情，页面开着就轮询。30 秒是在“实时涨幅看起来够新鲜”
 * 与不把数据源打爆之间的折中；后端把季度披露缓存一小时，反复拉的
 * 只有行情那一截。
 */
export function useFundHoldings(code: string | null) {
  return useQuery({
    queryKey: queryKeys.fundHoldings(code ?? ''),
    queryFn: () => request<FundHoldings>(`/funds/${code}/holdings`),
    enabled: Boolean(code),
    refetchInterval: 30_000,
  });
}

/** 把数据源同步任务入队；完成后基金详情与净值查询会重新拉取。 */
export function useRefreshFund(code: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<components['schemas']['FundSyncStatusResponse']>(`/funds/${code}/refresh`, { method: 'POST' }),
    onSuccess: async () => {
      // worker 是异步落库的；稍等片刻再回读。
      await new Promise((resolve) => setTimeout(resolve, 2500));
      // 自选与持仓行渲染的是同一份净值，它们同样已经过期。
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.funds }),
        client.invalidateQueries({ queryKey: queryKeys.watchlist }),
        client.invalidateQueries({ queryKey: queryKeys.portfolio }),
      ]);
    },
  });
}

/** 一次批量请求，把所有持仓与自选基金的最新净值都刷一遍。 */
export function useRefreshLatestNavs() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<components['schemas']['FundNavRefreshResponse']>('/funds/refresh-latest', { method: 'POST' }),
    onSuccess: async () => {
      // 这个接口在应答之前已把新净值落库，所以这次重读读到的是刷新的
      // 成果，而不是对刷新本身再试一次。
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.portfolio }),
        client.invalidateQueries({ queryKey: queryKeys.watchlist }),
        client.invalidateQueries({ queryKey: queryKeys.funds }),
      ]);
    },
  });
}

/**
 * 调用方页面每次获得焦点就请求一次新净值。
 *
 * 其他时机都不会触发：react-query 的 refetch-on-focus 绑的是浏览器
 * `visibilitychange` 事件，原生端根本没有这个事件；而标签页首次访问后
 * 就一直挂着，切换标签页也构不成重新挂载。
 */
export function useNavRefreshOnFocus() {
  // 依赖表里只该放 `mutate`：它绑定在稳定的 observer 上做了 memo，而结果
  // 对象的其余部分每次状态变化都会重建——依赖那些的话，
  // 本 effect 会被自己触发的失效重新运行，
  // 刷个不停。
  const { mutate, isPending, data } = useRefreshLatestNavs();
  useFocusEffect(
    useCallback(() => {
      mutate();
    }, [mutate]),
  );
  return { isPending, result: data };
}

/**
 * 对批量刷新只说一句实话；没话可说才是常态。
 *
 * 冷却期（`throttled`）根本没发请求、什么都没改变，而 `ok` 却是零更新
 * 说出来会被当成失败——这两种情况都保持沉默。
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
