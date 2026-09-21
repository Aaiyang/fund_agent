import { SymbolView } from 'expo-symbols';
import { Tabs } from 'expo-router';

import { theme } from '@/constants/theme';

/**
 * Tab icons. expo-symbols validates each name per platform: iOS uses SF
 * Symbols, Android/web use the Material list, so the pairs differ.
 */
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
