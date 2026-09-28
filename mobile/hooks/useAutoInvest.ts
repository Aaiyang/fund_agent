/** 定投计划: the schedule itself and the installments it settles (spec 3.8). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type AutoInvestPlan = components['schemas']['AutoInvestPlanItem'];

/**
 * Listing plans is what settles them: the backend writes every installment
 * that came due since the last read, so a plan stays current even when no
 * worker process is running.
 */
export function useAutoInvestPlans(accountId: number | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: [...queryKeys.autoInvest, accountId] as const,
    // Reading settles the plans, so the money views have to be refreshed from
    // inside the fetch — doing it during render would fire on every repaint.
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
