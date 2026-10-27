import { SymbolView } from 'expo-symbols';
import { router, Tabs } from 'expo-router';
import { type ReactNode } from 'react';
import { Pressable, Text, View } from 'react-native';

import { theme } from '@/constants/theme';
import { useUiStore } from '@/stores/ui';

/** 表头圆形按钮：白瓷底、细描边，和聊天页的输入框是同一套材质。 */
function HeaderIconButton({
  label,
  onPress,
  active,
  children,
}: {
  label: string;
  onPress: () => void;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => ({
        width: 34,
        height: 34,
        marginHorizontal: 8,
        borderRadius: 11,
        borderWidth: 1,
        borderColor: active ? theme.primary : theme.border,
        backgroundColor: active ? theme.primarySoft : theme.surface,
        alignItems: 'center',
        justifyContent: 'center',
        opacity: pressed ? 0.7 : 1,
      })}
    >
      {children}
    </Pressable>
  );
}

function SearchButton() {
  return (
    <HeaderIconButton label="搜索基金" onPress={() => router.push('/search')}>
      <SymbolView name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }} tintColor={theme.primary} size={19} />
    </HeaderIconButton>
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
    <HeaderIconButton label="历史会话" active={open} onPress={() => setOpen(!open)}>
      <SymbolView
        name={{ ios: 'bubble.left.and.bubble.right', android: 'chat', web: 'chat' }}
        tintColor={open ? theme.primary : theme.textMuted}
        size={18}
      />
    </HeaderIconButton>
  );
}

/**
 * 新建会话：只把聊天页切回空白，不在服务端建档。
 *
 * 之前这里一点就 POST /auth/session，于是"建了却没说一句话"的会话会留在历史列表里，
 * 越攒越多。空白会话本来就是未发生的事，第一条消息发出去时聊天页的
 * ensureActiveSession 再去建那条。
 */
function NewChatButton() {
  const setSessionId = useUiStore((state) => state.setAgentSessionId);
  const setSessionsOpen = useUiStore((state) => state.setAgentSessionsOpen);
  return (
    <HeaderIconButton
      label="新建会话"
      onPress={() => {
        setSessionId(null);
        setSessionsOpen(false);
      }}
    >
      <SymbolView name={{ ios: 'plus', android: 'add', web: 'add' }} tintColor={theme.primary} size={19} />
    </HeaderIconButton>
  );
}

/** 聊天表头两行：标题是助手名，副行只说当前状态。 */
function AgentHeaderTitle() {
  const streaming = useUiStore((state) => state.agentStreaming);
  const subtitle = streaming ? '正在生成' : '在线';
  return (
    <View style={{ alignItems: 'center', maxWidth: 190 }}>
      <Text style={{ fontSize: 17, fontWeight: '600', color: theme.text }}>小镜</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 2 }}>
        <View
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            marginRight: 5,
            backgroundColor: streaming ? theme.gold : theme.primary,
          }}
        />
        <Text numberOfLines={1} style={{ fontSize: 11, color: theme.textMuted }}>
          {subtitle}
        </Text>
      </View>
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: theme.primary,
        tabBarInactiveTintColor: theme.textFaint,
        tabBarStyle: {
          backgroundColor: theme.surface,
          borderTopWidth: 1,
          borderTopColor: theme.border,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '500' },
        headerShown: true,
        headerTitleAlign: 'center',
        headerStyle: { backgroundColor: theme.background },
        headerShadowVisible: false,
        headerTintColor: theme.primary,
        headerTitleStyle: { fontSize: 17, fontWeight: '600', color: theme.text },
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
          headerTitle: () => <AgentHeaderTitle />,
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
