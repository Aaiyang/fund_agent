/**
 * 聊天里的持仓截图附件。
 *
 * 走的是 `/chatbot/holding-imports/*` 这一组，不是 `/holding-imports/*`：
 * 前者把批次绑到**当前会话**（`chat_session_id`），Agent 的 `get_holding_import`
 * 工具才查得到；用普通导入端点上传的批次对 Agent 不存在。
 * 全部请求都要带会话令牌，用户令牌在这里会被当成"找不到会话"。
 *
 * 确认/取消也不在聊天里：后端明确只允许 `POST .../decision` 这个人工端点写持仓，
 * 普通聊天里说"确认"不会改账本——所以复核卡片上的两个按钮是唯一的落地入口。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Platform } from 'react-native';

import { request } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';
import { ensureSessionToken } from '@/hooks/useAgent';
import type { PickedImage } from '@/hooks/useImports';

export type ChatImportAccepted = components['schemas']['ScreenshotImportAccepted'];
export type ChatImportDetail = components['schemas']['ImportDetailResponse'];
export type ChatImportReview = components['schemas']['HoldingImportReview'];
export type ChatImportDecision = components['schemas']['HoldingImportDecisionResponse'];

/** 还在识别中的状态；其余都是终态，可以停止轮询。 */
const PARSING_STATUSES = new Set(['UPLOADED', 'PARSING']);

export function useUploadChatScreenshots(sessionId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { accountId: number; images: PickedImage[] }): Promise<ChatImportAccepted> => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      const form = new FormData();
      for (const image of input.images) {
        if (Platform.OS === 'web') {
          // Web 上选到的是一张 blob: 图，multipart 的 name 得在这里给，
          // 否则后端收到的文件名是 blob。
          const blob = await (await fetch(image.uri)).blob();
          form.append('files', blob, image.name);
        } else {
          form.append('files', image as unknown as Blob);
        }
      }
      return request<ChatImportAccepted>('/chatbot/holding-imports/screenshots', {
        method: 'POST',
        query: { account_id: input.accountId },
        formData: form,
        bearer: token,
      });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.chatImports }),
  });
}

export function useChatImportDetail(sessionId: string | null, importId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: queryKeys.chatImport(importId),
    enabled: Boolean(sessionId && importId),
    refetchInterval: (query) => (PARSING_STATUSES.has(query.state.data?.import_batch.status ?? '') ? 2000 : false),
    queryFn: async () => {
      const token = await ensureSessionToken(client, sessionId as string);
      return request<ChatImportDetail>(`/chatbot/holding-imports/${importId}`, { bearer: token });
    },
  });
}

/** 刷新或重连后把还挂在半路的复核卡片捞回来（草稿内容会跟着最新一次识别刷新）. */
export function usePendingChatAction(sessionId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: queryKeys.chatPendingAction,
    enabled: Boolean(sessionId),
    queryFn: async () => {
      const token = await ensureSessionToken(client, sessionId as string);
      return request<components['schemas']['PendingActionResponse']>('/chatbot/pending-action', { bearer: token });
    },
  });
}

export function useDecideChatImport(sessionId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      importId: string;
      decision: 'confirm' | 'cancel';
      interruptId: string;
      reviewDigest: string;
    }): Promise<ChatImportDecision> => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      return request<ChatImportDecision>(`/chatbot/holding-imports/${input.importId}/decision`, {
        method: 'POST',
        bearer: token,
        body: { decision: input.decision, interrupt_id: input.interruptId, review_digest: input.reviewDigest },
      });
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.chatImports });
      void client.invalidateQueries({ queryKey: queryKeys.chatPendingAction });
      void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
      void client.invalidateQueries({ queryKey: queryKeys.portfolio });
      void client.invalidateQueries({ queryKey: queryKeys.transactionsAll });
    },
  });
}
