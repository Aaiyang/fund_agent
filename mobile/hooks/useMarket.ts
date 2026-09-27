/**
 * Analysis feed for one listed instrument: snapshot, bars, minute line, profile.
 *
 * Nothing here is stored server-side, so each hook's `staleTime` is the only
 * thing between the screen and a provider call; they mirror the TTLs the backend
 * uses, because polling faster than that buys nothing.
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

/** Only fetched while the 分时 tab is showing, and only while it can change. */
export function useMarketIntraday(symbol: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.marketIntraday(symbol ?? ''),
    queryFn: () => api.get<MarketIntraday>(`/markets/${symbol}/intraday`),
    enabled: Boolean(symbol) && enabled,
    refetchInterval: 1000 * 60,
    refetchIntervalInBackground: false,
    staleTime: 1000 * 60,
  });
}

/** Company master data: quarterly-frozen at best, so cache it for a day. */
export function useMarketCompany(symbol: string | null) {
  return useQuery({
    queryKey: queryKeys.marketCompany(symbol ?? ''),
    queryFn: () => api.get<MarketCompany>(`/markets/${symbol}/company`),
    enabled: Boolean(symbol),
    staleTime: 1000 * 60 * 60 * 24,
  });
}
