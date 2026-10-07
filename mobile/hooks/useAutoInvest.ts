/** 定投计划：周期扣款排期本身，以及它已结算的各期（spec 3.8）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type AutoInvestPlan = components['schemas']['AutoInvestPlanItem'];

/**
 * 列出计划本身就是结算：后端会把自上次读取以来所有到期的期数补记入账，
 * 这样即便没有后台 worker 进程在跑，计划也不会落后于实际。
 */
export function useAutoInvestPlans(accountId: number | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: [...queryKeys.autoInvest, accountId] as const,
    // 读取顺带结算计划，所以金额相关的视图必须在这次 fetch 内部就刷新
    // ——放到渲染阶段做，每次重绘都会触发一遍。
    queryFn: async () => {
      const data = await api.get<components['schemas']['AutoInvestPlansResponse']>('/auto-invest/plans', {
        account_id: accountId,
      });
      if ((data.settled ?? 0) > 0) {
        await Promise.all([
          client.invalidateQueries({ queryKey: queryKeys.portfolio }),
          client.invalidateQueries({ queryKey: queryKeys.transactionsAll }),
        ]);
      }
      return data;
    },
  });
}

function invalidatePlans(client: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.autoInvest }),
    client.invalidateQueries({ queryKey: queryKeys.portfolio }),
    client.invalidateQueries({ queryKey: queryKeys.transactionsAll }),
  ]);
}

export function useCreatePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: components['schemas']['AutoInvestPlanCreateRequest']) =>
      api.post<AutoInvestPlan>('/auto-invest/plans', payload),
    onSuccess: () => invalidatePlans(client),
  });
}

export function useUpdatePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, ...payload }: { planId: number } & components['schemas']['AutoInvestPlanUpdateRequest']) =>
      api.patch<AutoInvestPlan>(`/auto-invest/plans/${planId}`, payload),
    onSuccess: () => invalidatePlans(client),
  });
}

export function useDeletePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, withOrders }: { planId: number; withOrders: boolean }) =>
      api.del(`/auto-invest/plans/${planId}`, { with_orders: withOrders }),
    onSuccess: () => invalidatePlans(client),
  });
}
