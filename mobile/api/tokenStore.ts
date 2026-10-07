/**
 * 令牌持久化。spec 8.6 禁止移动端用明文存储，所以原生端走 SecureStore；
 * expo-secure-store 没有 web 实现，web 构建退回 sessionStorage
 * （按标签页隔离，关掉标签就清空）。
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
