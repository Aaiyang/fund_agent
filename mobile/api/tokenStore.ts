/**
 * Token persistence. Spec 8.6 forbids plain storage on mobile, so native uses
 * SecureStore; expo-secure-store has no web implementation, so the web build
 * falls back to sessionStorage (per-tab, cleared on close).
 */

import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const ACCESS_KEY = 'fund-agent.access';
const REFRESH_KEY = 'fund-agent.refresh';

export type Tokens = { access: string | null; refresh: string | null };

async function read(key: string): Promise<string | null> {
  if (Platform.OS === 'web') return window.sessionStorage.getItem(key);
  return SecureStore.getItemAsync(key);
}

async function write(key: string, value: string | null): Promise<void> {
  if (Platform.OS === 'web') {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
    return;
  }
  if (value === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, value);
}

export async function loadTokens(): Promise<Tokens> {
  const [access, refresh] = await Promise.all([read(ACCESS_KEY), read(REFRESH_KEY)]);
  return { access, refresh };
}

export async function saveTokens(access: string, refresh?: string | null): Promise<void> {
  await write(ACCESS_KEY, access);
  if (refresh) await write(REFRESH_KEY, refresh);
}

export async function clearTokens(): Promise<void> {
  await write(ACCESS_KEY, null);
  await write(REFRESH_KEY, null);
}
