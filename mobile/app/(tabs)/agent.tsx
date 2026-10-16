import { SymbolView } from 'expo-symbols';
import { useLocalSearchParams } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  ActivityIndicator,
  Easing,
  KeyboardAvoidingView,
  type NativeSyntheticEvent,
  type NativeScrollEvent,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  Text,
  View,
} from 'react-native';

import { ErrorState, describeError } from '@/components/states';
import { AgentSessionsPanel } from '@/components/AgentSessionsPanel';
import { FundPickerSheet } from '@/components/FundPickerSheet';
import { FundSelectionCard } from '@/components/FundSelectionCard';
import { HoldingImportFlowCard } from '@/components/HoldingImportFlowCard';
import { MarkdownText } from '@/components/MarkdownText';
import { Screen, Card, Button } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useCreateAgentSession } from '@/hooks/useAgent';
import { useAgentChat } from '@/hooks/useAgentChat';
import { useAdvanceChatImport, useChatImportProgress, useDecideChatImport, usePendingChatAction, useUploadChatScreenshots } from '@/hooks/useChatImport';
import { useFundDetail } from '@/hooks/useFunds';
import { useLlmProfiles } from '@/hooks/useLlmProfiles';
import { useUiStore } from '@/stores/ui';
import type { PickedImage } from '@/hooks/useImports';
import { composeResearchQuestion, researchFollowupLabel, type PickerFund, type ResearchTier } from '@/utils/fundPicker';
import { describeRoleOutcomes } from '@/utils/researchProgress';

/** 选完只留在本地，随问题发送附件；识别由后端子图启动。 */
type Attachment = { key: string; images: PickedImage[] };

/** 一个字都不打、只甩图过来时给模型的那句话：只说上传了什么、走的哪条通道，不替它判断内容。 */
function attachmentFallback(attachments: Attachment[]): string {
  const count = attachments.reduce((sum, each) => sum + each.images.length, 0);
  return `我刚上传了 ${count} 张图片。`;
}

/** 用户那一句的底色：DeepSeek 式的浅蓝，不用实心蓝是因为白字在浅背景上读不动。 */
const USER_BUBBLE = 'rgba(37, 99, 235, 0.10)';

const SUGGESTIONS = ['我的持仓今天怎么样？', '帮我把自选里的基金排个序', '对比一下我持有的两只 QDII'];

/** 距底部多少像素以内算"在看最新内容"，只有在这个范围内才跟随流式输出往下滚。 */
const STICK_TO_BOTTOM_PX = 80;

/** 骨架灰：比边框深一点、比正文浅很多，读起来是"这里要有内容"而不是"这是内容"。 */
const SKELETON_BG = 'rgba(17, 24, 39, 0.06)';

/**
 * 读历史的骨架屏：按真实排版铺一段对话轮廓（用户一句浅蓝气泡在右、
 * 小镜的回答是几行不套气泡的灰条），整块缓慢呼吸。
 *
 * 不换成页面正中一个转圈：那既不知道在等什么，消息到了还会把转圈顶走、
 * 整屏跳一下。骨架占的位置就是内容将出现的位置。
 */
function ChatSkeleton({ label }: { label: string }) {
  const [breath] = useState(() => new Animated.Value(0.55));

  useEffect(() => {
    const pulse = (toValue: number) =>
      Animated.timing(breath, {
        toValue,
        duration: 760,
        easing: Easing.inOut(Easing.quad),
        // react-native-web 没有 native driver：开着它动画不跑。
        useNativeDriver: Platform.OS !== 'web',
      });
    const loop = Animated.loop(Animated.sequence([pulse(1), pulse(0.55)]));
    loop.start();
    return () => loop.stop();
  }, [breath]);

  /** 高 12 的是回答的行，高 34 的是用户那句气泡；圆角取高度一半。 */
  const block = (width: `${number}%`, height: number, gap: number, side?: 'flex-end') => (
    <View style={{ width, height, borderRadius: height / 2, backgroundColor: SKELETON_BG, marginBottom: gap, alignSelf: side }} />
  );

  return (
    <View accessibilityRole="progressbar" accessibilityLabel={label} accessibilityState={{ busy: true }}>
      <Animated.View style={{ opacity: breath, padding: theme.gap, paddingTop: 16 }}>
        {block('46%', 34, 20, 'flex-end')}
        {block('82%', 12, 9)}
        {block('67%', 12, 9)}
        {block('41%', 12, 26)}
        {block('31%', 34, 20, 'flex-end')}
        {block('74%', 12, 9)}
        {block('52%', 12, 0)}
      </Animated.View>
      <Text style={{ fontSize: 12, color: theme.textFaint, textAlign: 'center' }}>{label}</Text>
    </View>
  );
}

/**
 * 一条消息。借 DeepSeek 的排版：助手的回答不套气泡，直接铺在页面上，
 * 只有用户那一句是右侧一块浅色——长回答读起来不像在被逐条"回话"。
 */
function Message({ role, content, streaming, failed, onRetry, label, onResearch, researchDisabled, researchProgress, researchActivity, researchBadge, researchLabel }: {
  role: string;
  content: string;
  streaming?: boolean;
  failed?: string;
  onRetry?: () => void;
  label?: string;
  onResearch?: () => void;
  researchDisabled?: boolean;
  researchProgress?: string;
  researchActivity?: string;
  researchBadge?: string;
  researchLabel: string;
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
      {streaming && (researchActivity || researchProgress) ? (
        // 一行空间：有思考摘要时优先它，否则退回阶段进度。服务端已截尾压平，这里不再折行。
        <Text accessibilityLiveRegion="polite" numberOfLines={1} style={{ fontSize: 13, color: theme.textMuted, marginTop: 8 }}>
          {researchActivity ?? researchProgress}
        </Text>
      ) : null}
      {researchBadge ? (
        <Text numberOfLines={1} style={{ fontSize: 13, color: researchBadge.includes('失败') || researchBadge.includes('未完成') ? theme.danger : theme.textMuted, marginTop: 8 }}>
          {researchBadge}
        </Text>
      ) : null}
      {streaming && !content ? (
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <ActivityIndicator color={theme.primary} size="small" />
          <Text style={{ fontSize: 14, color: theme.textMuted, marginLeft: 8 }}>{researchProgress ? '多角色研究进行中…' : '正在思考…'}</Text>
        </View>
      ) : null}
      {onResearch ? (
        <Text
          accessibilityRole="link"
          accessibilityState={{ disabled: Boolean(researchDisabled) }}
          onPress={researchDisabled ? undefined : onResearch}
          style={{
            alignSelf: 'flex-start',
            marginTop: 10,
            paddingVertical: 4,
            fontSize: 14,
            color: researchDisabled ? theme.textFaint : theme.primary,
            textDecorationLine: 'underline',
          }}
        >
          {researchLabel}
        </Text>
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
  const createSession = useCreateAgentSession();
  /**
   * 只认这一次访问里显式选过的会话：进来就是空白新对话，要看历史从左上角面板挑。
   *
   * 之前兜底到"服务端最新一条"，于是每次刷新都接着上次的话头，而不是他要求的
   * 新对话。空白会话不在服务端建档 —— 第一条消息（或第一个附件）发出去时
   * 才由 ensureActiveSession 建出来。
   */
  const sessionId = storedSessionId;

  const context = useFundDetail(paramCode ?? null);
  const [contextDismissed, setContextDismissed] = useState(false);
  /** 选基金面板：多选 1~3 只后直接发起分析/对比。 */
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const scroller = useRef<ScrollView>(null);
  // 流式回答时"贴底才跟随"：contentSize 每个 token 都会变，无条件 scrollToEnd 会把
  // 已经往上翻着看历史的人一遍遍拽回末尾。用户滚回底部后自动恢复跟随。
  const atBottom = useRef(true);
  const lastContentHeight = useRef(0);
  const [offBottomDuringStream, setOffBottomDuringStream] = useState(false);
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

  function trackScroll(event: NativeSyntheticEvent<NativeScrollEvent>) {
    const { contentSize, layoutMeasurement, contentOffset } = event.nativeEvent;
    // 一条回答收尾时会先塌一下（本地这条撤掉、服务端历史还没重取回来）再长回来。
    // 塌陷那几帧的 contentOffset 是被系统夹出来的，不是用户翻的，据此放手会把
    // 刚说完的话顶出视野。
    if (contentSize.height < lastContentHeight.current - 1) return;
    // 内容不满一屏时这个差值是负的——本来就没历史可翻，当作在看最新。
    const distanceToBottom = contentSize.height - layoutMeasurement.height - contentOffset.y;
    const nearBottom = distanceToBottom <= STICK_TO_BOTTOM_PX;
    if (nearBottom !== atBottom.current) {
      atBottom.current = nearBottom;
      setOffBottomDuringStream(!nearBottom);
    }
  }

  /**
   * 只在内容**长高**时往下贴：塌回去（换会话、历史重取把整列重建）也走这个回调，
   * 那时跟着滚就是用户看到的"莫名其妙从头扫到底"。
   */
  function followIfAtBottom(_width: number, height: number) {
    const grew = height > lastContentHeight.current + 1;
    lastContentHeight.current = height;
    if (!atBottom.current || !grew) return;
    // animated: false：跟随每个 token 都开一次动画，观感就是一段段往下滑。
    scroller.current?.scrollToEnd({ animated: false });
  }

  function stickToBottom() {
    atBottom.current = true;
    setOffBottomDuringStream(false);
    scroller.current?.scrollToEnd({ animated: true });
  }

  const upload = useUploadChatScreenshots();
  const decide = useDecideChatImport(sessionId);
  const currentSession = useRef(sessionId);
  useEffect(() => { currentSession.current = sessionId; }, [sessionId]);
  const pending = usePendingChatAction(sessionId);
  const advance = useAdvanceChatImport(sessionId);
  const review = chat.review ?? pending.data?.pending_action ?? null;
  const processing = review?.kind === 'holding_import_processing' ? review : null;
  const progress = useChatImportProgress(sessionId, processing?.import_id ?? null);
  const lastAdvance = useRef<string | null>(null);
  const { mutate: advanceImport, isPending: advancing } = advance;
  const { setReview, history: chatHistory } = chat;
  const { refetch: refetchChatHistory } = chatHistory;
  const { refetch: refetchPending } = pending;

  useEffect(() => {
    if (!sessionId || !processing?.interrupt_id || !progress.data || advancing) return;
    if (['UPLOADED', 'PARSING'].includes(progress.data.import_batch.status)) return;
    const key = `${sessionId}:${processing.import_id}:${processing.interrupt_id}`;
    const active = sessionId;
    if (lastAdvance.current === key) return;
    lastAdvance.current = key;
    advanceImport({ importId: processing.import_id, interruptId: processing.interrupt_id }, {
      onSuccess: (result) => { if (currentSession.current !== active) return; setReview(result.pending_action ?? null); void refetchChatHistory(); },
      onError: (error) => { if (currentSession.current !== active) return; setReview(null); setProblem(describeError(error)); void refetchPending(); },
    });
  }, [sessionId, processing, progress.data, advancing, advanceImport, setReview, refetchChatHistory, refetchPending]);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const canSend = !uploading && !advance.isPending && !decide.isPending
    && (!review || ((review.kind === 'holding_import_account' || review.kind === 'human_question') && !attachments.length))
    && (Boolean(draft.trim()) || attachments.length > 0);
  // 回答上面标一句"是谁说的"：档案名是用户自己起的，标的是它底下那个模型号。
  const profiles = useLlmProfiles();
  const assistantLabel = profiles.data?.profiles.find((each) => each.name === profiles.data?.active)?.model;

  async function pickAttachments() {
    if (review || uploading || chat.sending) return;
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
    const ids: string[] = [];
    for (const each of attachments) {
      const accepted = await upload.mutateAsync({ sessionId: active, images: each.images });
      ids.push(String(accepted.import_id));
    }
    return ids;
  }

  async function ask(text: string) {
    if (chat.sending || !canSend) return;
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
    // 自己刚发的话得看得见：先把跟随打开，下一帧贴到底部。
    atBottom.current = true;
    setOffBottomDuringStream(false);
    void chat.send(question, importIds).catch((error: unknown) => setProblem(describeError(error)));
    requestAnimationFrame(stickToBottom);
  }

  /**
   * 基金页带过来的上下文里直接发起多智能体研究。
   *
   * 代码走 `research_fund_codes` 这个结构化字段，由后端当作"用户点按钮"的授权，
   * 不靠模型自己决定要不要多花几倍 token；消息正文仍然照常展示，也保证后端在结构化
   * 字段缺失时仍能按原文规则识别。
   */
  function startMultiRoleResearch() {
    if (!contextCode || chat.sending || uploading || review || pending.data?.continuation) return;
    const name = context.data?.fund_name;
    void runResearch([{ code: contextCode, name: name ?? '' }], 'multi_role');
  }

  /**
   * 把选中的基金发成一次研究请求：正文给人看，代码和成本档位走结构化字段。
   *
   * 不能只靠正文让后端的文本规则去猜：基金名里常带"股票/行业/主题"，那些词会让
   * 规则直接放弃对比路由，结果就是点了「对比分析」却变成单基金研究。
   */
  function runResearch(funds: PickerFund[], tier: ResearchTier) {
    if (!funds.length || chat.sending || uploading || review || pending.data?.continuation) return;
    setPickerOpen(false);
    atBottom.current = true;
    setOffBottomDuringStream(false);
    void chat
      .send(composeResearchQuestion(funds), [], undefined, { codes: funds.map((fund) => fund.code), strategy: tier })
      .catch((error: unknown) => setProblem(describeError(error)));
    requestAnimationFrame(stickToBottom);
  }

  function decideImport(decision: 'confirm' | 'cancel') {
    const review = chat.review ?? pending.data?.pending_action ?? null;
    if (!review || review.kind === 'fund_selection' || review.kind === 'human_question') return;
    const active = sessionId;
    setProblem(null);
    decide.mutate(
      {
        importId: String(review.import_id),
        decision,
        interruptId: review.interrupt_id ?? '',
        reviewDigest: review.kind === 'holding_import_review' ? review.review_digest : undefined,
      },
      {
        onSuccess: (result) => {
          if (currentSession.current !== active) return;
          chat.setReview(result.pending_action ?? null);
          void pending.refetch();
          // 决策会恢复 Agent 并让它接着说话，所以历史要重取一次。
          void chat.history.refetch();
        },
        onError: (error) => { if (currentSession.current !== active) return; chat.setReview(null); setProblem(describeError(error)); void pending.refetch(); void chat.history.refetch(); },
      },
    );
  }

  function chooseFund(fundCode?: string) {
    if (review?.kind !== 'fund_selection' || !review.interrupt_id || chat.sending) return;
    const active = sessionId;
    setProblem(null);
    atBottom.current = true;
    setOffBottomDuringStream(false);
    void chat.resume({ kind: 'fund_selection', interruptId: review.interrupt_id, fundCode }).catch((error: unknown) => {
      if (currentSession.current === active) setProblem(describeError(error));
    });
    requestAnimationFrame(stickToBottom);
  }

  function continueOriginalTask() {
    const action = pending.data?.continuation;
    if (!action || !sessionId || chat.sending) return;
    const active = sessionId;
    setProblem(null);
    atBottom.current = true;
    setOffBottomDuringStream(false);
    void chat.resume({ kind: 'continue', turnId: action.turn_id }).catch((error: unknown) => {
      if (currentSession.current === active) setProblem(describeError(error));
    });
    requestAnimationFrame(stickToBottom);
  }

  function continueImport(accountId?: number) {
    if (!review?.interrupt_id || review.kind === 'fund_selection' || review.kind === 'human_question') return;
    const active = sessionId;
    setProblem(null);
    if (review.kind === 'holding_import_processing'
      && (!progress.data || ['UPLOADED', 'PARSING'].includes(progress.data.import_batch.status))) {
      void progress.refetch();
      return;
    }
    advance.mutate({ importId: review.import_id, interruptId: review.interrupt_id, accountId }, {
      onSuccess: (result) => { if (currentSession.current !== active) return; chat.setReview(result.pending_action ?? null); void pending.refetch(); void chat.history.refetch(); },
      onError: (error) => { if (currentSession.current !== active) return; chat.setReview(null); setProblem(describeError(error)); void pending.refetch(); void chat.history.refetch(); },
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
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="对这只基金发起多智能体研究"
                hitSlop={8}
                disabled={chat.sending || uploading || Boolean(review) || Boolean(pending.data?.continuation)}
                onPress={startMultiRoleResearch}
              >
                <Text style={{ fontSize: 12, color: theme.warning, marginLeft: 10 }}>多智能体分析</Text>
              </Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel="不带这个上下文" hitSlop={8} onPress={() => setContextDismissed(true)}>
                <Text style={{ fontSize: 12, color: theme.warning, marginLeft: 6 }}>✕</Text>
              </Pressable>
            </View>
          ) : null}
        </View>

        {chat.loadingHistory ? (
          // 只有真选中了某条会话才有"读历史"这回事：空白新对话直接落在那张
          // 问候页上，不先转一下骨架屏。
          <ChatSkeleton label="正在读历史…" />
        ) : chat.historyError && !chat.turns.length ? (
          <ErrorState message={describeError(chat.historyError)} onRetry={chat.retryHistory} />
        ) : (
          <ScrollView
            ref={scroller}
            contentContainerStyle={{ padding: theme.gap, paddingTop: 16, paddingBottom: 16 }}
            keyboardShouldPersistTaps="handled"
            onScroll={trackScroll}
            scrollEventThrottle={16}
            onContentSizeChange={followIfAtBottom}
          >
            {!chat.turns.length ? (
              <View style={{ paddingTop: 36 }}>
                <Text style={{ fontSize: 21, fontWeight: '700', color: theme.text, textAlign: 'center' }}>你好，我是小镜</Text>
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
                researchProgress={turn.researchProgress}
                researchActivity={turn.researchActivity}
                researchBadge={turn.role === 'assistant'
                  ? describeRoleOutcomes(turn.research_roles ?? (turn.state === 'streaming' ? chat.researchOutcomes : []), turn.research_review_status)
                  : undefined}
                researchDisabled={chat.sending || uploading || Boolean(review) || Boolean(pending.data?.continuation)}
                researchLabel={researchFollowupLabel(turn.research_intent)}
                onResearch={turn.role === 'assistant' && turn.research_id ? () => {
                  void chat.send(researchFollowupLabel(turn.research_intent), [], turn.research_id ?? undefined)
                    .catch((error: unknown) => setProblem(describeError(error)));
                } : undefined}
              />
            ))}
            {problem ? <Text style={{ fontSize: 13, color: theme.danger, marginBottom: 8 }}>{problem}</Text> : null}
          </ScrollView>
        )}

        {chat.sending && offBottomDuringStream ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="回到最新回答"
            onPress={stickToBottom}
            style={{
              position: 'absolute',
              right: theme.gap + 6,
              bottom: 108,
              zIndex: 6,
              paddingHorizontal: 14,
              paddingVertical: 8,
              borderRadius: 999,
              borderWidth: 1,
              borderColor: theme.border,
              backgroundColor: theme.surface,
            }}
          >
            <Text style={{ fontSize: 13, color: theme.primary }}>回到最新 ↓</Text>
          </Pressable>
        ) : null}

        {!review && pending.data?.continuation ? <View style={{ paddingHorizontal: theme.gap, paddingTop: theme.gap }}>
          <Card>
            <Text style={{ color: theme.text, fontSize: 14, fontWeight: '600' }}>继续原任务</Text>
            {pending.data.continuation.selected_fund_code ? <Text style={{ color: theme.primary, fontSize: 12, marginTop: 6 }}>
              {pending.data.continuation.selected_fund_name} · {pending.data.continuation.selected_fund_code}
            </Text> : null}
            <Text style={{ color: theme.textMuted, fontSize: 12, lineHeight: 18, marginVertical: 8 }}>{pending.data.continuation.notice}</Text>
            <Button label={chat.sending ? '正在继续…' : '继续已确认的任务'} disabled={chat.sending || decide.isPending || advance.isPending} onPress={continueOriginalTask} />
          </Card>
        </View> : null}
        {review ? (
          <View style={{ paddingHorizontal: theme.gap, paddingTop: theme.gap }}>
            {review.kind === 'fund_selection' ? (
              <FundSelectionCard action={review} busy={chat.sending} onSelect={chooseFund} onCancel={() => chooseFund()} />
            ) : review.kind === 'human_question' ? <Card>
              <Text style={{ color: theme.text, fontSize: 14 }}>{review.question}</Text>
              <Text style={{ color: theme.textMuted, fontSize: 12, marginTop: 8 }}>{review.notice}</Text>
            </Card> : <HoldingImportFlowCard action={review} busy={advance.isPending || decide.isPending}
              decision={decide.isPending ? decide.variables.decision : null}
              onAccount={(accountId) => continueImport(accountId)} onContinue={() => continueImport()} onDecide={decideImport} />}
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
              accessibilityLabel="选择基金发起研究"
              hitSlop={10}
              onPress={() => setPickerOpen(true)}
              disabled={chat.sending || uploading || Boolean(review)}
              style={{ minWidth: 34, height: 34, borderRadius: 17, paddingHorizontal: 8, alignItems: "center", justifyContent: "center", opacity: chat.sending || uploading || review ? 0.4 : 1 }}
            >
              <Text style={{ fontSize: 12, color: theme.textMuted }}>选基金</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="添加附件"
              hitSlop={10}
              onPress={() => void pickAttachments()}
              disabled={uploading || chat.sending || Boolean(review)}
              style={{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', opacity: uploading || chat.sending || review ? 0.4 : 1 }}
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

      {/* 只在打开时挂载：否则聊天页每次进来都会白拉一次持仓和自选列表。 */}
      {pickerOpen ? <FundPickerSheet visible busy={chat.sending} onClose={() => setPickerOpen(false)} onConfirm={runResearch}/> : null}
    </Screen>
  );
}
