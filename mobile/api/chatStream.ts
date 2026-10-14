/**
 * 聊天接口的流式读取：POST + Server-Sent Events。
 *
 * 为什么不用 fetch：后端是 `POST /chatbot/chat/stream` 回 `text/event-stream`，
 * 一帧一帧地吐 `data: {"content": "...", "done": false}\n\n`。React Native 自带的
 * fetch 把整个响应体当字符串读完才交回来（没有可用的 response.body 流），
 * 那样就没有"边生成边显示"了。XMLHttpRequest 的 onprogress 在原生和 Web 上都会
 * 随分块推进，responseText 也逐渐变长，是目前唯一两端都靠得住的路子。
 *
 * 停止生成用 AbortSignal，内部对应 xhr.abort()。
 */

import { API_BASE_URL, apiError } from '@/api/client';
import type { ChatPendingAction } from '@/hooks/useChatImport';
import type { AgentRunContinuation } from '@/hooks/useChatImport';

export type AgentResumeAction =
  | { kind: 'fund_selection'; interruptId: string; fundCode?: string }
  | { kind: 'continue'; turnId: string };

export type ChatResearchProgress = {
  kind: 'research_progress';
  run_id: string;
  stage: 'evidence' | 'analysis' | 'review' | 'supplement' | 'revision' | 'report';
  role: 'fundamentals' | 'risk' | 'portfolio' | null;
  status: 'started' | 'completed' | 'partial' | 'failed' | 'skipped';
};

/** 角色调用透出的一行思考摘要：服务端已经截尾并压成单行，界面只给一行空间。 */
export type ChatResearchActivity = {
  kind: 'research_activity';
  run_id: string;
  stage: ChatResearchProgress['stage'];
  role: ChatResearchProgress['role'];
  text: string;
};

/** 后端 StreamResponse 的一帧；OpenAPI 里没有这个类型（流式响应没法描述）。 */
export type ChatStreamChunk = {
  content?: string;
  done?: boolean;
  /** Agent 走到人工复核时会带着它：卡片只能由 HTTP 端点决定，聊天文本不算确认。 */
  pending_action?: ChatPendingAction | null;
  research_progress?: ChatResearchProgress | null;
  research_activity?: ChatResearchActivity | null;
  continuation?: AgentRunContinuation | null;
};

/** 服务端把那一次生成的失败原因放在 done 帧的 content 里回传。 */
export class ChatStreamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatStreamError';
  }
}

const FRAME_SEPARATOR = '\n\n';
const DATA_PREFIX = 'data: ';

/**
 * 从已收到的文本里切出**完整**的帧，末尾没跟分隔符的那一段原样留下。
 *
 * 分块到达的边界完全由网络决定，一帧常被劈成两次；这里只认 `\n\n`，
 * 半截 JSON 永远不会被送去解析。
 */
export function takeFrames(pending: string): { frames: string[]; rest: string } {
  const pieces = pending.split(FRAME_SEPARATOR);
  const rest = pieces.pop() ?? '';
  return { frames: pieces.filter((frame) => frame.trim()), rest };
}

function parseFrame(frame: string, handlers: StreamHandlers): void {
  for (const line of frame.split('\n')) {
    if (!line.startsWith(DATA_PREFIX)) continue;
    const chunk = JSON.parse(line.slice(DATA_PREFIX.length)) as ChatStreamChunk;
    if (chunk.research_progress) handlers.onResearchProgress(chunk.research_progress);
    if (chunk.research_activity) handlers.onResearchActivity(chunk.research_activity);
    if (chunk.pending_action || (chunk.done && Object.prototype.hasOwnProperty.call(chunk, 'pending_action'))) handlers.onPendingAction(chunk.pending_action ?? null);
    if (chunk.done) {
      handlers.onDone();
      if (Object.prototype.hasOwnProperty.call(chunk, 'continuation')) handlers.onContinuation(chunk.continuation ?? null);
      // 正常收尾的 done 帧是空的；带内容的那一帧就是服务端的失败原因。
      if (chunk.content) throw new ChatStreamError(chunk.content);
      continue;
    }
    if (chunk.content) handlers.onDelta(chunk.content);
  }
}

type StreamHandlers = {
  onDelta: (delta: string) => void;
  onPendingAction: (review: ChatPendingAction | null) => void;
  onResearchProgress: (progress: ChatResearchProgress) => void;
  onResearchActivity: (activity: ChatResearchActivity) => void;
  onContinuation: (continuation: AgentRunContinuation | null) => void;
  onDone: () => void;
};

type StreamInput = {
  token: string;
  signal: AbortSignal;
  onDelta: (delta: string) => void;
  onPendingAction?: (review: ChatPendingAction | null) => void;
  onResearchProgress?: (progress: ChatResearchProgress) => void;
  onResearchActivity?: (activity: ChatResearchActivity) => void;
  onContinuation?: (continuation: AgentRunContinuation | null) => void;
};

/**
 * 把一句话发给当前会话，边收边回调增量。
 *
 * 抛错的情形：HTTP 非 2xx（鉴权失效、限流）、服务端 done 帧带了错误文本、
 * 以及连接自己断了。调用方 AbortSignal 时 promise 以 AbortError 拒绝。
 */
export function streamChatMessage(input: StreamInput & {
  text: string;
  /** 这一条消息带上的截图批次；后端会校验它们确实属于这个会话。 */
  holdingImportIds?: string[];
  researchFollowupId?: string;
  /** 选基金面板直接授权的研究对象与成本档位。 */
  researchFundCodes?: string[];
  researchStrategy?: 'single' | 'multi_role';
}): Promise<void> {
  const { text, holdingImportIds = [] } = input;
  return streamRequest(input, '/chatbot/chat/stream', {
    messages: [{ role: 'user', content: text }],
    ...(holdingImportIds.length ? { holding_import_ids: holdingImportIds } : {}),
    ...(input.researchFollowupId ? { research_followup_id: input.researchFollowupId } : {}),
    ...(input.researchFundCodes?.length ? { research_fund_codes: input.researchFundCodes, research_strategy: input.researchStrategy ?? 'single' } : {}),
  });
}

/** 人工选择和检查点继续使用相同的 SSE 传输，不伪造一条新的用户提问。 */
export function streamAgentResume(input: StreamInput & { action: AgentResumeAction }): Promise<void> {
  const { action } = input;
  return action.kind === 'fund_selection'
    ? streamRequest(input, '/chatbot/fund-selection/decision/stream', {
        interrupt_id: action.interruptId, decision: action.fundCode ? 'select' : 'cancel', fund_code: action.fundCode,
      })
    : streamRequest(input, '/chatbot/continue/stream', { turn_id: action.turnId });
}

function streamRequest(input: StreamInput, path: string, body: unknown): Promise<void> {
  const { token, signal } = input;
  let done = false;
  const handlers: StreamHandlers = {
    onDelta: input.onDelta,
    onPendingAction: input.onPendingAction ?? (() => undefined),
    onResearchProgress: input.onResearchProgress ?? (() => undefined),
    onResearchActivity: input.onResearchActivity ?? (() => undefined),
    onContinuation: input.onContinuation ?? (() => undefined),
    onDone: () => { done = true; },
  };

  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}${path}`);
    xhr.responseType = 'text';
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('Accept', 'text/event-stream');

    // 分块边界由网络决定，所以按"已消费的字符数"记进度，只处理已经收完的帧。
    let consumed = 0;
    const drain = (final: boolean) => {
      const body = xhr.responseText ?? '';
      const pending = body.slice(consumed);
      const { frames, rest } = takeFrames(pending);
      consumed += pending.length - rest.length;
      if (final && rest.trim()) {
        // 响应已经结束，末尾那一段也完整了，当最后一帧处理。
        consumed += rest.length;
        frames.push(rest);
      }
      for (const frame of frames) parseFrame(frame, handlers);
    };

    const onAbort = () => xhr.abort();
    let settled = false;
    const cleanup = () => signal.removeEventListener('abort', onAbort);
    const fail = (error: unknown, stop = false) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
      // 先拒绝原始错误，abort 回调不能将它替换成“用户停止生成”。
      if (stop) xhr.abort();
    };

    xhr.onprogress = () => {
      if (settled || (xhr.status !== 0 && (xhr.status < 200 || xhr.status >= 300))) return;
      try {
        drain(false);
      } catch (error) {
        // 异步事件回调抛出的异常不会被 Promise 自动捕获。
        fail(error, true);
      }
    };
    xhr.onload = () => {
      if (settled) return;
      if (xhr.status < 200 || xhr.status >= 300) {
        fail(apiError(xhr.status, xhr.statusText ?? '', xhr.responseText ?? ''));
        return;
      }
      try {
        drain(true);
        if (!done) throw new ChatStreamError('连接已结束，研究尚未完成，请查看任务状态并继续原任务。');
        settled = true;
        cleanup();
        resolve();
      } catch (error) {
        fail(error);
      }
    };
    xhr.onerror = () => {
      fail(new Error('连接中断，这条回答没有生成完'));
    };
    xhr.ontimeout = xhr.onerror;
    xhr.onabort = () => {
      fail(abortError());
    };
    signal.addEventListener('abort', onAbort);

    // 只发这一个问题：历史由服务端的 LangGraph 检查点按会话线程记着，
    // 整段重发会重复计入上下文。附件走结构化字段，不塞进正文——工具读的是
    // `holding_import_ids`，写在文本里它拿不到批次号，还会被后端当成编造的导入。
    try {
      xhr.send(JSON.stringify(body));
    } catch (error) {
      fail(error, true);
    }
  });
}

function abortError(): Error {
  const error = new Error('已停止生成');
  error.name = 'AbortError';
  return error;
}
