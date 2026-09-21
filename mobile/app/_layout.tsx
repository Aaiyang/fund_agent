import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Redirect, Stack } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import * as SplashScreen from 'expo-splash-screen';

import { ApiError } from '@/api/client';
import { useAuthStore } from '@/stores/auth';
import { theme } from '@/constants/theme';

SplashScreen.preventAutoHideAsync().catch(() => {
  // Already hidden or not available on this platform.
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Client-side rejections (401/404/409/422) never succeed on retry.
      retry: (failureCount, error) => {
        const status = error instanceof ApiError ? error.status : undefined;
        if (status && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
    },
  },
});

export default function RootLayout() {
  const status = useAuthStore((state) => state.status);
  const bootstrap = useAuthStore((state) => state.bootstrap);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    if (status !== 'booting') SplashScreen.hideAsync().catch(() => undefined);
  }, [status]);

  if (status === 'booting') {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.background }}>
        <ActivityIndicator color={theme.primary} />
      </View>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      {status === 'anonymous' ? <Redirect href="/login" /> : null}
      <Stack>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="login" options={{ title: '登录' }} />
        <Stack.Screen name="search" options={{ title: '搜索基金' }} />
        <Stack.Screen name="watchlist-groups" options={{ title: '自选分组' }} />
        <Stack.Screen name="transactions" options={{ title: '交易记录' }} />
        <Stack.Screen name="fund/[code]" options={{ title: '基金详情' }} />
        <Stack.Screen name="position/edit" options={{ title: '修改持仓' }} />
        <Stack.Screen name="account/index" options={{ title: '账户管理' }} />
        <Stack.Screen name="account/add" options={{ title: '添加账户' }} />
        <Stack.Screen name="account/[id]" options={{ title: '账户详情' }} />
        <Stack.Screen name="holding-import/index" options={{ title: '导入持仓' }} />
        <Stack.Screen name="holding-import/manual" options={{ title: '手动录入' }} />
        <Stack.Screen name="holding-import/screenshots" options={{ title: '截图识别' }} />
        <Stack.Screen name="holding-import/[importId]" options={{ title: '确认导入结果' }} />
      </Stack>
    </QueryClientProvider>
  );
}
