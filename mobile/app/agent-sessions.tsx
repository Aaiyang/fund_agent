/**
 * 历史会话列表：新建、切换、删除。
 *
 * 会话由服务端持有（LangGraph 的检查点按 session_id 当线程号），标题也是服务端
 * 在回答之后自动补的，所以这里不维护任何本地列表，只管显示服务端给的名字。
 */

import { SymbolView } from 'expo-symbols';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { sessionTitle, type ChatSession } from '@/api/chatSessions';
import { Async, EmptyState, describeError } from '@/components/states';
import { Badge, Button, Card, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAgentSessions, useCreateAgentSession, useDeleteAgentSession } from '@/hooks/useAgent';
import { useUiStore } from '@/stores/ui';
import { confirmAction } from '@/utils/confirm';

export default function AgentSessionsScreen() {
  const sessions = useAgentSessions();
  const create = useCreateAgentSession();
  const remove = useDeleteAgentSession();
  const storedSessionId = useUiStore((state) => state.agentSessionId);
  const setSessionId = useUiStore((state) => state.setAgentSessionId);
  const [problem, setProblem] = useState<string | null>(null);

  function select(sessionId: string) {
    setSessionId(sessionId);
    router.back();
  }

  async function createAndOpen() {
    try {
      const created = await create.mutateAsync();
      select(created.session_id);
    } catch (error) {
      setProblem(describeError(error));
    }
  }

  function confirmDelete(session: ChatSession, all: ChatSession[]) {
    confirmAction('删除这条会话', `「${sessionTitle(session)}」的全部消息会一起删掉，不可恢复。`, () => {
      remove.mutate(session.session_id, {
        onSuccess: () => {
          // 只有删掉的正是聊天页在用（或会兜底落到）的那条时，才需要重新落点。
          if (session.session_id !== (storedSessionId ?? all[0]?.session_id)) return;
          const remaining = all.filter((item) => item.session_id !== session.session_id);
          setSessionId(remaining[0]?.session_id ?? null);
        },
        onError: (error) => setProblem(describeError(error)),
      });
    });
  }

  return (
    <Screen>
      <Async
        query={sessions}
        empty={(data) => (data.length === 0 ? <EmptyState title="还没有会话" hint="回 Agent 页发一句话就会建一条。" /> : null)}
      >
        {(data) => (
          <Card>
            <SectionTitle title="会话" action="新建一条" onAction={() => void createAndOpen()} />
            {data.map((session) => {
              const active = (storedSessionId ?? data[0]?.session_id) === session.session_id;
              return (
                <View
                  key={session.session_id}
                  style={{
                    flexDirection: 'row',
                    alignItems: 'center',
                    paddingVertical: 10,
                    borderTopWidth: 1,
                    borderTopColor: theme.border,
                  }}
                >
                  <Pressable accessibilityRole="button" style={{ flex: 1 }} onPress={() => select(session.session_id)}>
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
                    onPress={() => confirmDelete(session, data)}
                    style={{ paddingHorizontal: 8 }}
                  >
                    <SymbolView name={{ ios: 'trash', android: 'delete', web: 'delete' }} tintColor={theme.textFaint} size={18} />
                  </Pressable>
                </View>
              );
            })}
          </Card>
        )}
      </Async>
      {problem ? <Text style={{ fontSize: 13, color: theme.danger, marginBottom: 8 }}>{problem}</Text> : null}
      <Button label="回 Agent" variant="secondary" onPress={() => router.back()} />
    </Screen>
  );
}
