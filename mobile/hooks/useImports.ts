/**
 * Holding imports: manual entry and screenshot recognition (spec 3.7).
 *
 * A screenshot batch is accepted with 202 + import_id and parsed by a worker;
 * the detail query polls while the batch is still UPLOADED/PARSING (spec 7.9).
 * Nothing reaches the real holdings until `confirm`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Platform } from 'react-native';

import { api, API_BASE_URL, request } from '@/api/client';
import { queryKeys } from '@/api/queries';
import { loadTokens } from '@/api/tokenStore';
import type { components } from '@/api/schema';

export type ImportDetail = components['schemas']['ImportDetail'];
export type ImportItem = components['schemas']['ImportItemOut'];
export type ManualPosition = components['schemas']['ManualPositionInput'];
export type PickedImage = { uri: string; name: string; mimeType: string };

const POLLING_STATUSES = new Set(['UPLOADED', 'PARSING']);

export function useImportHistory() {
  return useQuery({
    queryKey: [...queryKeys.imports, 'history'],
    queryFn: () => api.get<components['schemas']['ImportHistoryResponse']>('/holding-imports/history'),
  });
}

export function useImportDetail(importId: string | null) {
  return useQuery({
    queryKey: queryKeys.importDetail(importId ?? ''),
    queryFn: () =>
      request<components['schemas']['ImportDetailResponse']>(`/holding-imports/${importId}`).then(
        (response) => response.import_batch,
      ),
    enabled: Boolean(importId),
    refetchInterval: (query) => (POLLING_STATUSES.has(query.state.data?.status ?? '') ? 2000 : false),
  });
}

export function useCreateManualImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: components['schemas']['ManualImportRequest']) =>
      request<components['schemas']['ImportDetailResponse']>('/holding-imports/manual', {
        method: 'POST',
        body: payload,
      }).then((response) => response.import_batch),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.imports }),
  });
}

/**
 * Upload 1..N screenshots. Kept as an explicit call rather than `api.post`
 * because the multipart boundary must be set by the runtime.
 */
export async function uploadScreenshots(params: {
  accountId: number;
  images: PickedImage[];
}): Promise<components['schemas']['ScreenshotImportAccepted']> {
  const form = new FormData();
  for (const image of params.images) {
    if (Platform.OS === 'web') {
      const blob = await (await fetch(image.uri)).blob();
      form.append('files', blob, image.name);
    } else {
      form.append('files', image as unknown as Blob);
    }
  }

  const query = new URLSearchParams({ account_id: String(params.accountId) });
  const { access } = await loadTokens();

  const response = await fetch(`${API_BASE_URL}/holding-imports/screenshots?${query}`, {
    method: 'POST',
    headers: access ? { Authorization: `Bearer ${access}` } : undefined,
    body: form,
  });
  if (!response.ok) {
    throw new Error(`上传失败 (${response.status})`);
  }
  return (await response.json()) as components['schemas']['ScreenshotImportAccepted'];
}

export function useUploadScreenshots() {
  const client = useQueryClient();
  return useMutation({ mutationFn: uploadScreenshots, onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.imports }) });
}

export function useUpdateImportItem() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      importId,
      itemId,
      ...payload
    }: { importId: string; itemId: number } & components['schemas']['ImportItemUpdateRequest']) =>
      api.patch<ImportItem>(`/holding-imports/${importId}/items/${itemId}`, payload),
    onSuccess: (_data, variables) =>
      client.invalidateQueries({ queryKey: queryKeys.importDetail(variables.importId) }),
  });
}

/** The only path that writes real holdings (spec 3.7). */
export function useConfirmImport(importId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<components['schemas']['ImportConfirmResponse']>(`/holding-imports/${importId}/confirm`, {
        method: 'POST',
      }),
    onSuccess: async () => {
      await Promise.all([
        importId ? client.invalidateQueries({ queryKey: queryKeys.importDetail(importId) }) : Promise.resolve(),
        client.invalidateQueries({ queryKey: queryKeys.portfolio }),
        client.invalidateQueries({ queryKey: queryKeys.transactionsAll }),
        client.invalidateQueries({ queryKey: queryKeys.watchlist }),
      ]);
    },
  });
}

export function useDeleteImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (importId: string) => api.del(`/holding-imports/${importId}`),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.imports }),
  });
}
