/**
 * 盘中估值：一次请求算一批基金的「预估涨幅」.
 *
 * 估值是服务端现算的派生指标（不落库），所以按代码集合缓存 30 秒：同一屏里反复
 * 挂载不会重复驱动上游，切走再回来又能拿到新的。
 */

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type FundEstimate = components['schemas']['FundEstimateItem'];
export type ValuationEstimates = components['schemas']['ValuationEstimatesResponse'];

export function useValuationEstimates(codes: string[]) {
  // 查询键用排序后的代码串：数组每次渲染都是新的，直接进键会让缓存永远命中不了。
  const key = [...codes].sort().join(',');
  return useQuery({
    queryKey: [...queryKeys.valuations, key],
    queryFn: () => api.post<ValuationEstimates>('/valuation/estimates', { codes }),
    enabled: codes.length > 0,
    staleTime: 30_000,
  });
}

/** 按基金代码索引估值结果，供表格逐行取用. */
export function estimatesByCode(items?: FundEstimate[]): Record<string, FundEstimate> {
  return Object.fromEntries((items ?? []).map((item) => [item.fund_code, item]));
}

/**
 * 没有数时要说清是哪一种「没有」.
 *
 * QDII 的空白是口径决定（它的净值按境外收盘出，盘中给数等于预测今晚），不是数据
 * 坏了；把它和"接口还没接"混成一个 `未接入`，会让人以为页面出了问题。
 */
export function estimateHint(estimate?: FundEstimate): string {
  if (!estimate) return '';
  if (estimate.available) return '';
  if (estimate.reason === 'cross_timezone_calendar') return '境外收盘后';
  if (estimate.reason === 'thin_disclosure') return '披露太稀';
  if (estimate.reason === 'no_quotable_basis') return '无估值依据';
  return '未接入';
}
