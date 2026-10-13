import { SymbolView } from 'expo-symbols';
import { router, Tabs } from 'expo-router';
import { Pressable } from 'react-native';

import { theme } from '@/constants/theme';
import { useUiStore } from '@/stores/ui';

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

/**
 * 会话面板的开关。放在表头左侧，点开的是聊天页里滑出的面板，
 * 所以这里只翻一个 UI 状态，不做跳转。
 */
function SessionsButton() {
  const open = useUiStore((state) => state.agentSessionsOpen);
  const setOpen = useUiStore((state) => state.setAgentSessionsOpen);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="历史会话"
      hitSlop={10}
      onPress={() => setOpen(!open)}
      style={{ paddingHorizontal: 16 }}
    >
      <SymbolView
        name={{ ios: 'bubble.left.and.bubble.right', android: 'chat', web: 'chat' }}
        tintColor={open ? theme.primary : theme.textMuted}
        size={22}
      />
    </Pressable>
  );
}

/**
 * 新建会话：只把聊天页切回空白，不在服务端建档。
 *
 * 之前这里一点就 POST /auth/session，于是"建了却没说话"的会话会留在历史列表里，
 * 越攒越多。空白会话本来就是未发生的事，第一条消息发出去时聊天页的
 * ensureActiveSession 再去建那条。
 */
function NewChatButton() {
  const setSessionId = useUiStore((state) => state.setAgentSessionId);
  const setSessionsOpen = useUiStore((state) => state.setAgentSessionsOpen);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="新建会话"
      hitSlop={10}
      onPress={() => {
        setSessionId(null);
        setSessionsOpen(false);
      }}
      style={{ paddingHorizontal: 16 }}
    >
      <SymbolView name={{ ios: 'plus', android: 'add', web: 'add' }} tintColor={theme.primary} size={22} />
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
        headerTitleAlign: 'center',
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
        name="market"
        options={{
          title: '行情',
          headerTitle: '行情',
          tabBarIcon: ({ color, size }) => (
            <SymbolView
              name={{ ios: 'chart.line.uptrend.xyaxis', android: 'show_chart', web: 'show_chart' }}
              tintColor={color}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="agent"
        options={{
          title: '小镜',
          headerTitle: '小镜',
          headerLeft: () => <SessionsButton />,
          headerRight: () => <NewChatButton />,
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
