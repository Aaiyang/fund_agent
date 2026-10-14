/**
 * 对接 FastAPI 后端的 REST 客户端：Bearer 鉴权、单飞（single-flight）令牌
 * 刷新、带类型的错误。各页面从不直接调 fetch。
 *
 * 在真机 Android 上跑时，base URL 必须写局域网地址——`localhost` 指的是
 * 手机自己（spec 11.2）。请在 mobile/.env 里设置 EXPO_PUBLIC_API_BASE_URL。
 */

import { clearTokens, loadTokens, saveTokens } from '@/api/tokenStore';
import type { Tokens } from '@/api/tokenStore';

export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000/api/v1';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type QueryValue = string | number | boolean | undefined | null;

const CHAT_TASK_ERROR_MESSAGES: Record<string, string> = {
  fund_selection_resume_failed_check_status: '基金研究暂时未完成，请查看下方任务状态并继续原任务。',
  fund_selection_resume_timeout_check_status: '基金研究等待超时，请查看下方任务状态并继续原任务。',
  agent_continue_failed_check_status: '继续研究暂时失败，请稍后点击“继续已确认的任务”重试。',
  agent_continue_timeout_check_status: '继续研究等待超时，已保存的任务可稍后重试。',
  fund_selection_interrupt_mismatch: '这次基金选择已失效，请刷新当前会话的任务状态。',
};

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  /** JSON 请求体。 */
  body?: unknown;
  /** application/x-www-form-urlencoded 表单字段，鉴权类接口用这种。 */
  form?: Record<string, string>;
  /** 调用方自己拼好的 multipart 载荷。 */
  formData?: FormData;
  query?: Record<string, QueryValue>;
  /** 公开接口设 false，默认 true。 */
  auth?: boolean;
  /**
   * 用这个令牌当 Bearer，不读也不刷新用户的访问令牌。
   *
   * 聊天域（/chatbot）认的是会话令牌，服务端每次列会话时重新签发、没有配套的
   * refresh 令牌，套进用户令牌那条单飞刷新链里只会刷出一个错的身份。
   * 传 null 表示这个接口不带 Authorization。
   */
  bearer?: string | null;
};

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = `${API_BASE_URL}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

/**
 * 把非 2xx 的响应体翻成 ApiError。
 *
 * 流式那条链用的是 XMLHttpRequest，拿不到 Response 对象，所以错误码的推导
 * 单独出来，两条路径共用同一套 detail/errors 口径。
 */
export function apiError(status: number, statusText: string, bodyText: string): ApiError {
  let code = `http_${status}`;
  let message = statusText || '请求失败';
  try {
    const payload = JSON.parse(bodyText) as { detail?: unknown; errors?: { message?: string }[] };
    if (typeof payload?.detail === 'string') {
      code = payload.detail;
      message = CHAT_TASK_ERROR_MESSAGES[code] ?? payload.detail;
    } else if (Array.isArray(payload?.errors)) {
      message = payload.errors.map((item: { message?: string }) => item.message).join('；');
      code = 'validation_error';
    }
  } catch {
    // 错误响应体不是 JSON：沿用按状态码拼出的错误码。
  }
  return new ApiError(status, code, message);
}

async function parseError(response: Response): Promise<ApiError> {
  return apiError(response.status, response.statusText, await response.text().catch(() => ''));
}

/** 刷新令牌一次只换一回；并发的 401 共享同一次刷新。 */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const { refresh } = await loadTokens();
      if (!refresh) return false;
      const response = await fetch(buildUrl('/auth/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ refresh_token: refresh }).toString(),
      });
      if (!response.ok) {
        await clearTokens();
        return false;
      }
      const payload = (await response.json()) as { access_token: string; refresh_token?: string | null };
      await saveTokens(payload.access_token, payload.refresh_token ?? null);
      return true;
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function headersWith(auth: boolean, token: string | null, extra: Record<string, string> = {}) {
  const headers: Record<string, string> = { Accept: 'application/json', ...extra };
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/**
 * 发起一次请求，遇 401 就刷新一次访问令牌再试。
 *
 * 任何非 2xx 响应都抛 ApiError，调用方可以按状态码分支处理。
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, form, formData, query, auth = true, bearer } = options;
  const url = buildUrl(path, query);
  // bearer 一旦指定就走显式令牌，缺省才去读用户的访问令牌。
  const tokens: Tokens = bearer === undefined ? await loadTokens() : { access: bearer, refresh: null };

  const send = async (tokens: Tokens): Promise<Response> => {
    if (form) {
      return fetch(url, {
        method,
        headers: headersWith(auth, tokens.access, { 'Content-Type': 'application/x-www-form-urlencoded' }),
        body: new URLSearchParams(form).toString(),
      });
    }
    if (formData) {
      // multipart 的 boundary 交给运行时自动设置。
      return fetch(url, { method, headers: headersWith(auth, tokens.access), body: formData });
    }
    return fetch(url, {
      method,
      headers: headersWith(auth, tokens.access, body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  let response = await send(tokens);
  if (response.status === 401 && auth && bearer === undefined) {
    if (await refreshTokens()) response = await send(await loadTokens());
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, query?: Record<string, QueryValue>) => request<T>(path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T>(path: string, query?: Record<string, QueryValue>) => request<T>(path, { method: 'DELETE', query }),
};
