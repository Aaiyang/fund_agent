/**
 * 一次对话的客户端状态机：历史读服务端、正在生成的那条读本地。
 *
 * 界面看到的是 `turns`：已经落进 LangGraph 检查点的历史，加上本地这一轮
 * （提问 + 正在流式写入的回答）。本轮结束后再向服务端重取一次历史，
 * 本地那份就撤掉 —— 让服务端始终是唯一的真源，两边不会各存一份答案。
 */

import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { streamChatMessage, ChatStreamError } from '@/api/chatStream';
import { queryKeys } from '@/api/queries';
import { ensureSessionToken, useAgentMessages } from '@/hooks/useAgent';
import type { ChatPendingAction } from '@/hooks/useChatImport';
import type { ChatMessage } from '@/hooks/useAgent';

export type ChatTurn = ChatMessage & {
  /** 只有本地这一轮的那两条有值：正在生成 / 已被用户停止 / 服务端报错。 */
  state?: 'streaming' | 'stopped' | 'failed';
  /** state 为 failed 时给界面显示的失败原因。 */
  error?: string;
};

type Overlay = {
  sessionId: string;
  question: string;
  answer: string;
  state: ChatTurn['state'];
  error?: string;
  /** 这一轮带出去的截图批次，失败后「重试」要按同一批重发。 */
  importIds: string[];
};

export function useAgentChat(input: {
  sessionId: string | null;
  /** 没有当前会话时先建一条，返回可用的 session_id。 */
  ensureSession: () => Promise<string>;
}) {
  const { sessionId, ensureSession } = input;
  const client = useQueryClient();
  const history = useAgentMessages(sessionId);
  // useQuery 的结果对象每次渲染都是新的，依赖里只放解构出来的 refetch。
  const { refetch: refetchHistory } = history;
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  // 流里的识别、选账户和复核卡片按会话隔离，恢复后以服务端状态为准。
  const [pending, setPending] = useState<{ sessionId: string; action: ChatPendingAction | null } | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const send = useCallback(
    async (text: string, importIds: string[] = []) => {
      if (controller.current) throw new Error('上一条还在生成中');
      const content = text.trim();
      if (!content) throw new Error('要说点什么');

      const active = await ensureSession();
      const token = await ensureSessionToken(client, active);
      setOverlay({ sessionId: active, question: content, answer: '', state: 'streaming', importIds });
      const abort = new AbortController();
      controller.current = abort;

      let failed: string | null = null;
      let stopped = false;
      try {
        await streamChatMessage({
          token,
          text: content,
          holdingImportIds: importIds,
          signal: abort.signal,
          onDelta: (delta) => setOverlay((prev) => (
            prev?.sessionId === active && !abort.signal.aborted
              ? { ...prev, answer: prev.answer + delta }
              : prev
          )),
          onPendingAction: (action) => setPending((prev) => abort.signal.aborted ? prev : { sessionId: active, action }),
        });
      } catch (error) {
        if ((error as Error).name === 'AbortError') stopped = true;
        else if (error instanceof ChatStreamError) failed = error.message;
        else failed = (error as Error).message || '这条回答没生成出来';
      } finally {
        controller.current = null;
        void client.invalidateQueries({ queryKey: [...queryKeys.chatPendingAction, active] });
      }

      // 停止与正常收尾都以服务端的历史为准；失败时保留本地这条，好让"重试"还在。
      if (!failed) {
        setOverlay(null);
        await refetchHistory();
      } else {
        setOverlay((prev) => (prev ? { ...prev, state: 'failed', error: failed ?? undefined } : prev));
      }
      if (!failed && !stopped) {
        // 会话标题是服务端在回答之后异步补的，回头失效一次才追得上。
        void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
      }
    },
    [client, ensureSession, refetchHistory],
  );

  const stop = useCallback(() => controller.current?.abort(), []);
  const setReview = useCallback((action: ChatPendingAction | null) => {
    if (sessionId) setPending({ sessionId, action });
  }, [sessionId]);

  // 本地这一轮属于哪条会话：跳到会话列表换了一条，半截的旧回答不能跟过来。
  const current = overlay?.sessionId === sessionId ? overlay : null;

  /** 失败那条回答还在本地叠着，重试就是撤掉它再发一遍同一个问题。 */
  const retry = useCallback(() => {
    const question = current?.state === 'failed' ? current.question : null;
    if (!question) return;
    setOverlay(null);
    void send(question, current?.importIds ?? []);
  }, [current, send]);

  const turns: ChatTurn[] = [
    ...(history.data?.messages ?? []).filter((message) => message.role !== 'system'),
    ...(current
      ? [
          { role: 'user' as const, content: current.question },
          { role: 'assistant' as const, content: current.answer, state: current.state, error: current.error },
        ]
      : []),
  ];

  return {
    turns,
    sending: current?.state === 'streaming',
    canRetry: current?.state === 'failed',
    lastFailed: current?.state === 'failed' ? current.error : undefined,
    // 没有会话时历史查询是 disabled，而 react-query v5 里 disabled 的查询
    // 状态恒为 pending —— 直接拿 isPending 当加载态会让页面永远卡在"正在读历史"。
    loadingHistory: Boolean(sessionId) && history.isPending,
    historyError: history.isError && history.data === undefined ? history.error : null,
    retryHistory: () => void history.refetch(),
    review: pending?.sessionId === sessionId ? pending.action : null,
    /** 刷新后要把服务端还挂着的复核卡片灌进来；决策完成后置 null。 */
    setReview,
    history,
    send,
    stop,
    retry,
    /** 清空后要能把半截的本地状态丢掉。 */
    reset: () => {
      controller.current?.abort();
      setOverlay(null);
      setPending(null);
    },
  };
}
