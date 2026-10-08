import { SymbolView } from 'expo-symbols';
import { useLocalSearchParams } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, Text, View } from 'react-native';

import { EmptyState, ErrorState, LoadingState, describeError } from '@/components/states';
import { AgentSessionsPanel } from '@/components/AgentSessionsPanel';
import { ImportReviewCard } from '@/components/ImportReviewCard';
import { MarkdownText } from '@/components/MarkdownText';
import { Screen } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useCreateAgentSession, useAgentSessions } from '@/hooks/useAgent';
import { useAgentChat } from '@/hooks/useAgentChat';
import { useChatImportDetail, useDecideChatImport, usePendingChatAction, useUploadChatScreenshots } from '@/hooks/useChatImport';
import { useFundDetail } from '@/hooks/useFunds';
import { useAccounts } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import type { PickedImage } from '@/hooks/useImports';

/** 一条附件批次：批次号 + 几张图。识别进度只对最后一条轮询，早先的只留个号。 */
type Attachment = { importId: string; imageCount: number };

const ATTACHMENT_PROMPT = '我刚上传了持仓截图，帮我看下识别结果';

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
  const sessionsOpen = useUiStore((state) => state.agentSessionsOpen);
  const setSessionsOpen = useUiStore((state) => state.setAgentSessionsOpen);
  const viewAccountId = useUiStore((state) => state.accountId);
  const sessions = useAgentSessions();
  const createSession = useCreateAgentSession();
  // 没手动选过会话时落在服务端的第一条，和 Web 端一个口径。
  const sessionId = storedSessionId ?? sessions.data?.[0]?.session_id ?? null;

  const context = useFundDetail(paramCode ?? null);
  const [contextDismissed, setContextDismissed] = useState(false);
  const [draft, setDraft] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const scroller = useRef<ScrollView>(null);
  // 面板的关闭回调要稳定：它进了那个滑动 effect 的依赖，每次渲染都换身份会让
  // 动画反复重启。
  const closeSessions = useCallback(() => setSessionsOpen(false), [setSessionsOpen]);

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

  const accounts = useAccounts();
  const upload = useUploadChatScreenshots(sessionId);
  const decide = useDecideChatImport(sessionId);
  const pending = usePendingChatAction(sessionId);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const lastAttachment = attachments[attachments.length - 1] ?? null;
  const importDetail = useChatImportDetail(sessionId, lastAttachment?.importId ?? null);

  /** 顶部导航选中的账户优先；汇总视图下落到第一个账户（与导入页同一口径）。 */
  function targetAccountId(): number | null {
    return viewAccountId ?? accounts.data?.items[0]?.id ?? null;
  }

  async function attachScreenshots() {
    const accountId = targetAccountId();
    if (!accountId) {
      setProblem('还没有账户，先去「我的 → 账户管理」建一个');
      return;
    }
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setProblem('没有相册权限，无法上传截图');
      return;
    }
    const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsMultipleSelection: true, quality: 1 });
    if (picked.canceled || !picked.assets?.length) return;
    const images: PickedImage[] = picked.assets.map((asset, index) => ({
      uri: asset.uri,
      name: asset.fileName ?? `chat-${Date.now()}-${index}.jpg`,
      mimeType: asset.mimeType ?? 'image/jpeg',
    }));
    setProblem(null);
    upload.mutate(
      { accountId, images },
      {
        onSuccess: (accepted) => setAttachments((prev) => [...prev, { importId: String(accepted.import_id), imageCount: accepted.image_count }]),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  function ask(text: string) {
    if (chat.sending) return;
    const trimmed = text.trim();
    const importIds = attachments.map((item) => item.importId);
    // 只发附件、一个字都不打也是这条功能的正常用法，补一句默认提问。
    const body = trimmed || (importIds.length ? ATTACHMENT_PROMPT : '');
    if (!body) return;
    // 后端只有一条自由文本的通道，基金上下文只能写在消息里；附件不是文本，
    // 它走 `holding_import_ids` 这个结构化字段，工具才拿得到真实批次号。
    const name = context.data?.fund_name;
    const question = contextCode ? `（我正在看基金 ${contextCode}${name ? ` ${name}` : ''}）\n${body}` : body;
    setDraft('');
    setProblem(null);
    setAttachments([]);
    void chat.send(question, importIds).catch((error: unknown) => setProblem(describeError(error)));
  }

  function decideImport(decision: 'confirm' | 'cancel') {
    const review = chat.review ?? pending.data?.pending_action ?? null;
    if (!review) return;
    setProblem(null);
    decide.mutate(
      {
        importId: String(review.import_id),
        decision,
        interruptId: review.interrupt_id ?? '',
        reviewDigest: review.review_digest,
      },
      {
        onSuccess: () => {
          chat.setReview(null);
          void pending.refetch();
          // 决策会恢复 Agent 并让它接着说话，所以历史要重取一次。
          void chat.history.refetch();
        },
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  // 流里带回来的优先，其次问服务端这条会话还挂着哪张卡（刷新/重连后能恢复）。
  const review = chat.review ?? pending.data?.pending_action ?? null;

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

        {review ? (
          <View style={{ paddingHorizontal: theme.gap, paddingTop: theme.gap }}>
            <ImportReviewCard review={review} pending={decide.isPending ? decide.variables.decision : null} onDecide={decideImport} />
          </View>
        ) : null}

        {attachments.length ? (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: theme.gap, paddingTop: 8 }}>
            {attachments.map((item) => {
              const isLast = item.importId === lastAttachment?.importId;
              const batch = isLast ? importDetail.data?.import_batch : null;
              const status = batch?.status ?? 'UPLOADED';
              const rows = batch?.items?.length;
              const label =
                status === 'PARSING' || status === 'UPLOADED'
                  ? `截图 ${item.imageCount} 张 · 识别中…`
                  : status === 'PARSE_FAILED'
                    ? `截图 ${item.imageCount} 张 · 识别失败`
                    : `截图 ${item.imageCount} 张 · 识别出 ${rows ?? 0} 行`;
              return (
                <View
                  key={item.importId}
                  style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: theme.surface, borderWidth: 1, borderColor: theme.border, borderRadius: 999, paddingLeft: 10, paddingVertical: 4, marginRight: 8, marginBottom: 4 }}
                >
                  <Text style={{ fontSize: 12, color: theme.textMuted }}>{label}</Text>
                  <Pressable accessibilityRole="button" accessibilityLabel="不带这个附件" hitSlop={8} onPress={() => setAttachments((prev) => prev.filter((each) => each.importId !== item.importId))}>
                    <Text style={{ fontSize: 12, color: theme.textFaint, marginLeft: 6 }}>✕</Text>
                  </Pressable>
                </View>
              );
            })}
          </View>
        ) : null}

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
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="添加截图"
            hitSlop={10}
            onPress={() => void attachScreenshots()}
            disabled={upload.isPending}
            style={{ marginRight: 8, paddingVertical: 10, opacity: upload.isPending ? 0.5 : 1 }}
          >
            {upload.isPending ? (
              <ActivityIndicator size="small" color={theme.primary} />
            ) : (
              <SymbolView name={{ ios: 'plus', android: 'add', web: 'add' }} tintColor={theme.textMuted} size={20} />
            )}
          </Pressable>
          <TextInput
            value={draft}
            onChangeText={setDraft}
            placeholder={attachments.length ? '想问它什么都行（会带上截图）' : contextCode ? `问问 ${contextCode}…` : '想问什么都行'}
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
        </View>
      </KeyboardAvoidingView>
      {sessionsOpen ? (
        <AgentSessionsPanel activeSessionId={sessionId} onPick={setSessionId} onClose={closeSessions} />
      ) : null}
    </Screen>
  );
}
