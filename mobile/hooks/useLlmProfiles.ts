/**
 * 模型供应商档案：列表、整份保存、切换、以及探测某家有哪些模型。
 *
 * 三个写接口都回同一个 `LlmProfilesResponse`（active + profiles），所以一个
 * query key 就能把三种操作全部失效掉。档案和当前选择按登录用户隔离，
 * 同一个用户在 Web 和 Mobile 共享个人配置。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type LlmProfileItem = components['schemas']['LlmProfileItem'];
export type LlmProfileUpdate = components['schemas']['LlmProfileUpdate'];
export type LlmProfiles = components['schemas']['LlmProfilesResponse'];

export function useLlmProfiles() {
  return useQuery({
    queryKey: queryKeys.llmProfiles,
    queryFn: () => api.get<LlmProfiles>('/agent/llm/profiles'),
    staleTime: 30_000,
  });
}

/** 整份替换：删档案就是"保存一份少了它的列表"，服务端没有单条删除接口。 */
export function useSaveLlmProfiles() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (profiles: LlmProfileUpdate[]) => api.post<LlmProfiles>('/agent/llm/settings', { profiles }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.llmProfiles }),
  });
}

export function useSwitchLlmProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<LlmProfiles>('/agent/llm/switch', { name }),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.llmProfiles }),
  });
}

/**
 * 拿"接口地址 + Key"去问厂家有哪些模型。
 *
 * 用 mutation 而不是 query：这是点一下才做一次的探测，入参（Key）还在边填边变，
 * 缓存它没有意义，失败也該由按钮自己显示。
 */
export function useVendorModels() {
  return useMutation({
    mutationFn: (input: { base_url: string; api_key: string }) =>
      api.post<components['schemas']['LlmModelsResponse']>('/agent/llm/models', input),
  });
}
