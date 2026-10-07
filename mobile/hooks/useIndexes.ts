/** 基金详情页业绩对比线用的业绩比较基准指数（spec 3.5.3）。 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';
import type { NavRange } from '@/hooks/useFunds';

export type IndexCatalogItem = components['schemas']['IndexCatalogItem'];
export type IndexHistory = components['schemas']['IndexHistoryResponse'];

export const DEFAULT_BENCHMARK = 'sh000300';

/** 目录是服务端写死的清单，任何时候来取都不会变。 */
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

/** 首页行情条：收盘价一个交易日才动一次，缓存 5 分钟已经够新鲜。 */
export function useIndexQuotes() {
  return useQuery({
    queryKey: queryKeys.indexQuotes,
    queryFn: () => api.get<components['schemas']['IndexQuotesResponse']>('/indexes/quotes'),
    staleTime: 1000 * 60 * 5,
  });
}
