/**
 * 认证状态（Zustand）。这里只放本地/UI 状态——服务器数据归 TanStack Query（spec 8.4）。
 */

import { create } from 'zustand';

import { request } from '@/api/client';
import { queryClient } from '@/api/queryClient';
import { clearTokens, loadTokens, saveTokens } from '@/api/tokenStore';
import { useUiStore } from '@/stores/ui';
import type { components } from '@/api/schema';

export type CurrentUser = components['schemas']['CurrentUserResponse'];
type TokenResponse = components['schemas']['TokenResponse'];
type UserResponse = components['schemas']['UserResponse'];

type AuthStatus = 'booting' | 'anonymous' | 'authenticated';

type AuthState = {
  status: AuthStatus;
  user: CurrentUser | null;
  error: string | null;
  bootstrap: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, username?: string) => Promise<void>;
  updateProfile: (input: { email?: string; username?: string }) => Promise<void>;
  signOut: () => Promise<void>;
};

async function fetchMe(): Promise<CurrentUser> {
  return request<CurrentUser>('/auth/me');
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'booting',
  user: null,
  error: null,

  async bootstrap() {
    const { access } = await loadTokens();
    if (!access) {
      set({ status: 'anonymous', user: null });
      return;
    }
    try {
      const user = await fetchMe();
      set({ status: 'authenticated', user, error: null });
    } catch {
      await clearTokens();
      set({ status: 'anonymous', user: null });
    }
  },

  async signIn(email, password) {
    const tokens = await request<TokenResponse>('/auth/login', {
      method: 'POST',
      form: { email, password, grant_type: 'password' },
      auth: false,
    });
    await saveTokens(tokens.access_token, tokens.refresh_token ?? null);
    const user = await fetchMe();
    set({ status: 'authenticated', user, error: null });
  },

  async signUp(email, password, username) {
    await request<UserResponse>(
      '/auth/register',
      { method: 'POST', body: { email, password, username: username || null }, auth: false },
    );
    // 注册只回访问令牌；再走一次登录，把客户端维持长会话所需的
    // 刷新令牌也拿到手。
    await get().signIn(email, password);
  },

  async updateProfile(input) {
    const user = await request<CurrentUser>('/auth/me', { method: 'PATCH', body: input });
    set({ user });
  },

  async signOut() {
    try {
      await request<void>('/auth/logout', { method: 'POST' });
    } catch {
      // 吊销令牌失败也不能把用户卡死在应用里。
    }
    await clearTokens();
    // 缓存里的服务器数据属于这个用户：不清掉的话，各项查询过期之前，
    // 界面会一直渲染上一个账户的持仓。
    queryClient.clear();
    useUiStore.getState().reset();
    set({ status: 'anonymous', user: null });
  },
}));
