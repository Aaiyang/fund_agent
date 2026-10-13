/**
 * 板块涨跌榜（`/sectors/board`）：新浪行业/概念板块的当日快照排名.
 *
 * 类型与 `backend/app/schemas/sector.py` 一一对应：`mobile/api/schema.ts` 是
 * openapi 生成物、还没重跑到这批接口，所以这里手写，等下次
 * `npm run generate:api` 之后可以换成 `components['schemas'][...]`。
 *
 * 榜单口径要说清两件事：涨跌幅单位是**百分点**；上游不带报价时间戳，
 * 所以 `fetched_at` 只是服务端抓取的时刻，不能当成"此刻开市中的最新价"。
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';

export type SectorKind = 'industry' | 'concept';
export type SectorOrder = 'desc' | 'asc';
/** 可用于面积/排名的指标，与后端 `SectorBoardSort` 同一份取值。 */
export type SectorSort = 'change_pct' | 'amount';

export type SectorBoardStock = {
  code: string;
  name: string | null;
  change_pct: number | null;
};

export type SectorBoardItem = {
  code: string;
  name: string;
  sector_type: SectorKind;
  stock_count: number | null;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  amount: number | null;
  leading_stock: SectorBoardStock | null;
};

export type SectorBoard = {
  request_id: string;
  source: string;
  sector_type: SectorKind;
  order: SectorOrder;
  sort: SectorSort;
  change_pct_unit: string;
  fetched_at: string;
  quote_time_verified: boolean;
  items: SectorBoardItem[];
  total_available: number;
  warnings: string[];
};

export const SECTOR_KIND_LABELS: Record<SectorKind, string> = { industry: '行业板块', concept: '概念板块' };
export const SECTOR_ORDER_LABELS: Record<SectorOrder, string> = { desc: '涨幅榜', asc: '跌幅榜' };
export const SECTOR_SORT_LABELS: Record<SectorSort, string> = { change_pct: '涨幅', amount: '成交额' };
export const SECTOR_SORTS: SectorSort[] = ['change_pct', 'amount'];

export function useSectorBoard(kind: SectorKind, order: SectorOrder, sort: SectorSort, limit: number) {
  return useQuery({
    queryKey: queryKeys.sectorBoard(kind, order, sort, limit),
    queryFn: () => api.get<SectorBoard>('/sectors/board', { kind, order, sort, limit }),
    refetchInterval: 1000 * 30,
    refetchIntervalInBackground: false,
    staleTime: 1000 * 30,
  });
}
