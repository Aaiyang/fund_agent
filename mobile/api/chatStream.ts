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
import type { ChatImportReview } from '@/hooks/useChatImport';

/** 后端 StreamResponse 的一帧；OpenAPI 里没有这个类型（流式响应没法描述）。 */
export type ChatStreamChunk = {
  content?: string;
  done?: boolean;
  /** Agent 走到人工复核时会带着它：卡片只能由 HTTP 端点决定，聊天文本不算确认。 */
  pending_action?: ChatImportReview | null;
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
    if (chunk.pending_action) handlers.onPendingAction(chunk.pending_action);
    if (chunk.done) {
      // 正常收尾的 done 帧是空的；带内容的那一帧就是服务端的失败原因。
      if (chunk.content) throw new ChatStreamError(chunk.content);
      continue;
    }
    if (chunk.content) handlers.onDelta(chunk.content);
  }
}

type StreamHandlers = {
  onDelta: (delta: string) => void;
  onPendingAction: (review: ChatImportReview) => void;
};

/**
 * 把一句话发给当前会话，边收边回调增量。
 *
 * 抛错的情形：HTTP 非 2xx（鉴权失效、限流）、服务端 done 帧带了错误文本、
 * 以及连接自己断了。调用方 AbortSignal 时 promise 以 AbortError 拒绝。
 */
export function streamChatMessage(input: {
  token: string;
  text: string;
  /** 这一条消息带上的截图批次；后端会校验它们确实属于这个会话。 */
  holdingImportIds?: string[];
  signal: AbortSignal;
  onDelta: (delta: string) => void;
  onPendingAction?: (review: ChatImportReview) => void;
}): Promise<void> {
  const { token, text, holdingImportIds = [], signal } = input;
  const handlers: StreamHandlers = {
    onDelta: input.onDelta,
    onPendingAction: input.onPendingAction ?? (() => undefined),
  };

  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/chatbot/chat/stream`);
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
    signal.addEventListener('abort', onAbort);

    xhr.onprogress = () => drain(false);
    xhr.onload = () => {
      signal.removeEventListener('abort', onAbort);
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(apiError(xhr.status, xhr.statusText ?? '', xhr.responseText ?? ''));
        return;
      }
      try {
        drain(true);
        resolve();
      } catch (error) {
        reject(error);
      }
    };
    xhr.onerror = () => {
      signal.removeEventListener('abort', onAbort);
      reject(new Error('连接中断，这条回答没有生成完'));
    };
    xhr.ontimeout = xhr.onerror;
    xhr.onabort = () => {
      signal.removeEventListener('abort', onAbort);
      reject(abortError());
    };

    // 只发这一个问题：历史由服务端的 LangGraph 检查点按会话线程记着，
    // 整段重发会重复计入上下文。附件走结构化字段，不塞进正文——工具读的是
    // `holding_import_ids`，写在文本里它拿不到批次号，还会被后端当成编造的导入。
    xhr.send(
      JSON.stringify({
        messages: [{ role: 'user', content: text }],
        ...(holdingImportIds.length ? { holding_import_ids: holdingImportIds } : {}),
      }),
    );
  });
}

function abortError(): Error {
  const error = new Error('已停止生成');
  error.name = 'AbortError';
  return error;
}
