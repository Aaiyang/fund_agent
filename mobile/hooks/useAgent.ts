/**
 * 会话与历史消息的读写。
 *
 * 三条约定决定了这里的形状：
 * 1. 聊天接口认会话令牌（`/auth/session` 签出来的那种），所以每个请求都要显式带
 *    `bearer`，见 `api/chatSessions.ts`；
 * 2. 上下文由服务端的 LangGraph 检查点按会话线程记着，客户端只发当前这一句话，
 *    从不重发整段历史；
 * 3. 会话标题是服务端在回答之后异步补的，所以每次答完要回头失效一次会话列表。
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { sessionToken, rememberSession, rememberSessions, forgetSession, type ChatSession } from '@/api/chatSessions';
import { request } from '@/api/client';
import { queryKeys } from '@/api/queries';
import type { components } from '@/api/schema';

export type ChatMessage = components['schemas']['Message'];
export type ChatResponse = components['schemas']['ChatResponse'];

async function fetchSessions(): Promise<ChatSession[]> {
  const sessions = await request<ChatSession[]>('/auth/sessions');
  // 这份响应里每条会话都带着刚签发的新令牌，登记下来聊天才有的用。
  rememberSessions(sessions);
  return sessions;
}

export function useAgentSessions() {
  return useQuery({ queryKey: queryKeys.agentSessions, queryFn: fetchSessions });
}

/** 令牌缺失时（冷启动、或在别的页面上第一次打开这条会话）现拉一次列表补上。 */
export async function ensureSessionToken(client: QueryClient, sessionId: string): Promise<string> {
  const known = sessionToken(sessionId);
  if (known) return known;
  const sessions = await client.fetchQuery({ queryKey: queryKeys.agentSessions, queryFn: fetchSessions });
  rememberSessions(sessions);
  const fresh = sessionToken(sessionId);
  if (!fresh) throw new Error('这条会话已经不在了，换一个或新建一个');
  return fresh;
}

export function useCreateAgentSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<ChatSession>('/auth/session', { method: 'POST' }),
    onSuccess: (session) => {
      rememberSession(session);
      void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
    },
  });
}

/**
 * 删会话。
 *
 * 路径上的 session_id 必须和令牌里的对得上，否则服务端直接 403，
 * 所以这里用的始终是那条会话自己的令牌。
 */
export function useDeleteAgentSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const token = await ensureSessionToken(client, sessionId);
      return request<void>(`/auth/session/${sessionId}`, { method: 'DELETE', bearer: token });
    },
    onSuccess: (_data, sessionId) => {
      forgetSession(sessionId);
      void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
      void client.invalidateQueries({ queryKey: queryKeys.agentMessages(sessionId) });
    },
  });
}

export function useAgentMessages(sessionId: string | null) {
  const client = useQueryClient();
  return useQuery({
    queryKey: queryKeys.agentMessages(sessionId),
    enabled: Boolean(sessionId),
    // 打开会话即是一次读历史，缓存过期后不自动重取：正在聊的对话被后台刷新
    // 会把本地叠加的那条覆盖掉。
    staleTime: Infinity,
    queryFn: async () => {
      if (!sessionId) throw new Error('还没有选中会话');
      const token = await ensureSessionToken(client, sessionId);
      return request<ChatResponse>('/chatbot/messages', { bearer: token });
    },
  });
}

/**
 * 清空某条会话的消息，会话本身留着（和 Web 端一个口径）。
 *
 * session_id 走 mutation 的入参而不是构造参数：会话列表页要为每一行各发起一次，
 * 在 map 里调 hook 是非法的。
 */
export function useClearAgentMessages() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const token = await ensureSessionToken(client, sessionId);
      return request<{ message: string }>('/chatbot/messages', { method: 'DELETE', bearer: token });
    },
    onSuccess: (_data, sessionId) => {
      void client.invalidateQueries({ queryKey: queryKeys.agentMessages(sessionId) });
    },
  });
}
