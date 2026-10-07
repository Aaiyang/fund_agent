import { QueryClientProvider } from '@tanstack/react-query';
import { Redirect, Stack } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import * as SplashScreen from 'expo-splash-screen';

import { queryClient } from '@/api/queryClient';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { useAuthStore } from '@/stores/auth';
import { theme } from '@/constants/theme';

SplashScreen.preventAutoHideAsync().catch(() => {
  // 启动屏已隐藏，或该平台不支持启动屏 API。
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
      <Stack>        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="login" options={{ title: '登录' }} />
        <Stack.Screen name="search" options={{ title: '搜索基金' }} />
        <Stack.Screen name="watchlist-groups" options={{ title: '自选分组' }} />
        <Stack.Screen name="transactions" options={{ title: '交易记录' }} />
        <Stack.Screen name="nav-history" options={{ title: '净值详情' }} />
        <Stack.Screen name="fund/[code]" options={{ title: '基金详情' }} />
        <Stack.Screen name="fund-holdings" options={{ title: '重仓股' }} />
        <Stack.Screen name="market/[symbol]" options={{ title: '行情分析' }} />
        <Stack.Screen name="position/edit" options={{ title: '修改持仓' }} />
        <Stack.Screen name="position/trade" options={{ title: '加减仓' }} />
        <Stack.Screen name="auto-invest" options={{ title: '定投计划' }} />
        <Stack.Screen name="profile/edit" options={{ title: '编辑资料' }} />
        <Stack.Screen name="account/index" options={{ title: '账户管理' }} />
        <Stack.Screen name="account/add" options={{ title: '添加账户' }} />
        <Stack.Screen name="account/[id]" options={{ title: '账户详情' }} />
        <Stack.Screen name="holding-import/index" options={{ title: '导入持仓' }} />
        <Stack.Screen name="holding-import/manual" options={{ title: '手动录入' }} />
        <Stack.Screen name="holding-import/screenshots" options={{ title: '截图识别' }} />
        <Stack.Screen name="holding-import/[importId]" options={{ title: '确认导入结果' }} />
      </Stack>
      <ConfirmDialog />
    </QueryClientProvider>
  );
}
