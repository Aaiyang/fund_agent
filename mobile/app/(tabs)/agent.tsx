import { SymbolView } from 'expo-symbols';
import { useLocalSearchParams } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, TextInput, Text, View } from 'react-native';

import { ErrorState, LoadingState, describeError } from '@/components/states';
import { AgentSessionsPanel } from '@/components/AgentSessionsPanel';
import { ImportReviewCard } from '@/components/ImportReviewCard';
import { MarkdownText } from '@/components/MarkdownText';
import { Screen } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useCreateAgentSession, useAgentSessions } from '@/hooks/useAgent';
import { useAgentChat } from '@/hooks/useAgentChat';
import { useDecideChatImport, usePendingChatAction, useUploadChatScreenshots } from '@/hooks/useChatImport';
import { useFundDetail } from '@/hooks/useFunds';
import { useLlmProfiles } from '@/hooks/useLlmProfiles';
import { useAccounts } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import type { PickedImage } from '@/hooks/useImports';

/** 一条待发送的附件。选完只留在本地，点发送才上传——上传本身就是让服务端开始识别。 */
type Attachment = { key: string; images: PickedImage[] };

/** 一个字都不打、只甩图过来时给模型的那句话：只说上传了什么、走的哪条通道，不替它判断内容。 */
function attachmentFallback(attachments: Attachment[]): string {
  const count = attachments.reduce((sum, each) => sum + each.images.length, 0);
  return `我刚上传了 ${count} 张图片（持仓截图导入通道）`;
}

/** 用户那一句的底色：DeepSeek 式的浅蓝，不用实心蓝是因为白字在浅背景上读不动。 */
const USER_BUBBLE = 'rgba(37, 99, 235, 0.10)';

const SUGGESTIONS = ['我的持仓今天怎么样？', '帮我把自选里的基金排个序', '对比一下我持有的两只 QDII'];

/**
 * 一条消息。借 DeepSeek 的排版：助手的回答不套气泡，直接铺在页面上，
 * 只有用户那一句是右侧一块浅色——长回答读起来不像在被逐条"回话"。
 */
function Message({ role, content, streaming, failed, onRetry, label }: {
  role: string;
  content: string;
  streaming?: boolean;
  failed?: string;
  onRetry?: () => void;
  label?: string;
}) {
  if (role === 'user') {
    return (
      <View
        style={{
          alignSelf: 'flex-end',
          maxWidth: '86%',
          marginBottom: 16,
          backgroundColor: USER_BUBBLE,
          borderRadius: 16,
          paddingHorizontal: 14,
          paddingVertical: 9,
        }}
      >
        <Text style={{ fontSize: 15, lineHeight: 23, color: theme.text }} selectable>
          {content}
        </Text>
      </View>
    );
  }
  return (
    <View style={{ marginBottom: 20 }}>
      {label ? <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 6 }}>{label}</Text> : null}
      {content ? <MarkdownText content={content} /> : null}
      {streaming && !content ? (
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

  /** 没有当前会话时先建一条；附件要在发消息之前拿到这个号去换令牌。 */
  async function ensureActiveSession(): Promise<string> {
    if (sessionId) return sessionId;
    const created = await createSession.mutateAsync();
    setSessionId(created.session_id);
    return created.session_id;
  }

  const chat = useAgentChat({ sessionId, ensureSession: ensureActiveSession });

  const contextCode = paramCode && !contextDismissed ? paramCode : null;

  const accounts = useAccounts();
  const upload = useUploadChatScreenshots();
  const decide = useDecideChatImport(sessionId);
  const pending = usePendingChatAction(sessionId);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const canSend = !uploading && (Boolean(draft.trim()) || attachments.length > 0);
  // 回答上面标一句"是谁说的"：档案名是用户自己起的，标的是它底下那个模型号。
  const profiles = useLlmProfiles();
  const assistantLabel = profiles.data?.profiles.find((each) => each.name === profiles.data?.active)?.model;

  /** 顶部导航选中的账户优先；汇总视图下落到第一个账户（与导入页同一口径）。 */
  function targetAccountId(): number | null {
    return viewAccountId ?? accounts.data?.items[0]?.id ?? null;
  }

  async function pickAttachments() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setProblem('没有相册权限，无法选图');
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
    setAttachments((prev) => [...prev, { key: `${Date.now()}-${prev.length}`, images }]);
  }

  /** 一次发送里每选一批是一个批次，各自换回一个后端校验得到的批次号。 */
  async function uploadAttachments(active: string): Promise<string[]> {
    if (!attachments.length) return [];
    const accountId = targetAccountId();
    if (!accountId) throw new Error('还没有账户，先去「我的 → 账户管理」建一个');
    const ids: string[] = [];
    for (const each of attachments) {
      const accepted = await upload.mutateAsync({ sessionId: active, accountId, images: each.images });
      ids.push(String(accepted.import_id));
    }
    return ids;
  }

  async function ask(text: string) {
    if (chat.sending || uploading) return;
    const trimmed = text.trim();
    const body = trimmed || (attachments.length ? attachmentFallback(attachments) : '');
    if (!body) return;
    setProblem(null);
    setUploading(true);
    let importIds: string[] = [];
    try {
      importIds = await uploadAttachments(await ensureActiveSession());
    } catch (error: unknown) {
      // 附件没传上去就先把话说出去，模型拿不到批次号，所以整条不发。
      setUploading(false);
      setProblem(describeError(error));
      return;
    }
    setUploading(false);
    setDraft('');
    setAttachments([]);
    // 后端只有一条自由文本的通道，基金上下文只能写在消息里；附件不是文本，
    // 它走 `holding_import_ids` 这个结构化字段，工具才拿得到真实批次号。
    const name = context.data?.fund_name;
    const question = contextCode ? `（我正在看基金 ${contextCode}${name ? ` ${name}` : ''}）\n${body}` : body;
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
            contentContainerStyle={{ padding: theme.gap, paddingTop: 16, paddingBottom: 16 }}
            keyboardShouldPersistTaps="handled"
            onContentSizeChange={() => scroller.current?.scrollToEnd({ animated: true })}
          >
            {!chat.turns.length ? (
              <View style={{ paddingTop: 36 }}>
                <Text style={{ fontSize: 21, fontWeight: '700', color: theme.text, textAlign: 'center' }}>你好，我是基金助手</Text>
                <Text style={{ fontSize: 14, lineHeight: 22, color: theme.textMuted, textAlign: 'center', marginTop: 8, paddingHorizontal: 16 }}>
                  可以问我的持仓、我的自选、某一只基金，{'\n'}或者让它对比两只。
                </Text>
                <View style={{ alignItems: 'center', marginTop: 22, gap: 8 }}>
                  {SUGGESTIONS.map((item) => (
                    <Pressable
                      key={item}
                      accessibilityRole="button"
                      onPress={() => setDraft(item)}
                      style={{ paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surface }}
                    >
                      <Text style={{ fontSize: 14, color: theme.textMuted }}>{item}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            ) : null}
            {chat.turns.map((turn, index) => (
              <Message
                key={`${index}-${turn.role}`}
                role={turn.role}
                content={turn.content}
                streaming={turn.state === 'streaming'}
                failed={turn.state === 'failed' ? turn.error : undefined}
                onRetry={chat.retry}
                label={turn.role === 'assistant' ? assistantLabel : undefined}
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

        <View
          style={{
            backgroundColor: theme.surface,
            borderTopWidth: 1,
            borderTopColor: theme.border,
            paddingHorizontal: theme.gap,
            paddingTop: 8,
            paddingBottom: Platform.OS === 'web' ? 12 : 20,
          }}
        >
          {attachments.length ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 8, gap: 8 }}>
              {attachments.map((item) => (
                <View
                  key={item.key}
                  style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: theme.background, borderRadius: 999, paddingLeft: 10, paddingVertical: 4 }}
                >
                  <Text style={{ fontSize: 12, color: theme.textMuted }}>图片 {item.images.length} 张</Text>
                  <Pressable accessibilityRole="button" accessibilityLabel="不带这个附件" hitSlop={8} disabled={uploading} onPress={() => setAttachments((prev) => prev.filter((each) => each.key !== item.key))}>
                    <Text style={{ fontSize: 12, color: theme.textFaint, marginLeft: 6 }}>✕</Text>
                  </Pressable>
                </View>
              ))}
            </View>
          ) : null}

          <View
            style={{
              flexDirection: 'row',
              alignItems: 'flex-end',
              backgroundColor: theme.background,
              borderWidth: 1,
              borderColor: theme.border,
              borderRadius: 22,
              padding: 6,
            }}
          >
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="添加附件"
              hitSlop={10}
              onPress={() => void pickAttachments()}
              disabled={uploading || chat.sending}
              style={{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', opacity: uploading || chat.sending ? 0.4 : 1 }}
            >
              {uploading ? (
                <ActivityIndicator size="small" color={theme.primary} />
              ) : (
                <SymbolView name={{ ios: 'plus', android: 'add', web: 'add' }} tintColor={theme.textMuted} size={19} />
              )}
            </Pressable>
            <TextInput
              value={draft}
              onChangeText={setDraft}
              placeholder={attachments.length ? '想问它什么都行，可以只发附件' : contextCode ? `问问 ${contextCode}…` : '想问什么都行'}
              placeholderTextColor={theme.textFaint}
              maxLength={3000}
              multiline
              onSubmitEditing={() => void ask(draft)}
              returnKeyType="send"
              blurOnSubmit={false}
              style={{
                flex: 1,
                maxHeight: 112,
                minHeight: 34,
                paddingHorizontal: 8,
                paddingVertical: 6,
                fontSize: 15,
                lineHeight: 22,
                color: theme.text,
                backgroundColor: 'transparent',
                textAlignVertical: 'top',
              }}
            />
            {chat.sending ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="停止生成"
                onPress={chat.stop}
                style={{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.primary }}
              >
                <SymbolView name={{ ios: 'stop.fill', android: 'stop', web: 'stop' }} tintColor="#FFFFFF" size={15} />
              </Pressable>
            ) : (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="发送"
                disabled={!canSend}
                onPress={() => void ask(draft)}
                style={{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', marginLeft: 6, backgroundColor: canSend ? theme.primary : theme.border }}
              >
                <SymbolView name={{ ios: 'arrow.up', android: 'arrow_upward', web: 'arrow_upward' }} tintColor="#FFFFFF" size={17} />
              </Pressable>
            )}
          </View>
        </View>
      </KeyboardAvoidingView>
      {sessionsOpen ? (
        <AgentSessionsPanel activeSessionId={sessionId} onPick={setSessionId} onClose={closeSessions} />
      ) : null}
    </Screen>
  );
}
