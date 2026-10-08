import { SymbolView } from 'expo-symbols';
import { router, Tabs } from 'expo-router';
import { Pressable } from 'react-native';

import { theme } from '@/constants/theme';
import { useCreateAgentSession } from '@/hooks/useAgent';
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
 * 新建会话。放在表头标题右边，取代原来面板里那个「新建」文字按钮：
 * 建完直接选中并把面板收起，回到聊天页就是新的一条空白对话。
 */
function NewChatButton() {
  const create = useCreateAgentSession();
  const setSessionId = useUiStore((state) => state.setAgentSessionId);
  const setSessionsOpen = useUiStore((state) => state.setAgentSessionsOpen);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="新建会话"
      hitSlop={10}
      disabled={create.isPending}
      onPress={() => create.mutate(undefined, { onSuccess: (session) => { setSessionId(session.session_id); setSessionsOpen(false); } })}
      style={{ paddingHorizontal: 16, opacity: create.isPending ? 0.5 : 1 }}
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
        name="agent"
        options={{
          title: 'Agent',
          headerTitle: 'AI 基金助手',
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
