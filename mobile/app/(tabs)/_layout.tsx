import { SymbolView } from 'expo-symbols';
import { router, Tabs } from 'expo-router';
import { Pressable } from 'react-native';

import { theme } from '@/constants/theme';

/**
 * Tab icons. expo-symbols validates each name per platform: iOS uses SF
 * Symbols, Android/web use the Material list, so the pairs differ.
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
