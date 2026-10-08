/**
 * 会话面板：从屏幕右侧滑入，盖在聊天内容上面。
 *
 * 不用 Modal 是因为 `animationType="slide"` 在 iOS/Android/Web 上都是自下而上，
 * 而这里要的是"右滑出来"的抽屉感；用一层绝对定位的遮罩 + Animated.translateX
 * 反而三端一致。宽度按屏宽 78% 取（上限 320），动画位移直接用同一个数算，
 * 省掉 onLayout 量宽那一轮（面板挂载时宽度就该确定）。
 */

import { SymbolView } from 'expo-symbols';
import { useEffect, useState } from 'react';
import { Animated, Dimensions, Pressable, ScrollView, Text, View } from 'react-native';

import { sessionTitle, type ChatSession } from '@/api/chatSessions';
import { confirmAction } from '@/utils/confirm';
import { useAgentSessions, useCreateAgentSession, useDeleteAgentSession } from '@/hooks/useAgent';
import { theme } from '@/constants/theme';
import { Badge } from '@/components/ui';
import { describeError } from '@/components/states';

const PANEL_WIDTH = Math.min(320, Dimensions.get('window').width * 0.78);

export function AgentSessionsPanel({
  activeSessionId,
  onPick,
  onClose,
}: {
  activeSessionId: string | null;
  onPick: (sessionId: string) => void;
  onClose: () => void;
}) {
  const sessions = useAgentSessions();
  const create = useCreateAgentSession();
  const remove = useDeleteAgentSession();
  const [problem, setProblem] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  // Animated.Value 要跨渲染保持稳定，但用 useRef(...).current 会在渲染期读 ref，
  // expo 的 react-hooks/refs 规则会拦；useState 的惰性初始化同样只建一次。
  const [slide] = useState(() => new Animated.Value(0));

  useEffect(() => {
    Animated.timing(slide, { toValue: closing ? 1 : 0, duration: 180, useNativeDriver: true }).start(() => {
      if (closing) onClose();
    });
  }, [closing, slide, onClose]);

  function dismiss() {
    setClosing(true);
  }

  function pick(sessionId: string) {
    onPick(sessionId);
    dismiss();
  }

  function createAndPick() {
    create.mutate(undefined, {
      onSuccess: (session) => pick(session.session_id),
      onError: (error) => setProblem(describeError(error)),
    });
  }

  function confirmDelete(session: ChatSession) {
    confirmAction('删除这条会话', `「${sessionTitle(session)}」的全部消息会一起删掉，不可恢复。`, () => {
      remove.mutate(session.session_id, { onError: (error) => setProblem(describeError(error)) });
    });
  }

  const items = sessions.data ?? [];

  return (
    <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
      <Pressable accessibilityRole="button" accessibilityLabel="关闭会话列表" onPress={dismiss} style={{ flex: 1, backgroundColor: 'rgba(17,24,39,0.35)' }} />
      <Animated.View
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          right: 0,
          width: PANEL_WIDTH,
          backgroundColor: theme.surface,
          borderLeftWidth: 1,
          borderColor: theme.border,
          transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [0, PANEL_WIDTH] }) }],
        }}
      >
        <View
          style={{
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingHorizontal: theme.gap,
            paddingTop: theme.gap,
            paddingBottom: 8,
            borderBottomWidth: 1,
            borderColor: theme.border,
          }}
        >
          <Text style={{ fontSize: 16, fontWeight: '600', color: theme.text }}>会话</Text>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <Pressable accessibilityRole="button" onPress={createAndPick} disabled={create.isPending} hitSlop={8} style={{ marginRight: 14 }}>
              <Text style={{ fontSize: 13, color: theme.primary, opacity: create.isPending ? 0.5 : 1 }}>{create.isPending ? '新建中…' : '新建'}</Text>
            </Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel="关闭" onPress={dismiss} hitSlop={10}>
              <SymbolView name={{ ios: 'xmark', android: 'close', web: 'close' }} tintColor={theme.textMuted} size={18} />
            </Pressable>
          </View>
        </View>

        <ScrollView contentContainerStyle={{ padding: theme.gap }}>
          {sessions.isPending ? <Text style={{ fontSize: 13, color: theme.textMuted }}>加载中…</Text> : null}
          {!sessions.isPending && !items.length ? (
            <Text style={{ fontSize: 13, color: theme.textMuted }}>还没有会话，点「新建」开始一条。</Text>
          ) : null}
          {items.map((session) => {
            const active = activeSessionId === session.session_id;
            return (
              <View
                key={session.session_id}
                style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderColor: theme.border }}
              >
                <Pressable accessibilityRole="button" style={{ flex: 1 }} onPress={() => pick(session.session_id)}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={{ fontSize: 15, color: theme.text, fontWeight: '500' }} numberOfLines={1}>
                      {sessionTitle(session)}
                    </Text>
                    {active ? (
                      <View style={{ marginLeft: 8 }}>
                        <Badge label="当前" tone="muted" />
                      </View>
                    ) : null}
                  </View>
                  <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>会话 {session.session_id.slice(0, 8)}</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="删除这条会话"
                  hitSlop={10}
                  onPress={() => confirmDelete(session)}
                  style={{ paddingHorizontal: 6 }}
                >
                  <SymbolView name={{ ios: 'trash', android: 'delete', web: 'delete' }} tintColor={theme.textFaint} size={18} />
                </Pressable>
              </View>
            );
          })}
          {problem ? <Text style={{ fontSize: 13, color: theme.danger, marginTop: 10 }}>{problem}</Text> : null}
        </ScrollView>
      </Animated.View>
    </View>
  );
}
