import { SymbolView } from 'expo-symbols';
import { router, Tabs } from 'expo-router';
import { Pressable } from 'react-native';

import { theme } from '@/constants/theme';

/**
 * 标签栏图标。expo-symbols 按平台分别校验图标名：iOS 用 SF Symbols，
 * Android/web 用 Material 图标列表，所以各平台的名称成对配置且取值不同。
 */
function SearchButton() {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="搜索基金"
      hitSlop={10}
      onPress={() => router.push('/search')}
      style={{ paddingHorizontal: 16 }}
    >
      <SymbolView name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }} tintColor={theme.primary} size={22} />
    </Pressable>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: theme.primary,
        tabBarInactiveTintColor: theme.textMuted,
        headerShown: true,
        headerTitleStyle: { fontSize: 17, color: theme.text },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: '持有',
          headerTitle: '我的持仓',
          headerRight: () => <SearchButton />,
          tabBarIcon: ({ color, size }) => (
            <SymbolView
              name={{ ios: 'briefcase', android: 'account_balance', web: 'account_balance' }}
              tintColor={color}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="watchlist"
        options={{
          title: '自选',
          headerTitle: '自选基金',
          headerRight: () => <SearchButton />,
          tabBarIcon: ({ color, size }) => (
            <SymbolView name={{ ios: 'star', android: 'star', web: 'star' }} tintColor={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="agent"
        options={{
          title: 'Agent',
          tabBarIcon: ({ color, size }) => (
            <SymbolView name={{ ios: 'sparkles', android: 'auto_awesome', web: 'auto_awesome' }} tintColor={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: '我的',
          tabBarIcon: ({ color, size }) => (
            <SymbolView name={{ ios: 'person', android: 'person', web: 'person' }} tintColor={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
