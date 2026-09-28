/**
 * REST client for the FastAPI backend: bearer auth, single-flight token
 * refresh, and typed errors. Screens never call fetch directly.
 *
 * The base URL must be a LAN address when running on a real Android device —
 * `localhost` points at the phone itself (spec 11.2). Set
 * EXPO_PUBLIC_API_BASE_URL in mobile/.env.
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

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  /** JSON body. */
  body?: unknown;
  /** application/x-www-form-urlencoded fields (the auth endpoints use them). */
  form?: Record<string, string>;
  /** multipart payload built by the caller. */
  formData?: FormData;
  query?: Record<string, QueryValue>;
  /** Set false for public endpoints. Default true. */
  auth?: boolean;
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

async function parseError(response: Response): Promise<ApiError> {
  let code = `http_${response.status}`;
  let message = response.statusText || '请求失败';
  try {
    const payload = await response.json();
    if (typeof payload?.detail === 'string') {
      message = payload.detail;
      code = payload.detail;
    } else if (Array.isArray(payload?.errors)) {
      message = payload.errors.map((item: { message?: string }) => item.message).join('；');
      code = 'validation_error';
    }
  } catch {
    // Non-JSON error body: keep the status-derived code.
  }
  return new ApiError(response.status, code, message);
}

/** Refresh tokens are exchanged once at a time; concurrent 401s share it. */
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
 * Perform a request, refreshing the access token once on 401.
 *
 * Throws ApiError for any non-2xx response so callers can branch on status.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, form, formData, query, auth = true } = options;
  const url = buildUrl(path, query);

  const send = async (tokens: Tokens): Promise<Response> => {
    if (form) {
      return fetch(url, {
        method,
        headers: headersWith(auth, tokens.access, { 'Content-Type': 'application/x-www-form-urlencoded' }),
        body: new URLSearchParams(form).toString(),
      });
    }
    if (formData) {
      // Let the runtime set the multipart boundary.
      return fetch(url, { method, headers: headersWith(auth, tokens.access), body: formData });
    }
    return fetch(url, {
      method,
      headers: headersWith(auth, tokens.access, body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  };

  let response = await send(await loadTokens());
  if (response.status === 401 && auth) {
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
