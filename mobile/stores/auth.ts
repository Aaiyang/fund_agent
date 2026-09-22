/**
 * Auth state (Zustand). Local/UI state only — server data belongs to TanStack
 * Query (spec 8.4).
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
    // Registration returns an access token only; sign in again to also get the
    // refresh token the client needs for long-lived sessions.
    await get().signIn(email, password);
  },

  async signOut() {
    try {
      await request<void>('/auth/logout', { method: 'POST' });
    } catch {
      // A failed revocation must not leave the user stuck in the app.
    }
    await clearTokens();
    // Cached server data belongs to this user: leaving it in place would render
    // the previous account's holdings until each query went stale.
    queryClient.clear();
    useUiStore.getState().reset();
    set({ status: 'anonymous', user: null });
  },
}));
