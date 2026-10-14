/**
 * 一次对话的客户端状态机：历史读服务端、正在生成的那条读本地。
 *
 * 界面看到的是 `turns`：已经落进 LangGraph 检查点的历史，加上本地这一轮
 * （提问 + 正在流式写入的回答）。本轮结束后再向服务端重取一次历史，
 * 确认历史包含完整回答后才撤掉本地那份，避免刷新失败或延迟时丢失正文。
 */

import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { streamChatMessage, streamAgentResume, ChatStreamError } from '@/api/chatStream';
import type { AgentResumeAction } from '@/api/chatStream';
import type { ClientResearch } from '@/utils/fundPicker';
import { queryKeys } from '@/api/queries';
import { ensureSessionToken, fetchAgentMessages, useAgentMessages } from '@/hooks/useAgent';
import type { ChatPendingAction } from '@/hooks/useChatImport';
import type { ChatMessage } from '@/hooks/useAgent';
import type { ChatResearchProgress } from '@/api/chatStream';
import { describeResearchProgress, mergeResearchProgress } from '@/utils/researchProgress';

export type ChatTurn = ChatMessage & {
  /** 仅本地这一轮有值；完整历史接管后撤掉。 */
  state?: 'streaming' | 'completed' | 'stopped' | 'failed';
  /** state 为 failed 时给界面显示的失败原因。 */
  error?: string;
  researchProgress?: string;
};

type Overlay = {
  runId: symbol;
  baseCount: number;
  sessionId: string;
  question: string;
  answer: string;
  state: ChatTurn['state'];
  error?: string;
  /** 这一轮带出去的截图批次，失败后「重试」要按同一批重发。 */
  importIds: string[];
  researchFollowupId?: string;
  /** 重试要按同一种授权重发，否则按钮点第二次会变成普通提问。 */
  research?: ClientResearch;
  resumeAction?: AgentResumeAction;
  progress: ChatResearchProgress[];
};

export function useAgentChat(input: {
  sessionId: string | null;
  /** 没有当前会话时先建一条，返回可用的 session_id。 */
  ensureSession: () => Promise<string>;
}) {
  const { sessionId, ensureSession } = input;
  const client = useQueryClient();
  const history = useAgentMessages(sessionId);
  const [overlay, setOverlay] = useState<Overlay | null>(null);
  // 流里的识别、选账户和复核卡片按会话隔离，恢复后以服务端状态为准。
  const [pending, setPending] = useState<{ sessionId: string; action: ChatPendingAction | null } | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(
    async (text: string, importIds: string[] = [], researchFollowupId?: string, resumeAction?: AgentResumeAction, research?: ClientResearch) => {
      if (controller.current) throw new Error('上一条还在生成中');
      const content = text.trim();
      if (!content && !resumeAction) throw new Error('要说点什么');

      const abort = new AbortController();
      const runId = Symbol('chat-run');
      controller.current = abort;
      let active: string;
      let token: string;
      try {
        active = resumeAction ? sessionId ?? '' : await ensureSession();
        if (!active) throw new Error('还没有选中会话');
        token = await ensureSessionToken(client, active);
      } catch (error) {
        controller.current = null;
        throw error;
      }
      const baseCount = sessionId === active ? (history.data?.messages ?? []).filter((message) => message.role !== 'system').length : 0;
      setOverlay({ runId, baseCount, sessionId: active, question: content, answer: '', state: 'streaming', importIds, researchFollowupId, research, resumeAction, progress: [] });

      let failed: string | null = null;
      let stopped = false;
      let answer = '';
      let receiving = true;
      try {
        const handlers = {
          token,
          signal: abort.signal,
          onDelta: (delta: string) => {
            if (!receiving || abort.signal.aborted) return;
            answer += delta;
            setOverlay((prev) => (
              prev?.runId === runId
                ? { ...prev, answer: prev.answer + delta }
                : prev
            ));
          },
          onPendingAction: (action: ChatPendingAction | null) => setPending((prev) => !receiving || abort.signal.aborted ? prev : { sessionId: active, action }),
          onResearchProgress: (progress: ChatResearchProgress) => setOverlay((prev) => (
            receiving && prev?.runId === runId && !abort.signal.aborted
              ? { ...prev, progress: mergeResearchProgress(prev.progress, progress) }
              : prev
          )),
        };
        if (resumeAction) await streamAgentResume({ ...handlers, action: resumeAction });
        else await streamChatMessage({ ...handlers, text: content, holdingImportIds: importIds, researchFollowupId, researchFundCodes: research?.codes, researchStrategy: research?.strategy });
      } catch (error) {
        if ((error as Error).name === 'AbortError') stopped = true;
        else if (error instanceof ChatStreamError) failed = error.message;
        else failed = (error as Error).message || '这条回答没生成出来';
      } finally {
        receiving = false;
        controller.current = null;
        void client.invalidateQueries({ queryKey: [...queryKeys.chatPendingAction, active] });
      }

      // 完整历史成功返回前保留流式正文；刷新失败不会清空已经生成的报告。
      if (!failed) {
        setOverlay((prev) => prev?.runId === runId ? { ...prev, state: stopped ? 'stopped' : 'completed' } : prev);
        try {
          const refreshed = await client.fetchQuery({
            queryKey: queryKeys.agentMessages(active),
            queryFn: () => fetchAgentMessages(client, active),
            staleTime: 0,
          });
          const saved = refreshed.messages.filter((message) => message.role !== 'system');
          if (saved.some((message, index) => index >= baseCount && message.role === 'assistant' && message.content === answer)) {
            setOverlay((prev) => prev?.runId === runId ? null : prev);
          }
        } catch {
          // 网络恢复后读取完整历史会自动替换本地回答。
        }
      } else {
        setOverlay((prev) => (prev?.runId === runId ? { ...prev, state: 'failed', error: failed ?? undefined } : prev));
      }
      if (!failed && !stopped) {
        // 会话标题是服务端在回答之后异步补的，回头失效一次才追得上。
        void client.invalidateQueries({ queryKey: queryKeys.agentSessions });
      }
    },
    [client, ensureSession, history.data, sessionId],
  );

  const send = useCallback((text: string, importIds: string[] = [], researchFollowupId?: string, research?: ClientResearch) =>
    run(text, importIds, researchFollowupId, undefined, research), [run]);
  const resume = useCallback((action: AgentResumeAction) => run('', [], undefined, action), [run]);

  const stop = useCallback(() => controller.current?.abort(), []);
  const setReview = useCallback((action: ChatPendingAction | null) => {
    if (sessionId) setPending({ sessionId, action });
  }, [sessionId]);

  // 本地这一轮属于哪条会话：跳到会话列表换了一条，半截的旧回答不能跟过来。
  const current = overlay?.sessionId === sessionId ? overlay : null;
  const savedMessages = (history.data?.messages ?? []).filter((message) => message.role !== 'system');
  const savedCurrent = current && current.state !== 'streaming' && current.state !== 'failed'
    && savedMessages.some((message, index) => index >= current.baseCount && message.role === 'assistant' && message.content === current.answer);
  useEffect(() => {
    if (savedCurrent) setOverlay((prev) => prev?.runId === current?.runId ? null : prev);
  }, [savedCurrent, current?.runId]);

  /** 失败那条回答还在本地叠着，重试就是撤掉它再发一遍同一个问题。 */
  const retry = useCallback(() => {
    const question = current?.state === 'failed' && !current.resumeAction ? current.question : null;
    if (!question) return;
    setOverlay(null);
    void send(question, current?.importIds ?? [], current?.researchFollowupId, current?.research);
  }, [current, send]);

  const turns: ChatTurn[] = [
    ...(current && !savedCurrent ? savedMessages.slice(0, current.baseCount) : savedMessages),
    ...(current && !savedCurrent
      ? [
          ...(current.question ? [{ role: 'user' as const, content: current.question }] : []),
          { role: 'assistant' as const, content: current.answer, state: current.state, error: current.error, researchProgress: describeResearchProgress(current.progress) },
        ]
      : []),
  ];

  return {
    turns,
    sending: current?.state === 'streaming',
    canRetry: current?.state === 'failed' && !current.resumeAction,
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
    resume,
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
