import { SymbolView } from 'expo-symbols';
import { useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, Text, View } from 'react-native';

import { EmptyState, ErrorState, LoadingState, describeError } from '@/components/states';
import { MarkdownText } from '@/components/MarkdownText';
import { Screen } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useClearAgentMessages, useCreateAgentSession, useAgentSessions } from '@/hooks/useAgent';
import { useAgentChat } from '@/hooks/useAgentChat';
import { useFundDetail } from '@/hooks/useFunds';
import { useUiStore } from '@/stores/ui';
import { confirmAction } from '@/utils/confirm';

function Bubble({ role, content, streaming, failed, onRetry }: {
  role: string;
  content: string;
  streaming?: boolean;
  failed?: string;
  onRetry?: () => void;
}) {
  const mine = role === 'user';
  return (
    <View
      style={{
        alignSelf: mine ? 'flex-end' : 'flex-start',
        maxWidth: '86%',
        marginBottom: 10,
        backgroundColor: mine ? theme.primary : theme.surface,
        borderRadius: theme.radius,
        borderWidth: mine ? 0 : 1,
        borderColor: theme.border,
        padding: 12,
      }}
    >
      {mine ? (
        <Text style={{ fontSize: 15, lineHeight: 22, color: '#FFFFFF' }} selectable>
          {content}
        </Text>
      ) : content ? (
        <MarkdownText content={content} />
      ) : streaming ? (
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <ActivityIndicator color={theme.primary} size="small" />
          <Text style={{ fontSize: 14, color: theme.textMuted, marginLeft: 8 }}>正在思考…</Text>
        </View>
      ) : null}
      {failed ? (
        <View style={{ marginTop: 8 }}>
          <Text style={{ fontSize: 13, color: theme.danger }} numberOfLines={2}>
            {failed}
          </Text>
          <Text style={{ fontSize: 13, color: theme.primary, marginTop: 6 }} onPress={onRetry}>
            重新生成
          </Text>
        </View>
      ) : null}
    </View>
  );
}

export default function AgentScreen() {
  const { fund_code: paramCode } = useLocalSearchParams<{ fund_code?: string }>();
  const storedSessionId = useUiStore((state) => state.agentSessionId);
  const setSessionId = useUiStore((state) => state.setAgentSessionId);
  const sessions = useAgentSessions();
  const createSession = useCreateAgentSession();
  // 没手动选过会话时落在服务端的第一条，和 Web 端一个口径。
  const sessionId = storedSessionId ?? sessions.data?.[0]?.session_id ?? null;

  const clearMessages = useClearAgentMessages(sessionId);
  const context = useFundDetail(paramCode ?? null);
  const [contextDismissed, setContextDismissed] = useState(false);
  const [draft, setDraft] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const scroller = useRef<ScrollView>(null);

  const chat = useAgentChat({
    sessionId,
    ensureSession: async () => {
      if (sessionId) return sessionId;
      const created = await createSession.mutateAsync();
      setSessionId(created.session_id);
      return created.session_id;
    },
  });

  const contextCode = paramCode && !contextDismissed ? paramCode : null;

  function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || chat.sending) return;
    // 后端只有一条自由文本的通道，基金上下文只能写在消息里；
    // 界面把它作为独立的一行带上，用户看得见自己实际发出去了什么。
    const name = context.data?.fund_name;
    const question = contextCode ? `（我正在看基金 ${contextCode}${name ? ` ${name}` : ''}）\n${trimmed}` : trimmed;
    setDraft('');
    setProblem(null);
    void chat.send(question).catch((error: unknown) => setProblem(describeError(error)));
  }

  function confirmClear() {
    if (!chat.turns.length) return;
    confirmAction('清空当前对话', '这条会话里的消息会全部删除，会话本身保留。', () => {
      chat.reset();
      clearMessages.mutate(undefined, { onError: (error) => setProblem(describeError(error)) });
    });
  }

  return (
    <Screen scroll={false}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={{ flexDirection: 'row', paddingHorizontal: theme.gap, paddingTop: theme.gap }}>
          {contextCode ? (
            <View
              style={{
                flexDirection: 'row',
                alignItems: 'center',
                backgroundColor: theme.warningBackground,
                borderRadius: 999,
                paddingLeft: 10,
                paddingVertical: 4,
                marginBottom: 6,
              }}
            >
              <Text style={{ fontSize: 12, color: theme.warning }}>已带上下文 {contextCode}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="不带这个上下文" hitSlop={8} onPress={() => setContextDismissed(true)}>
                <Text style={{ fontSize: 12, color: theme.warning, marginLeft: 6 }}>✕</Text>
              </Pressable>
            </View>
          ) : null}
        </View>

        {chat.loadingHistory ? (
          <LoadingState label="正在读历史…" />
        ) : chat.historyError && !chat.turns.length ? (
          <ErrorState message={describeError(chat.historyError)} onRetry={chat.retryHistory} />
        ) : (
          <ScrollView
            ref={scroller}
            contentContainerStyle={{ padding: theme.gap, paddingBottom: 16 }}
            keyboardShouldPersistTaps="handled"
            onContentSizeChange={() => scroller.current?.scrollToEnd({ animated: true })}
          >
            {!chat.turns.length ? (
              <EmptyState title="问点什么都行" hint="可以问我的持仓、我的自选、某一只基金，或者让它对比两只。" />
            ) : null}
            {chat.turns.map((turn, index) => (
              <Bubble
                key={`${index}-${turn.role}`}
                role={turn.role}
                content={turn.content}
                streaming={turn.state === 'streaming'}
                failed={turn.state === 'failed' ? turn.error : undefined}
                onRetry={chat.retry}
              />
            ))}
            {problem ? <Text style={{ fontSize: 13, color: theme.danger, marginBottom: 8 }}>{problem}</Text> : null}
          </ScrollView>
        )}

        <View
          style={{
            flexDirection: 'row',
            alignItems: 'flex-end',
            backgroundColor: theme.surface,
            borderTopWidth: 1,
            borderTopColor: theme.border,
            paddingHorizontal: theme.gap,
            paddingVertical: 8,
          }}
        >
          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder={contextCode ? `问问 ${contextCode}…` : '想问什么都行'}
            placeholderTextColor={theme.textFaint}
            maxLength={3000}
            multiline
            editable={!chat.sending}
            onSubmitEditing={() => ask(draft)}
            returnKeyType="send"
            blurOnSubmit={false}
            style={{
              flex: 1,
              maxHeight: 112,
              minHeight: 40,
              borderWidth: 1,
              borderColor: theme.border,
              borderRadius: 10,
              paddingHorizontal: 12,
              paddingVertical: 9,
              fontSize: 15,
              color: theme.text,
              backgroundColor: theme.background,
              textAlignVertical: 'top',
            }}
          />
          {chat.sending ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="停止生成"
              onPress={chat.stop}
              style={{ marginLeft: 8, paddingHorizontal: 14, paddingVertical: 11, borderRadius: 10, borderWidth: 1, borderColor: theme.danger }}
            >
              <Text style={{ fontSize: 15, color: theme.danger, fontWeight: '600' }}>停止</Text>
            </Pressable>
          ) : (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="发送"
              disabled={!draft.trim()}
              onPress={() => ask(draft)}
              style={{ marginLeft: 8, paddingHorizontal: 14, paddingVertical: 11, borderRadius: 10, backgroundColor: theme.primary, opacity: draft.trim() ? 1 : 0.45 }}
            >
              <Text style={{ fontSize: 15, color: '#FFFFFF', fontWeight: '600' }}>发送</Text>
            </Pressable>
          )}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="清空当前对话"
            hitSlop={10}
            onPress={confirmClear}
            style={{ marginLeft: 10, paddingVertical: 11 }}
          >
            <SymbolView name={{ ios: 'trash', android: 'delete', web: 'delete' }} tintColor={theme.textFaint} size={18} />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}
