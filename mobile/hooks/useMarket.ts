/**
 * 单只上市品种的分析数据源：快照、K 线、分钟线、公司简介。
 *
 * 这些数据服务端都不落库，各 hook 的 `staleTime` 就是页面与适配器层调用
 * 之间唯一的缓冲；它们对齐后端用的缓存有效期，因为拉得比那更勤毫无意义。
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';
import type { NavRange } from '@/hooks/useFunds';

export type MarketQuote = components['schemas']['SymbolQuoteResponse'];
export type MarketHistory = components['schemas']['SymbolHistoryResponse'];
export type MarketIntraday = components['schemas']['SymbolIntradayResponse'];
export type MarketCompany = components['schemas']['SymbolCompanyResponse'];
export type MarketPeriod = components['schemas']['SymbolHistoryResponse']['period'];

export function useMarketQuote(symbol: string | null) {
  return useQuery({
    queryKey: queryKeys.marketQuote(symbol ?? ''),
    queryFn: () => api.get<MarketQuote>(`/markets/${symbol}/quote`),
    enabled: Boolean(symbol),
    refetchInterval: 1000 * 30,
    refetchIntervalInBackground: false,
  });
}

export function useMarketHistory(symbol: string | null, period: MarketPeriod, range: NavRange) {
  return useQuery({
    queryKey: queryKeys.marketHistory(symbol ?? '', period, range),
    queryFn: () =>
      api.get<MarketHistory>(`/markets/${symbol}/history`, {
        period,
        range,
      }),
    enabled: Boolean(symbol),
    staleTime: 1000 * 60 * 10,
  });
}

/** 只在分钟线标签开着时拉，也只在它还可能变化的时段拉。 */
export function useMarketIntraday(symbol: string | null, enabled: boolean, days: 1 | 5 = 1) {
  return useQuery({
    queryKey: queryKeys.marketIntraday(symbol ?? '', days),
    queryFn: () => api.get<MarketIntraday>(`/markets/${symbol}/intraday`, { days }),
    enabled: Boolean(symbol) && enabled,
    refetchInterval: 1000 * 60,
    refetchIntervalInBackground: false,
    staleTime: 1000 * 60,
  });
}

/** 公司概况最多随季报冻结一次，缓存一天足矣。 */
export function useMarketCompany(symbol: string | null) {
  return useQuery({
    queryKey: queryKeys.marketCompany(symbol ?? ''),
    queryFn: () => api.get<MarketCompany>(`/markets/${symbol}/company`),
    enabled: Boolean(symbol),
    staleTime: 1000 * 60 * 60 * 24,
  });
}
