/**
 * 聊天域的会话令牌登记处。
 *
 * `/chatbot/*` 认的是**会话令牌**（JWT 的 sub 是会话 UUID），不是登录用的用户令牌：
 * 拿用户令牌去打聊天接口，服务端按会话去找会直接 404。而 `GET /auth/sessions`
 * 每次都会为每条会话**重新签发**一个新令牌，所以这里只在内存里存最新那一份：
 * 落盘反而会留着一个已经过期的令牌，重启后照样得重新拉列表。
 */

import type { components } from '@/api/schema';

/**
 * 一条聊天会话。
 *
 * `created_at` 是后端刚补上的字段：`api/schema.ts` 那份生成物还没重跑到它，所以这里
 * 先交叉出可选形状（下次 `npm run generate:api` 之后它会变成必填，这段不用改）。
 */
export type ChatSession = components['schemas']['SessionResponse'] & { created_at?: string };

const tokens = new Map<string, string>();

export function rememberSession(session: ChatSession | null | undefined): void {
  const token = session?.token?.access_token;
  if (session?.session_id && token) tokens.set(session.session_id, token);
}

export function rememberSessions(sessions: ChatSession[] | null | undefined): void {
  for (const session of sessions ?? []) rememberSession(session);
}

export function sessionToken(sessionId: string | null | undefined): string | undefined {
  if (!sessionId) return undefined;
  return tokens.get(sessionId);
}

export function forgetSession(sessionId: string): void {
  tokens.delete(sessionId);
}

/** 退出登录时清干净，免得下一个用户拿着上一个人的会话令牌。 */
export function forgetAllSessions(): void {
  tokens.clear();
}

/** 会话在界面上的显示名：服务端会自动起名，起好了之前先用占位文案。 */
export function sessionTitle(session: ChatSession): string {
  return session.name?.trim() || '新对话';
}
