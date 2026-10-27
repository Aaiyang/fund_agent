/**
 * 会话面板：贴在屏幕左边、从左往右滑出，盖在聊天内容上面。
 *
 * 不用 Modal 是因为 `animationType="slide"` 三端都是自下而上，出不来抽屉感；
 * 一层绝对定位遮罩 + Animated.translateX 反而一致。宽度按屏宽 78% 取（上限 320），
 * 动画位移用同一个数算，省掉 onLayout 量宽那一轮。
 *
 * 面板自己不放标题栏：标题在表头已经有了，再来一条会把两块界面割开。
 * 关闭靠点遮罩、再点一次表头那个按钮，或直接选中一条会话。
 */

import { SymbolView } from 'expo-symbols';
import { useEffect, useState } from 'react';
import { Animated, Dimensions, Platform, Pressable, ScrollView, Text, View } from 'react-native';

import { sessionTitle, type ChatSession } from '@/api/chatSessions';
import { describeError } from '@/components/states';
import { Badge } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAgentSessions, useDeleteAgentSession } from '@/hooks/useAgent';
import { confirmAction } from '@/utils/confirm';
import { formatSessionTime } from '@/utils/format';

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
  const remove = useDeleteAgentSession();
  const [problem, setProblem] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  // Animated.Value 要跨渲染保持稳定，但 useRef(...).current 属于渲染期读 ref，
  // expo 的 react-hooks/refs 会拦；useState 惰性初始化同样只建一次。
  // 初值 1 = 停在左边框外，挂载后那个 effect 推到 0，才是"从左往右滑出"。
  const [slide] = useState(() => new Animated.Value(1));

  useEffect(() => {
    Animated.timing(slide, {
      toValue: closing ? 1 : 0,
      duration: 180,
      // react-native-web 没有 native driver：开着它动画不跑，start() 的回调也不触发。
      useNativeDriver: Platform.OS !== 'web',
    }).start();
  }, [closing, slide]);

  useEffect(() => {
    if (!closing) return;
    // 卸载交给定时器，时长与动画一致，两端都确定性收口。
    const timer = setTimeout(onClose, 180);
    return () => clearTimeout(timer);
  }, [closing, onClose]);

  function dismiss() {
    setClosing(true);
  }

  function pick(sessionId: string) {
    onPick(sessionId);
    dismiss();
  }

  function confirmDelete(session: ChatSession) {
    confirmAction('删除这条会话', `「${sessionTitle(session)}」的全部消息会一起删掉，不可恢复。`, () => {
      remove.mutate(session.session_id, { onError: (error) => setProblem(describeError(error)) });
    });
  }

  const items = sessions.data ?? [];

  return (
    <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="关闭会话列表"
        onPress={dismiss}
        style={{ flex: 1, backgroundColor: theme.overlay }}
      />
      <Animated.View
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: 0,
          width: PANEL_WIDTH,
          backgroundColor: theme.surface,
          borderRightWidth: 1,
          borderColor: theme.border,
          transform: [{ translateX: slide.interpolate({ inputRange: [0, 1], outputRange: [0, -PANEL_WIDTH] }) }],
        }}
      >
        <View
          style={{
            paddingHorizontal: 16,
            paddingTop: 16,
            paddingBottom: 12,
            borderBottomWidth: 1,
            borderBottomColor: theme.border,
            flexDirection: 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <View>
            <Text style={{ fontSize: 10, fontWeight: '700', letterSpacing: 1.4, color: theme.gold }}>HISTORY</Text>
            <Text style={{ marginTop: 4, fontSize: 19, fontWeight: '600', color: theme.text }}>会话</Text>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="关闭会话列表"
            hitSlop={8}
            onPress={dismiss}
            style={{ width: 34, height: 34, borderRadius: 11, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surfaceSoft, alignItems: 'center', justifyContent: 'center' }}
          >
            <SymbolView name={{ ios: 'xmark', android: 'close', web: 'close' }} tintColor={theme.textMuted} size={15} />
          </Pressable>
        </View>
        <ScrollView contentContainerStyle={{ padding: 12 }}>
          {sessions.isPending ? <Text style={{ fontSize: 13, color: theme.textMuted, padding: 6 }}>加载中…</Text> : null}
          {!sessions.isPending && !items.length ? (
            <Text style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20, padding: 6 }}>还没有会话，问过一句就会出现在这里。</Text>
          ) : null}
          {items.map((session) => {
            const active = activeSessionId === session.session_id;
            return (
              <View
                key={session.session_id}
                style={{
                  flexDirection: 'row',
                  alignItems: 'center',
                  paddingVertical: 10,
                  paddingHorizontal: 10,
                  marginBottom: 6,
                  borderRadius: 12,
                  borderWidth: 1,
                  borderColor: active ? theme.primary : 'transparent',
                  backgroundColor: active ? theme.primarySoft : 'transparent',
                }}
              >
                <Pressable accessibilityRole="button" style={{ flex: 1 }} onPress={() => pick(session.session_id)}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={{ flexShrink: 1, fontSize: 14, color: theme.text, fontWeight: active ? '600' : '500' }} numberOfLines={1}>
                      {sessionTitle(session)}
                    </Text>
                    {active ? (
                      <View style={{ marginLeft: 8 }}>
                        <Badge label="当前" tone="muted" />
                      </View>
                    ) : null}
                  </View>
                  {/* 列表按创建时间倒序，标出时间才看得出哪条是刚聊过的。 */}
                  {session.created_at ? (
                    <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 3 }}>
                      {formatSessionTime(session.created_at)}
                    </Text>
                  ) : null}
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="删除这条会话"
                  hitSlop={10}
                  onPress={() => confirmDelete(session)}
                  style={{ padding: 6 }}
                >
                  <SymbolView name={{ ios: 'trash', android: 'delete', web: 'delete' }} tintColor={theme.textFaint} size={17} />
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
