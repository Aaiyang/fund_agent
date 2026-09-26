/** Benchmark indexes for the fund-detail comparison line (spec 3.5.3). */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';
import type { NavRange } from '@/hooks/useFunds';

export type IndexCatalogItem = components['schemas']['IndexCatalogItem'];
export type IndexHistory = components['schemas']['IndexHistoryResponse'];

export const DEFAULT_BENCHMARK = 'sh000300';

/** The catalog is a fixed server-side list; it never changes between visits. */
export function useIndexCatalog() {
  return useQuery({
    queryKey: queryKeys.indexes,
    queryFn: () => api.get<components['schemas']['IndexCatalogResponse']>('/indexes'),
    staleTime: 1000 * 60 * 60,
  });
}

export function useIndexHistory(indexCode: string | null, range: NavRange) {
  return useQuery({
    queryKey: queryKeys.indexHistory(indexCode ?? '', range),
    queryFn: () =>
      api.get<IndexHistory>(`/indexes/${indexCode}/history`, {
        range,
      }),
    enabled: Boolean(indexCode),
  });
}

/** Home-page market tape: closes move once a day, so 5 minutes is fresh enough. */
export function useIndexQuotes() {
  return useQuery({
    queryKey: queryKeys.indexQuotes,
    queryFn: () => api.get<components['schemas']['IndexQuotesResponse']>('/indexes/quotes'),
    staleTime: 1000 * 60 * 5,
  });
}
