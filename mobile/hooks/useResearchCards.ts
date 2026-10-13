import { useQuery } from '@tanstack/react-query';

import type { ResearchCard } from '../../shared/research-card';
import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import { useAuthStore } from '@/stores/auth';

export type SectorCard = Extract<ResearchCard, { type: 'sector_quote' }>;
export type AllocationCard = Extract<ResearchCard, { type: 'fund_allocation' }>;
export type SectorMarket = {
  requested_date: string; warnings: string[];
  sectors: { sector_code: string; name: string; sector_type: 'industry' | 'concept'; price: number | null;
    change_pct: number | null; quote_time: string | null; stale: boolean; error_code: string | null }[];
};
export type AllocationPreview = {
  captured_at: string; warnings: string[];
  scenario: { available: boolean; reason?: string; assumption?: string; amount?: number;
    before_fund_assets?: number; after_fund_assets?: number; before_target_value?: number; after_target_value?: number;
    before_weight_ratio?: number | null; after_weight_ratio?: number | null };
};

export function useSectorResearchCard(card: SectorCard) {
  return useQuery({
    queryKey: [...queryKeys.sectors, 'market', card.sector_code, card.sector_type],
    queryFn: () => api.get<SectorMarket>('/sectors/market', { keyword: card.sector_code, sector_type: card.sector_type, limit: 1 }),
    staleTime: 15_000,
  });
}

export function useAllocationResearchCard(card: AllocationCard) {
  const userId = useAuthStore((state) => state.user?.id);
  return useQuery({
    queryKey: [...queryKeys.portfolio, 'allocation-preview', userId, card.fund_code, card.account_id, card.action, card.amount],
    queryFn: () => api.get<AllocationPreview>('/portfolio/allocation-preview', {
      fund_code: card.fund_code, account_id: card.account_id, action: card.action, amount: card.amount,
    }),
    enabled: Boolean(userId),
    staleTime: 0,
  });
}
