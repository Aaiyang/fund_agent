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
export type ChatImportReview = components['schemas']['HoldingImportReview'];
export type ChatPendingAction = NonNullable<components['schemas']['PendingActionResponse']['pending_action']>;
export type ChatImportAction = Exclude<ChatPendingAction, { kind: 'fund_selection' | 'human_question' }>;
export type ChatImportDecision = components['schemas']['HoldingImportDecisionResponse'];
export type AgentRunContinuation = components['schemas']['AgentRunContinuation'];
type PendingResponse = components['schemas']['PendingActionResponse'];
type ContinuedResponse = components['schemas']['ChatResponse'];

export function useUploadChatScreenshots() {
  const client = useQueryClient();
  return useMutation({
    // 会话按调用传：附件是在"发送"那一刻上传的，那时可能刚为这条消息新建会话，
    // 挂在 hook 上的还是渲染时那份 null。
    mutationFn: async (input: { sessionId: string; accountId?: number; images: PickedImage[] }): Promise<ChatImportAccepted> => {
      const token = await ensureSessionToken(client, input.sessionId);
      const form = new FormData();
      for (const image of input.images) {
        if (Platform.OS === 'web') {
          // Web 上选到的是一张 blob: 图，multipart 的 name 得在这里给，
          // 否则后端收到的文件名是 blob。
          const blob = await (await fetch(image.uri)).blob();
          form.append('files', blob, image.name);
        } else {
          form.append('files', { uri: image.uri, name: image.name, type: image.mimeType } as unknown as Blob);
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

/** 刷新或重连后把还挂在半路的复核卡片捞回来（草稿内容会跟着最新一次识别刷新). */
export function usePendingChatAction(sessionId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: [...queryKeys.chatPendingAction, sessionId],
    enabled: Boolean(sessionId),
    refetchInterval: (query) => query.state.data?.pending_action?.kind === 'holding_import_processing' ? 3000 : false,
    queryFn: async () => {
      const token = await ensureSessionToken(client, sessionId as string);
      return request<PendingResponse>('/chatbot/pending-action', { bearer: token });
    },
  });
}

export function useDecideChatImport(sessionId: string | null) {
  const client = useQueryClient();
  return useMutation({
    onMutate: () => ({ sessionId }),
    mutationFn: async (input: {
      importId: string;
      decision: 'confirm' | 'cancel';
      interruptId: string;
      reviewDigest?: string;
    }): Promise<ChatImportDecision> => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      return request<ChatImportDecision>(`/chatbot/holding-imports/${input.importId}/decision`, {
        method: 'POST',
        bearer: token,
        body: { decision: input.decision, interrupt_id: input.interruptId, review_digest: input.reviewDigest },
      });
    },
    onSuccess: (_result, _input, context) => {
      const active = context?.sessionId;
      if (!active) return;
      void client.invalidateQueries({ queryKey: queryKeys.agentMessages(active) });
      void client.invalidateQueries({ queryKey: queryKeys.chatImports });
      void client.invalidateQueries({ queryKey: [...queryKeys.chatPendingAction, active] });
      void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
      void client.invalidateQueries({ queryKey: queryKeys.portfolio });
      void client.invalidateQueries({ queryKey: queryKeys.transactionsAll });
    },
  });
}

/** 识别结束或选择账户后恢复子图；返回下一张卡，不确认持仓。 */
export function useAdvanceChatImport(sessionId: string | null) {
  const client = useQueryClient();
  return useMutation({
    onMutate: () => ({ sessionId }),
    mutationFn: async (input: { importId: string; interruptId: string; accountId?: number }): Promise<components['schemas']['ChatResponse']> => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      const step = input.accountId === undefined ? 'continue' : 'account';
      return request(`/chatbot/holding-imports/${input.importId}/${step}`, {
        method: 'POST', bearer: token,
        body: { interrupt_id: input.interruptId, ...(input.accountId === undefined ? {} : { account_id: input.accountId }) },
      });
    },
    onSuccess: (_result, _input, context) => {
      const active = context?.sessionId;
      if (!active) return;
      void client.invalidateQueries({ queryKey: [...queryKeys.chatPendingAction, active] });
      void client.invalidateQueries({ queryKey: queryKeys.agentMessages(active) });
    },
  });
}

/** 当前会话的识别状态；只在子图等待时轮询。 */
export function useChatImportProgress(sessionId: string | null, importId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: [...queryKeys.chatImport(importId), sessionId],
    enabled: Boolean(sessionId && importId),
    queryFn: async () => {
      const token = await ensureSessionToken(client, sessionId as string);
      return request<components['schemas']['ImportDetailResponse']>(`/chatbot/holding-imports/${importId}`, { bearer: token });
    },
    refetchInterval: (query) => !query.state.data || ['UPLOADED', 'PARSING'].includes(query.state.data.import_batch.status) ? 3000 : false,
  });
}

/** 按会话令牌恢复基金选择，候选和中断由服务端核验。 */
export function useSelectAnalysisFund(sessionId: string | null) {
  const client = useQueryClient();
  return useMutation({
    onMutate: () => ({ sessionId }),
    mutationFn: async (input: { interruptId: string; fundCode?: string }): Promise<components['schemas']['ChatResponse']> => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      return request('/chatbot/fund-selection/decision', {
        method: 'POST', bearer: token,
        body: { interrupt_id: input.interruptId, decision: input.fundCode ? 'select' : 'cancel', fund_code: input.fundCode },
      });
    },
    onSuccess: (_result, _input, context) => {
      const active = context?.sessionId;
      if (!active) return;
      void client.invalidateQueries({ queryKey: [...queryKeys.chatPendingAction, active] });
      void client.invalidateQueries({ queryKey: queryKeys.agentMessages(active) });
      void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
    },
  });
}

/** 继续服务端checkpoint中的原任务，不重发基金选择或用户问题。 */
export function useContinueAgentRun(sessionId: string | null) {
  const client = useQueryClient();
  return useMutation({
    onMutate: () => ({ sessionId }),
    mutationFn: async (input: { turnId: string }): Promise<ContinuedResponse> => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      return request('/chatbot/continue', { method: 'POST', bearer: token, body: { turn_id: input.turnId } });
    },
    onSuccess: (_result, _input, context) => {
      const active = context?.sessionId;
      if (!active) return;
      void client.invalidateQueries({ queryKey: [...queryKeys.chatPendingAction, active] });
      void client.invalidateQueries({ queryKey: queryKeys.agentMessages(active) });
      void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
    },
  });
}
