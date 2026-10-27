'use client';

import {
  type KeyboardEvent,
  type SyntheticEvent,
  Suspense,
  lazy,
  memo,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import Image from 'next/image';
import {
  AlertCircle,
  ArrowUp,
  Check,
  CheckCircle2,
  ChevronDown,
  LineChart,
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  Star,
  Trash2,
  UserRound,
  Wallet,
  X,
} from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  type ChatMessage,
  type LlmProfiles,
  type Session,
  type UserProfile,
  clearMessages,
  createSession,
  deleteSession,
  getLlmProfiles,
  getCurrentUser,
  getMessages,
  healthCheck,
  listSessions,
  login,
  register,
  streamMessage,
  switchLlmProfile,
} from '@/lib/api';
import type { TradeOperation } from '@/lib/fund-api';

const AccountsPage = lazy(() =>
  import('@/components/pages/accounts-page').then((module) => ({
    default: module.AccountsPage,
  })),
);
const AutoInvestPage = lazy(() =>
  import('@/components/pages/auto-invest-page').then((module) => ({
    default: module.AutoInvestPage,
  })),
);
const FundDetailPage = lazy(() =>
  import('@/components/pages/fund-detail-page').then((module) => ({
    default: module.FundDetailPage,
  })),
);
const ImportPage = lazy(() =>
  import('@/components/pages/import-page').then((module) => ({
    default: module.ImportPage,
  })),
);
const ImportReviewPage = lazy(() =>
  import('@/components/pages/import-review-page').then((module) => ({
    default: module.ImportReviewPage,
  })),
);
const MarketDetailPage = lazy(() =>
  import('@/components/pages/market-detail-page').then((module) => ({
    default: module.MarketDetailPage,
  })),
);
const MarketPage = lazy(() =>
  import('@/components/pages/market-page').then((module) => ({
    default: module.MarketPage,
  })),
);
const NavHistoryPage = lazy(() =>
  import('@/components/pages/nav-history-page').then((module) => ({
    default: module.NavHistoryPage,
  })),
);
const PersonaPage = lazy(() =>
  import('@/components/pages/persona-page').then((module) => ({
    default: module.PersonaPage,
  })),
);
const PortfolioPage = lazy(() =>
  import('@/components/pages/portfolio-page').then((module) => ({
    default: module.PortfolioPage,
  })),
);
const PositionEditPage = lazy(() =>
  import('@/components/pages/position-edit-page').then((module) => ({
    default: module.PositionEditPage,
  })),
);
const ProfileEditPage = lazy(() =>
  import('@/components/pages/profile-edit-page').then((module) => ({
    default: module.ProfileEditPage,
  })),
);
const ProfilePage = lazy(() =>
  import('@/components/pages/profile-page').then((module) => ({
    default: module.ProfilePage,
  })),
);
const TradePage = lazy(() =>
  import('@/components/pages/trade-page').then((module) => ({
    default: module.TradePage,
  })),
);
const TransactionsPage = lazy(() =>
  import('@/components/pages/transactions-page').then((module) => ({
    default: module.TransactionsPage,
  })),
);
const WatchlistGroupsPage = lazy(() =>
  import('@/components/pages/watchlist-groups-page').then((module) => ({
    default: module.WatchlistGroupsPage,
  })),
);
const WatchlistPage = lazy(() =>
  import('@/components/pages/watchlist-page').then((module) => ({
    default: module.WatchlistPage,
  })),
);
const ComparisonCard = lazy(() =>
  import('@/components/comparison-card').then((module) => ({
    default: module.ComparisonCard,
  })),
);
const ResearchCopy = lazy(() =>
  import('@/components/research-copy').then((module) => ({
    default: module.ResearchCopy,
  })),
);
const AccountDialog = lazy(() =>
  import('@/components/account-dialog').then((module) => ({
    default: module.AccountDialog,
  })),
);
const LlmSettingsDialog = lazy(() =>
  import('@/components/llm-settings').then((module) => ({
    default: module.LlmSettingsDialog,
  })),
);

const PRELOAD_PAGES: Partial<Record<MainView, () => Promise<unknown>>> = {
  portfolio: () => import('@/components/pages/portfolio-page'),
  watchlist: () => import('@/components/pages/watchlist-page'),
  market: () => import('@/components/pages/market-page'),
  profile: () => import('@/components/pages/profile-page'),
};

type StoredAuth = {
  token: string;
  user: UserProfile;
};

type MainView = 'agent' | 'portfolio' | 'watchlist' | 'market' | 'profile';

type AppView =
  | MainView
  | 'fund'
  | 'accounts'
  | 'transactions'
  | 'auto-invest'
  | 'watchlist-groups'
  | 'import'
  | 'import-review'
  | 'persona'
  | 'profile-edit'
  | 'market-detail'
  | 'position-edit'
  | 'trade'
  | 'nav-history';

const APP_NAV: Array<{
  key: MainView;
  label: string;
  hint: string;
  icon: typeof Wallet;
}> = [
  { key: 'portfolio', label: '持仓', hint: '账户与资产', icon: Wallet },
  { key: 'watchlist', label: '自选', hint: '持续观察', icon: Star },
  { key: 'market', label: '行情', hint: '大盘与板块', icon: LineChart },
  { key: 'agent', label: '小镜', hint: '研究与对话', icon: Sparkles },
  { key: 'profile', label: '我的', hint: '设置与账号', icon: UserRound },
];

type WebMcpTool = {
  name: string;
  title: string;
  description: string;
  inputSchema: Record<string, unknown>;
  annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
  execute(input: unknown): Promise<unknown>;
};

declare global {
  interface Document {
    readonly modelContext?: {
      registerTool(
        tool: WebMcpTool,
        options?: { signal?: AbortSignal },
      ): void | Promise<void>;
    };
  }
}

const AUTH_STORAGE_KEY = 'fund-agent-auth';

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作失败，请稍后重试';
}

function PageFallback() {
  return (
    <div className="grid min-h-60 place-items-center px-6 py-16">
      <div className="flex items-center gap-2.5 text-xs text-text-faint">
        <RefreshCw className="size-3.5 animate-spin text-primary" />
        正在打开页面…
      </div>
    </div>
  );
}

function MascotImage({
  src = '/xiaojing-avatar.png',
  alt = '',
  size,
  className,
}: {
  src?: string;
  alt?: string;
  size: number;
  className?: string;
}) {
  return (
    <Image
      src={src}
      alt={alt}
      width={size}
      height={size}
      unoptimized
      className={className}
    />
  );
}

function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated: (auth: StoredAuth) => void;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');

    try {
      if (mode === 'register') {
        const response = await register({
          email,
          password,
          username: username.trim() || undefined,
        });
        onAuthenticated({
          token: response.token.access_token,
          user: {
            id: response.id,
            email: response.email,
            username: response.username,
          },
        });
        return;
      }

      const token = await login(email, password);
      const user = await getCurrentUser(token.access_token);
      onAuthenticated({ token: token.access_token, user });
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden lg:grid lg:grid-cols-[1.08fr_minmax(440px,0.92fr)]">
      <section className="relative hidden min-h-screen overflow-hidden border-r border-border bg-[#edece0] lg:flex lg:flex-col lg:justify-between">
        <div
          aria-hidden="true"
          className="absolute inset-0 [background:radial-gradient(circle_at_16%_10%,rgba(47,112,87,.11),transparent_32%),radial-gradient(circle_at_84%_86%,rgba(128,99,51,.12),transparent_30%)]"
        />
        <div className="relative flex items-center gap-3 px-12 pt-12 xl:px-16">
          <MascotImage
            size={44}
            className="size-11 rounded-[14px] border border-border object-cover"
          />
          <div>
            <p className="text-sm font-semibold tracking-[0.18em] text-primary">
              持见
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              小镜 · 你的基金研究搭子
            </p>
          </div>
        </div>

        <div className="relative grid items-center gap-4 px-12 xl:grid-cols-[1fr_280px] xl:px-16">
          <div className="max-w-xl">
            <p className="font-display text-sm tracking-[0.28em] text-gold">
              把持仓问明白
            </p>
            <h1 className="font-display mt-5 max-w-xl text-5xl font-semibold leading-[1.18] tracking-[-0.02em] text-foreground xl:text-6xl">
              把选择
              <br />
              看清楚。
            </h1>
            <p className="mt-7 max-w-lg text-[15px] leading-8 text-text-soft">
              查持仓、读自选、比基金。也可以直接发起一次多智能体研究，让不同视角把问题说透。
            </p>
            <div className="mt-10 flex flex-wrap gap-2">
              {['持仓体检', '自选扫描', '基金对比', '多智能体'].map((item) => (
                <span
                  key={item}
                  className="rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground"
                >
                  {item}
                </span>
              ))}
            </div>
          </div>
          <div className="hidden size-[300px] items-center justify-center rounded-[40px] border border-border bg-card/55 p-5 shadow-[0_18px_40px_rgba(33,58,42,0.06)] xl:flex">
            <MascotImage
              src="/xiaojing-mascot.png"
              alt="小镜"
              size={260}
              className="h-full w-full rounded-[28px] object-contain"
            />
          </div>
        </div>

        <div className="relative grid grid-cols-3 border-t border-border px-12 py-7 text-xs xl:px-16">
          {[
            ['持仓', '今天怎么样，谁在拖累收益'],
            ['自选', '排序、对比、找重点'],
            ['研究', '多角色交叉，留下证据'],
          ].map(([title, hint], index) => (
            <div
              key={title}
              className={index ? 'border-l border-border pl-5' : ''}
            >
              <p className="font-display text-sm text-foreground">{title}</p>
              <p className="mt-1.5 leading-5 text-muted-foreground">{hint}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-[430px]">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <MascotImage
              size={40}
              className="size-10 rounded-[13px] border border-border object-cover"
            />
            <div>
              <p className="text-sm font-semibold tracking-[0.16em] text-primary">
                持见
              </p>
              <p className="text-xs text-muted-foreground">小镜 · 基金研究搭子</p>
            </div>
          </div>

          <div className="paper-panel rounded-[28px] border border-border p-6 sm:p-9">
            <p className="text-xs tracking-[0.22em] text-gold">WELCOME BACK</p>
            <h2 className="font-display mt-3 text-3xl font-semibold tracking-tight text-foreground">
              先坐下，再慢慢看。
            </h2>
            <p className="mt-2.5 text-sm leading-6 text-muted-foreground">
              账户与对话数据只连接到你的本地后端。登录后继续上一段研究，或从一张白纸开始。
            </p>

            <div className="mt-7 grid grid-cols-2 rounded-full border border-border bg-[#edece0] p-1">
              {(
                [
                  ['login', '登录'],
                  ['register', '创建账户'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => {
                    setMode(value);
                    setError('');
                  }}
                  className={`h-9 rounded-full text-sm transition-colors ${
                    mode === value
                      ? 'bg-card font-semibold text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="mt-6">
              {mode === 'register' && (
                <div className="mb-5 space-y-2">
                  <Label htmlFor="username">显示名称</Label>
                  <Input
                    id="username"
                    autoComplete="nickname"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="想让我怎么称呼你"
                    className="h-12 rounded-xl border-border bg-card px-4"
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="email">邮箱</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="请输入邮箱"
                  className="h-12 rounded-xl border-border bg-card px-4"
                />
              </div>
              <div className="mt-5 space-y-2">
                <Label htmlFor="password">密码</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete={
                    mode === 'login' ? 'current-password' : 'new-password'
                  }
                  required
                  minLength={8}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="请输入密码（至少 8 位）"
                  className="h-12 rounded-xl border-border bg-card px-4"
                />
                {mode === 'register' && (
                  <p className="text-xs leading-5 text-muted-foreground">
                    需包含大小写字母、数字与特殊字符。
                  </p>
                )}
              </div>

              {error && (
                <div
                  role="alert"
                  className="mt-5 flex gap-2 rounded-xl border border-destructive/25 bg-destructive/5 px-3 py-2.5 text-sm text-destructive"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                type="submit"
                size="lg"
                disabled={busy}
                className="mt-7 h-12 w-full rounded-xl font-semibold shadow-[0_10px_24px_rgba(47,112,87,0.18)]"
              >
                {busy ? (
                  <RefreshCw className="animate-spin" />
                ) : (
                  <ShieldCheck />
                )}
                {busy
                  ? '正在连接…'
                  : mode === 'login'
                    ? '进入持见'
                    : '创建并进入'}
              </Button>
            </form>

            <p className="mt-6 flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <ShieldCheck className="size-3.5" /> JWT 会话保护 · 本地开发环境
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-hidden="true">
      {[0, 1, 2].map((item) => (
        <span
          key={item}
          className="thinking-dot size-1.5 rounded-full bg-primary"
          style={{ animationDelay: `${item * 160}ms` }}
        />
      ))}
    </span>
  );
}

function Welcome({
  disabled,
  onPrompt,
}: {
  disabled: boolean;
  onPrompt: (text: string) => void;
}) {
  const actions = [
    {
      icon: Wallet,
      title: '持仓体检',
      hint: '今天怎么样，谁在拖累收益',
      prompt: '我的持仓今天怎么样？',
    },
    {
      icon: Star,
      title: '自选扫描',
      hint: '排序、对比、找重点',
      prompt: '帮我扫描一下自选基金，找出重点。',
    },
    {
      icon: LineChart,
      title: '基金对比',
      hint: '把候选放在同一张桌上',
      prompt: '帮我对比 000001 和 011452。',
    },
    {
      icon: Sparkles,
      title: '多智能体',
      hint: '输入 1~3 只基金，多角色交叉研究',
      prompt: '请对以下基金发起多智能体研究：',
    },
  ];
  return (
    <div className="rise-in flex flex-1 flex-col items-center justify-center py-6 text-center sm:py-8">
      <div className="rounded-[28px] border border-border bg-primary/[0.06] p-1.5 shadow-[0_18px_40px_rgba(33,58,42,0.06)]">
        <MascotImage
          src="/xiaojing-mascot.png"
          alt="小镜"
          size={124}
          className="size-[124px] rounded-[22px] object-cover sm:size-[140px]"
        />
      </div>
      <p className="mt-4 flex items-center gap-1.5 text-[10px] font-bold tracking-[0.22em] text-gold">
        <Sparkles className="size-3" /> 持见 · 小镜
      </p>
      <h2 className="font-display mt-2 max-w-2xl text-[26px] font-semibold leading-[1.4] tracking-[0.01em] text-foreground sm:text-[30px]">
        把持仓问明白，把选择看清楚。
      </h2>
      <p className="mt-2.5 max-w-xl text-sm leading-6 text-muted-foreground">
        查持仓、读自选、比基金，也可以直接发起一次多智能体研究。
      </p>

      <div className="mt-6 grid w-full max-w-3xl gap-2.5 text-left sm:grid-cols-2 lg:grid-cols-4">
        {actions.map(({ icon: Icon, title, hint, prompt }) => (
          <button
            key={title}
            type="button"
            disabled={disabled}
            onClick={() => onPrompt(prompt)}
            className="group rounded-2xl border border-border bg-card/70 p-3.5 transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:bg-card hover:shadow-[0_12px_24px_rgba(33,58,42,0.06)] disabled:pointer-events-none disabled:opacity-45"
          >
            <span className="grid size-8 place-items-center rounded-xl bg-primary/[0.08] text-primary">
              <Icon className="size-3.5" />
            </span>
            <span className="mt-2.5 block text-[13px] font-semibold text-foreground">
              {title}
            </span>
            <span className="mt-1 block text-[11px] leading-5 text-muted-foreground">
              {hint}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

const MessageItem = memo(function MessageItem({
  message,
  isLast,
  sending,
  model,
  token,
}: {
  message: ChatMessage;
  isLast: boolean;
  sending: boolean;
  model: string;
  token: string;
}) {
  const isUser = message.role === 'user';
  const isThinking = sending && isLast && !message.content;
  const roles = (message.research_roles ?? []).filter(
    (item) => item.status !== 'skipped',
  );
  const completedRoles = roles.filter(
    (item) => item.status === 'completed',
  ).length;

  if (isUser) {
    return (
      <div className="rise-in flex justify-end">
        <div className="max-w-[82%] rounded-[20px] border border-gold/20 bg-gold/[0.10] px-4 py-3 text-[15px] leading-7 text-foreground shadow-[0_8px_18px_rgba(128,99,51,0.04)]">
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        </div>
      </div>
    );
  }

  return (
    <article className="rise-in flex gap-3">
      <MascotImage
        size={36}
        className="mt-0.5 size-9 shrink-0 rounded-xl border border-border object-cover"
      />
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold text-foreground">小镜</span>
          <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-secondary-foreground">
            {model || '投研助手'}
          </span>
          {roles.length > 0 && (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] ${
                completedRoles === roles.length
                  ? 'bg-primary/[0.08] text-primary'
                  : 'bg-accent/70 text-accent-foreground'
              }`}
            >
              多角色 · {completedRoles}/{roles.length} 完成
            </span>
          )}
        </div>
        {message.fund_comparison_chart && (
          <Suspense
            fallback={
              <div className="mb-4 h-28 animate-pulse rounded-2xl border border-border bg-card/50" />
            }
          >
            <ComparisonCard
              token={token}
              chart={message.fund_comparison_chart}
            />
          </Suspense>
        )}
        {isThinking ? (
          <div className="flex items-center gap-2.5 py-1 text-sm text-text-faint">
            <ThinkingDots />
            正在整理研究线索…
          </div>
        ) : (
          <Suspense
            fallback={
              <div className="my-2 h-4 w-2/3 animate-pulse rounded bg-border/60" />
            }
          >
            <ResearchCopy
              content={message.content}
              citations={message.research_citations}
              token={token}
            />
          </Suspense>
        )}
      </div>
    </article>
  );
});

function ChatWorkspace({
  auth,
  onLogout,
  onUserUpdated,
}: {
  auth: StoredAuth;
  onLogout: () => void;
  onUserUpdated: (user: UserProfile) => void;
}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [error, setError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [view, setView] = useState<AppView>('agent');
  const [selectedFund, setSelectedFund] = useState<string | null>(null);
  const [fundOrigin, setFundOrigin] = useState<'portfolio' | 'watchlist'>(
    'watchlist',
  );
  const [selectedMarketSymbol, setSelectedMarketSymbol] = useState<
    string | null
  >(null);
  const [selectedImportId, setSelectedImportId] = useState<string | null>(null);
  const [selectedPositionCode, setSelectedPositionCode] = useState<
    string | null
  >(null);
  const [positionOrigin, setPositionOrigin] = useState<'portfolio' | 'fund'>(
    'portfolio',
  );
  const [tradeCode, setTradeCode] = useState<string | null>(null);
  const [tradeOperation, setTradeOperation] = useState<TradeOperation>('BUY');
  const [tradeOrigin, setTradeOrigin] = useState<'portfolio' | 'fund'>(
    'portfolio',
  );
  const [transactionsCode, setTransactionsCode] = useState<string | null>(null);
  const [transactionsOrigin, setTransactionsOrigin] = useState<
    'portfolio' | 'fund'
  >('portfolio');
  const scrollRef = useRef<HTMLDivElement>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [llmOpen, setLlmOpen] = useState(false);
  const [llm, setLlm] = useState<LlmProfiles | null>(null);
  const [loadingLlm, setLoadingLlm] = useState(false);
  const activeSessionIdRef = useRef<string | null>(null);
  const streamGenerationRef = useRef(0);
  const streamRequestRef = useRef<{
    sessionId: string | null;
    controller: AbortController;
  } | null>(null);

  function activateSession(session: Session | null) {
    const nextId = session?.session_id ?? null;
    if (nextId === activeSessionIdRef.current) return;
    const stream = streamRequestRef.current;
    if (stream && stream.sessionId !== nextId) stream.controller.abort();
    activeSessionIdRef.current = nextId;
    setActiveSession(session);
    setMessages([]);
  }

  useEffect(
    () => () => {
      const stream = streamRequestRef.current;
      streamRequestRef.current = null;
      stream?.controller.abort();
    },
    [],
  );

  function openLlmSettings() {
    setLlmOpen(true);
  }

  async function selectLlm(name: string) {
    setLoadingLlm(true);
    try {
      setLlm(await switchLlmProfile(auth.token, name));
    } catch (switchError) {
      setError(getErrorMessage(switchError));
    } finally {
      setLoadingLlm(false);
    }
  }

  const refreshSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const nextSessions = await listSessions(auth.token);
      setSessions(nextSessions);
      setActiveSession((current) => {
        // 和 mobile 一样，进入工作台先落在空白问候页；要看历史从侧栏挑。
        if (!current) return null;
        return (
          nextSessions.find(
            (item) => item.session_id === current.session_id,
          ) ?? null
        );
      });
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoadingSessions(false);
    }
  }, [auth.token]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshSessions();
      void healthCheck().then(setOnline);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshSessions]);

  useEffect(() => {
    let cancelled = false;
    void getLlmProfiles(auth.token)
      .then((profiles) => {
        if (!cancelled) setLlm(profiles);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [auth.token]);

  useEffect(() => {
    let cancelled = false;
    const nextId = activeSession?.session_id ?? null;
    activeSessionIdRef.current = nextId;
    const stream = streamRequestRef.current;
    if (stream && stream.sessionId !== nextId) stream.controller.abort();
    if (!activeSession) {
      const timer = window.setTimeout(() => setMessages([]), 0);
      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => {
      if (streamRequestRef.current?.sessionId === activeSession.session_id) {
        setLoadingMessages(false);
        return;
      }
      const generation = streamGenerationRef.current;
      setLoadingMessages(true);
      setError('');
      void getMessages(activeSession)
        .then((history) => {
          if (
            !cancelled &&
            generation === streamGenerationRef.current &&
            streamRequestRef.current?.sessionId !== activeSession.session_id
          )
            setMessages(history);
        })
        .catch((loadError: unknown) => {
          if (!cancelled) setError(getErrorMessage(loadError));
        })
        .finally(() => {
          if (!cancelled) setLoadingMessages(false);
        });
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeSession]);

  useEffect(() => {
    const element = scrollRef.current;
    if (element)
      element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  async function handleNewSession(): Promise<Session | null> {
    setError('');
    try {
      const session = await createSession(auth.token);
      setSessions((current) => [session, ...current]);
      activateSession(session);
      setSidebarOpen(false);
      return session;
    } catch (createError) {
      setError(getErrorMessage(createError));
      return null;
    }
  }

  async function submitMessage(rawContent: string) {
    const content = rawContent.trim();
    if (!content) throw new Error('消息不能为空');
    if (streamRequestRef.current) throw new Error('上一条消息仍在生成中');
    const request = {
      sessionId: activeSession?.session_id ?? null,
      controller: new AbortController(),
    };
    streamRequestRef.current = request;
    streamGenerationRef.current += 1;
    setSending(true);
    let session = activeSession;
    try {
      if (!session) {
        const created = await createSession(auth.token);
        session = created;
        if (request.controller.signal.aborted)
          throw new DOMException('已停止生成', 'AbortError');
        request.sessionId = session.session_id;
        setSessions((current) => [created, ...current]);
        activateSession(session);
        setSidebarOpen(false);
      }
      setDraft('');
      setError('');
      setMessages((current) => [
        ...current,
        { role: 'user', content },
        { role: 'assistant', content: '' },
      ]);
      await streamMessage(
        session,
        content,
        (chunk) => {
          if (
            streamRequestRef.current !== request ||
            activeSessionIdRef.current !== request.sessionId ||
            request.controller.signal.aborted
          )
            return;
          setMessages((current) => {
            if (
              streamRequestRef.current !== request ||
              activeSessionIdRef.current !== request.sessionId ||
              request.controller.signal.aborted
            )
              return current;
            const next = [...current];
            const last = next[next.length - 1];
            if (last?.role === 'assistant')
              next[next.length - 1] = {
                ...last,
                content: last.content + chunk,
              };
            return next;
          });
        },
        request.controller.signal,
      );
      // 流式只带正文；引用、角色徽标和多角色状态要从服务端历史补一次。
      try {
        const history = await getMessages(session);
        if (
          streamRequestRef.current === request &&
          activeSessionIdRef.current === request.sessionId
        )
          setMessages(history);
      } catch {
        // 历史补取失败不覆盖已经流式显示的回答。
      }
      window.setTimeout(() => void refreshSessions(), 500);
    } catch (sendError) {
      if (sendError instanceof Error && sendError.name === 'AbortError') {
        return { status: 'stopped', session_id: request.sessionId };
      }
      if (activeSessionIdRef.current !== request.sessionId) throw sendError;
      setError(getErrorMessage(sendError));
      setMessages((current) =>
        current.filter(
          (message, index) => index !== current.length - 1 || message.content,
        ),
      );
      throw sendError;
    } finally {
      if (streamRequestRef.current === request) {
        streamRequestRef.current = null;
        setSending(false);
      }
    }

    return { status: 'completed', session_id: session.session_id };
  }

  function handleSend() {
    void submitMessage(draft).catch(() => undefined);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  }

  async function handleClear() {
    if (!activeSession || streamRequestRef.current) return;
    const sessionId = activeSession.session_id;
    try {
      await clearMessages(activeSession);
      if (activeSessionIdRef.current !== sessionId) return;
      streamGenerationRef.current += 1;
      setMessages([]);
      setError('');
    } catch (clearError) {
      if (activeSessionIdRef.current === sessionId)
        setError(getErrorMessage(clearError));
    }
  }

  async function handleDelete(session: Session) {
    try {
      await deleteSession(session);
      const remaining = sessions.filter(
        (item) => item.session_id !== session.session_id,
      );
      setSessions(remaining);
      if (activeSession?.session_id === session.session_id)
        activateSession(remaining[0] ?? null);
      setError('');
    } catch (deleteError) {
      setError(getErrorMessage(deleteError));
    }
  }

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;

    const lifecycle = new AbortController();
    const reportRegistrationError = (registrationError: unknown) => {
      console.warn('webmcp_registration_failed', registrationError);
    };
    const registrations = [
      context.registerTool(
        {
          name: 'create_chat_session',
          title: '创建新对话',
          description: '创建并切换到一个新的 Fund Agent 对话会话。',
          inputSchema: {
            type: 'object',
            properties: {},
            additionalProperties: false,
          },
          annotations: { readOnlyHint: false, untrustedContentHint: false },
          async execute() {
            const session = await handleNewSession();
            if (!session) throw new Error('创建会话失败');
            return { status: 'created', session_id: session.session_id };
          },
        },
        { signal: lifecycle.signal },
      ),
      context.registerTool(
        {
          name: 'send_chat_message',
          title: '发送聊天消息',
          description:
            '向当前 Fund Agent 会话发送一条消息；若没有会话则先创建会话，并等待流式回答完成。',
          inputSchema: {
            type: 'object',
            properties: {
              content: { type: 'string', minLength: 1, maxLength: 3000 },
            },
            required: ['content'],
            additionalProperties: false,
          },
          annotations: { readOnlyHint: false, untrustedContentHint: true },
          async execute(input) {
            const content =
              typeof input === 'object' &&
              input !== null &&
              'content' in input &&
              typeof input.content === 'string'
                ? input.content.trim()
                : '';
            if (!content || content.length > 3000) {
              throw new Error('content 必须为 1 至 3000 个字符');
            }
            return submitMessage(content);
          },
        },
        { signal: lifecycle.signal },
      ),
    ];

    for (const registration of registrations) {
      void Promise.resolve(registration).catch(reportRegistrationError);
    }
    return () => lifecycle.abort();
  });

  const displayName = auth.user.username || auth.user.email.split('@')[0];
  const activeName = activeSession?.name?.trim() || '新对话';
  const activeProfile =
    llm?.profiles.find((profile) => profile.name === llm.active) ?? null;
  const pageTitles: Record<AppView, { title: string; hint: string }> = {
    agent: { title: activeName, hint: '小镜 · 研究会话' },
    portfolio: { title: '持仓', hint: '账户汇总与持仓明细' },
    watchlist: { title: '自选', hint: '观察清单与分组' },
    market: { title: '行情', hint: '大盘指数与板块' },
    profile: { title: '我的', hint: '账号、模型与导入记录' },
    fund: { title: '基金详情', hint: selectedFund ?? '' },
    accounts: { title: '账户管理', hint: '新建、改名与删除持仓账户' },
    transactions: { title: '交易记录', hint: '买入、卖出、定投与修正' },
    'auto-invest': { title: '定投计划', hint: '扣款排期与结算' },
    'watchlist-groups': { title: '自选分组', hint: '分组与组内排序' },
    import: { title: '导入持仓', hint: '手动录入或截图识别' },
    'import-review': { title: '导入审阅', hint: '确认后才会写入持仓' },
    persona: { title: '用户画像', hint: '由你确认的投资偏好' },
    'profile-edit': { title: '编辑资料', hint: '昵称与邮箱' },
    'market-detail': { title: '行情分析', hint: selectedMarketSymbol ?? '' },
    'position-edit': { title: '同步持仓', hint: selectedPositionCode ?? '' },
    trade: { title: '加减仓', hint: tradeCode ?? '' },
    'nav-history': { title: '净值明细', hint: selectedFund ?? '' },
  };
  const activeNav: MainView =
    view === 'fund'
      ? fundOrigin
      : view === 'market-detail'
        ? 'market'
        : view === 'watchlist-groups'
          ? 'watchlist'
          : view === 'accounts' ||
              view === 'persona' ||
              view === 'profile-edit'
            ? 'profile'
            : view === 'agent' ||
                view === 'portfolio' ||
                view === 'watchlist' ||
                view === 'market' ||
                view === 'profile'
              ? view
              : 'portfolio';

  function openFund(code: string, origin: 'portfolio' | 'watchlist') {
    setSelectedFund(code);
    setFundOrigin(origin);
    setView('fund');
    setSidebarOpen(false);
  }

  function goView(next: MainView) {
    setView(next);
    setSelectedFund(null);
    setSelectedMarketSymbol(null);
    setSelectedImportId(null);
    setSelectedPositionCode(null);
    setTradeCode(null);
    setTransactionsCode(null);
    setSidebarOpen(false);
  }

  function openTrade(
    code: string,
    operation: TradeOperation,
    origin: 'portfolio' | 'fund',
  ) {
    setTradeCode(code);
    setTradeOperation(operation);
    setTradeOrigin(origin);
    setView('trade');
    setSidebarOpen(false);
  }

  function openTransactions(code: string | null, origin: 'portfolio' | 'fund') {
    setTransactionsCode(code);
    setTransactionsOrigin(origin);
    setView('transactions');
    setSidebarOpen(false);
  }

  function openPosition(code: string, origin: 'portfolio' | 'fund') {
    setSelectedPositionCode(code);
    setPositionOrigin(origin);
    setView('position-edit');
    setSidebarOpen(false);
  }

  function backFromPosition() {
    if (positionOrigin === 'fund' && selectedFund) setView('fund');
    else setView('portfolio');
  }

  function backFromTrade() {
    if (tradeOrigin === 'fund' && selectedFund) setView('fund');
    else setView('portfolio');
  }

  function backFromTransactions() {
    if (transactionsOrigin === 'fund' && selectedFund) setView('fund');
    else setView('portfolio');
  }

  return (
    <main className="flex h-screen overflow-hidden bg-background">
      {sidebarOpen && (
        <button
          aria-label="关闭侧栏"
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[300px] flex-col border-r border-border bg-sidebar transition-transform lg:static lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="flex h-[76px] items-center justify-between border-b border-border px-5">
          <div className="flex items-center gap-3">
            <MascotImage
              size={40}
              className="size-10 rounded-[13px] border border-border object-cover"
            />
            <div>
              <p className="font-display text-[15px] font-semibold tracking-[0.06em] text-foreground">
                持见
              </p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                小镜 · 基金研究搭子
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            className="lg:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="关闭侧栏"
          >
            <X />
          </Button>
        </div>

        <nav aria-label="功能导航" className="mt-3 grid gap-1 px-3">
          {APP_NAV.map(({ key, label, hint, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => goView(key)}
              onMouseEnter={() => void PRELOAD_PAGES[key]?.()}
              onFocus={() => void PRELOAD_PAGES[key]?.()}
              className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors ${
                activeNav === key
                  ? 'bg-primary/[0.08] text-primary'
                  : 'text-text-soft hover:bg-card/60 hover:text-foreground'
              }`}
            >
              <Icon className="size-4 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-medium">{label}</span>
                <span className="mt-0.5 block text-[10px] text-text-faint">
                  {hint}
                </span>
              </span>
            </button>
          ))}
        </nav>

        {view === 'agent' && (
          <>
            <div className="px-4 pb-3 pt-4">
              <Button
                className="h-11 w-full justify-start rounded-xl bg-primary text-primary-foreground shadow-[0_10px_22px_rgba(47,112,87,0.16)] hover:bg-primary/90"
                onClick={() => void handleNewSession()}
              >
                <Plus /> 新建对话
              </Button>
            </div>

        <div className="flex items-center justify-between px-5 pb-2 pt-3">
          <p className="text-[10px] font-semibold tracking-[0.2em] text-muted-foreground">
            历史会话
          </p>
          <span className="text-[10px] tabular-nums text-text-faint">
            {sessions.length.toString().padStart(2, '0')}
          </span>
        </div>

        <nav
          aria-label="历史会话"
          className="min-h-0 flex-1 overflow-y-auto px-2 pb-4"
        >
          {loadingSessions ? (
            <div className="space-y-2 p-2">
              {[0, 1, 2].map((item) => (
                <div
                  key={item}
                  className="h-14 animate-pulse rounded-xl bg-primary/[0.04]"
                />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <div className="mx-2 mt-3 rounded-2xl border border-dashed border-border px-4 py-8 text-center">
              <MessageSquare className="mx-auto size-5 text-text-faint" />
              <p className="mt-2 text-xs text-muted-foreground">
                还没有对话。问一句，就从这里开始。
              </p>
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = activeSession?.session_id === session.session_id;
              return (
                <div
                  key={session.session_id}
                  className={`group mb-1 flex items-center rounded-xl border transition-colors ${
                    isActive
                      ? 'border-primary/20 bg-primary/[0.07]'
                      : 'border-transparent hover:border-border hover:bg-card/60'
                  }`}
                >
                  <button
                    className="min-w-0 flex-1 px-3 py-3 text-left"
                    onClick={() => {
                      activateSession(session);
                      setSidebarOpen(false);
                    }}
                  >
                    <p
                      className={`truncate text-[13px] leading-5 ${isActive ? 'font-medium text-foreground' : 'text-text-soft'}`}
                    >
                      {session.name?.trim() || '新对话'}
                    </p>
                    <p className="mt-1 truncate text-[10px] tracking-wide text-text-faint">
                      {session.session_id.slice(0, 12)}
                    </p>
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      aria-label="会话操作"
                      className="mr-2 grid size-7 place-items-center rounded-lg text-muted-foreground opacity-0 outline-none hover:bg-primary/[0.06] hover:text-foreground group-hover:opacity-100 focus:opacity-100"
                    >
                      <MoreHorizontal />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-36">
                      <DropdownMenuItem
                        variant="destructive"
                        onClick={() => void handleDelete(session)}
                      >
                        <Trash2 /> 删除会话
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            })
          )}
        </nav>
          </>
        )}

        <div className="border-t border-border p-3">
          <DropdownMenu>
            <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-xl border border-transparent px-2 py-2.5 text-left outline-none transition-colors hover:border-border hover:bg-card/70">
              <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-gold/10 text-sm font-semibold text-gold">
                {displayName.slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {displayName}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {auth.user.email}
                </p>
              </div>
              <MoreHorizontal className="size-4 text-text-faint" />
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-64">
              <DropdownMenuGroup>
                <DropdownMenuLabel>{auth.user.email}</DropdownMenuLabel>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setAccountOpen(true)}>
                <UserRound /> 账号管理
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={loadingLlm || sending}
                onClick={openLlmSettings}
              >
                <Settings /> 模型供应商设置
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onLogout}>
                <LogOut /> 退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[76px] shrink-0 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur-xl sm:px-7">
          <div className="flex min-w-0 items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="打开侧栏"
            >
              <Menu />
            </Button>
            <PanelLeftClose className="hidden size-4 text-text-faint lg:block" />
            <MascotImage
              size={36}
              className="size-9 rounded-xl border border-border object-cover"
            />
            <div className="min-w-0">
              <h1 className="truncate text-[15px] font-semibold text-foreground">
                {pageTitles[view].title}
              </h1>
              <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {view === 'agent' && (
                  <span
                    className={`size-1.5 rounded-full ${online ? 'bg-primary' : online === false ? 'bg-destructive' : 'bg-text-faint'}`}
                  />
                )}
                {view === 'agent'
                  ? `小镜 · ${online ? '在线' : online === false ? '离线' : '连接中'}`
                  : pageTitles[view].hint}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {view === 'agent' && (
              <span className="hidden max-w-52 items-center gap-1.5 truncate rounded-full border border-border bg-card/60 px-3 py-1.5 text-[11px] text-muted-foreground sm:flex">
                <span className="size-1.5 rounded-full bg-gold" />
                {activeProfile?.model ?? '默认模型'}
              </span>
            )}
            {view === 'agent' && (
            <AlertDialog>
              <AlertDialogTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={
                      !activeSession || messages.length === 0 || sending
                    }
                    aria-label="清空对话"
                  />
                }
              >
                <Trash2 />
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>清空当前对话？</AlertDialogTitle>
                  <AlertDialogDescription>
                    当前会话中的全部消息将被永久删除，但会话本身会保留。
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction
                    variant="destructive"
                    onClick={() => void handleClear()}
                  >
                    确认清空
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            )}
          </div>
        </header>

        {error && (
          <div
            role="alert"
            className="flex shrink-0 items-center justify-between border-b border-destructive/20 bg-destructive/[0.06] px-4 py-2.5 text-xs text-destructive sm:px-7"
          >
            <span className="flex min-w-0 items-center gap-2">
              <AlertCircle className="size-3.5 shrink-0" />
              <span className="truncate">{error}</span>
            </span>
            <button
              className="ml-3 rounded-lg p-1 text-destructive/70 hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setError('')}
              aria-label="关闭错误提示"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}

        {view === 'agent' ? (
          <>
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto scroll-smooth"
        >
          <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-5 sm:px-8">
            {loadingMessages ? (
              <div className="flex flex-1 items-center justify-center py-16">
                <div className="flex items-center gap-3 text-sm text-text-faint">
                  <RefreshCw className="size-4 animate-spin text-primary" />
                  正在读这段对话…
                </div>
              </div>
            ) : messages.length === 0 ? (
              <Welcome disabled={sending} onPrompt={setDraft} />
            ) : (
              <div className="space-y-7 py-8 sm:py-10">
                {messages
                  .filter((message) => message.role !== 'system')
                  .map((message, index) => (
                    <MessageItem
                      key={`${index}-${message.role}`}
                      message={message}
                      isLast={index === messages.length - 1}
                      sending={sending}
                      model={activeProfile?.model ?? ''}
                      token={auth.token}
                    />
                  ))}
              </div>
            )}
          </div>
        </div>

        <footer className="shrink-0 px-4 pb-4 pt-2 sm:px-8 sm:pb-6">
          <div className="mx-auto max-w-3xl">
            <div className="rounded-[24px] border border-border bg-card/95 p-2.5 shadow-[0_16px_40px_rgba(33,58,42,0.07)] backdrop-blur focus-within:border-primary/35">
              <div className="flex items-center px-1 pb-1">
                <DropdownMenu>
                  <DropdownMenuTrigger
                    aria-label="切换模型"
                    disabled={sending}
                    className="flex max-w-[80%] items-center gap-2 rounded-full border border-border bg-primary/[0.035] px-3 py-1.5 text-[11px] text-muted-foreground outline-none transition-colors hover:border-primary/25 hover:text-foreground disabled:opacity-50"
                  >
                    <span className="size-1.5 rounded-full bg-primary" />
                    <span className="truncate">
                      {activeProfile
                        ? `${activeProfile.name} · ${activeProfile.model}`
                        : '选择模型'}
                    </span>
                    <ChevronDown className="size-3.5 shrink-0" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-64">
                    <DropdownMenuGroup>
                      <DropdownMenuLabel>当前模型</DropdownMenuLabel>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    {llm?.profiles.map((profile) => (
                      <DropdownMenuItem
                        key={profile.name}
                        disabled={sending || profile.name === llm.active}
                        onClick={() => void selectLlm(profile.name)}
                      >
                        <span className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate">{profile.name}</span>
                          <span className="truncate text-[10px] text-muted-foreground">
                            {profile.model}
                          </span>
                        </span>
                        {profile.name === llm.active ? (
                          <Check className="size-4 text-primary" />
                        ) : null}
                      </DropdownMenuItem>
                    ))}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      disabled={loadingLlm || sending}
                      onClick={openLlmSettings}
                    >
                      <Settings /> 管理模型
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <Textarea
                value={draft}
                onChange={(event) =>
                  setDraft(event.target.value.slice(0, 3000))
                }
                onKeyDown={handleComposerKeyDown}
                disabled={sending}
                placeholder={
                  activeSession
                    ? '把问题放在这里，慢慢说…'
                    : '问点什么，新的对话会从这里开始…'
                }
                className="max-h-44 min-h-[58px] resize-none border-0 bg-transparent px-3 py-2.5 text-[15px] leading-7 shadow-none focus-visible:ring-0"
              />
              <div className="flex items-center justify-between px-2 pb-1 pt-1.5">
                <div className="flex items-center gap-3 text-[10px] text-text-faint">
                  <span>ENTER 发送</span>
                  <span className="hidden sm:inline">SHIFT + ENTER 换行</span>
                  <span>{draft.length}/3000</span>
                </div>
                <Button
                  size="icon"
                  disabled={!draft.trim() || sending}
                  onClick={handleSend}
                  aria-label="发送消息"
                  className="size-10 rounded-full bg-primary text-primary-foreground shadow-[0_8px_18px_rgba(47,112,87,0.22)] hover:bg-primary/90 disabled:shadow-none"
                >
                  {sending ? (
                    <RefreshCw className="animate-spin" />
                  ) : (
                    <ArrowUp />
                  )}
                </Button>
              </div>
            </div>
            <p className="mt-2.5 flex items-center justify-center gap-1.5 text-[10px] text-text-faint">
              <CheckCircle2 className="size-3" />
              AI 生成内容可能存在偏差，请核验关键投资信息。
            </p>
          </div>
        </footer>
          </>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <Suspense fallback={<PageFallback />}>
            {view === 'portfolio' && (
              <PortfolioPage
                token={auth.token}
                onOpenFund={(code) => openFund(code, 'portfolio')}
                onManageAccounts={() => setView('accounts')}
                onOpenImport={() => setView('import')}
                onOpenTransactions={() => openTransactions(null, 'portfolio')}
                onOpenAutoInvest={() => setView('auto-invest')}
                onEditPosition={(code) => openPosition(code, 'portfolio')}
                onTrade={(code, operation) =>
                  openTrade(code, operation, 'portfolio')
                }
              />
            )}
            {view === 'watchlist' && (
              <WatchlistPage
                token={auth.token}
                onOpenFund={(code) => openFund(code, 'watchlist')}
                onOpenGroups={() => setView('watchlist-groups')}
              />
            )}
            {view === 'watchlist-groups' && (
              <WatchlistGroupsPage
                token={auth.token}
                onBack={() => setView('watchlist')}
              />
            )}
            {view === 'market' && (
              <MarketPage
                token={auth.token}
                onOpenSymbol={(symbol) => {
                  setSelectedMarketSymbol(symbol);
                  setView('market-detail');
                }}
              />
            )}
            {view === 'market-detail' && selectedMarketSymbol && (
              <MarketDetailPage
                token={auth.token}
                symbol={selectedMarketSymbol}
                onBack={() => setView('market')}
              />
            )}
            {view === 'profile' && (
              <ProfilePage
                token={auth.token}
                user={auth.user}
                onOpenPortfolio={() => goView('portfolio')}
                onOpenWatchlist={() => goView('watchlist')}
                onOpenGroups={() => setView('watchlist-groups')}
                onOpenManageAccounts={() => setView('accounts')}
                onOpenImport={() => setView('import')}
                onOpenImportReview={(importId) => {
                  setSelectedImportId(importId);
                  setView('import-review');
                }}
                onOpenTransactions={() => openTransactions(null, 'portfolio')}
                onOpenAutoInvest={() => setView('auto-invest')}
                onOpenPersona={() => setView('persona')}
                onOpenModel={openLlmSettings}
                onOpenAccount={() => setView('profile-edit')}
                onLogout={onLogout}
              />
            )}
            {view === 'profile-edit' && (
              <ProfileEditPage
                token={auth.token}
                user={auth.user}
                onBack={() => setView('profile')}
                onSaved={(user) => onUserUpdated(user)}
              />
            )}
            {view === 'persona' && (
              <PersonaPage
                token={auth.token}
                onBack={() => setView('profile')}
              />
            )}
            {view === 'accounts' && (
              <AccountsPage
                token={auth.token}
                onBack={() => setView('portfolio')}
                onOpenPortfolio={() => setView('portfolio')}
              />
            )}
            {view === 'transactions' && (
              <TransactionsPage
                token={auth.token}
                fundCode={transactionsCode}
                onBack={backFromTransactions}
              />
            )}
            {view === 'auto-invest' && (
              <AutoInvestPage
                token={auth.token}
                onBack={() => setView('portfolio')}
                onOpenFund={(code) => openFund(code, 'portfolio')}
              />
            )}
            {view === 'import' && (
              <ImportPage
                token={auth.token}
                onBack={() => setView('portfolio')}
                onOpenImport={(importId) => {
                  setSelectedImportId(importId);
                  setView('import-review');
                }}
              />
            )}
            {view === 'import-review' && selectedImportId && (
              <ImportReviewPage
                token={auth.token}
                importId={selectedImportId}
                onBack={() => setView('import')}
                onOpenPortfolio={() => setView('portfolio')}
                onDeleted={() => {
                  setSelectedImportId(null);
                  setView('import');
                }}
              />
            )}
            {view === 'position-edit' && selectedPositionCode && (
              <PositionEditPage
                token={auth.token}
                code={selectedPositionCode}
                onBack={backFromPosition}
                onDone={backFromPosition}
                onTrade={(operation) =>
                  openTrade(selectedPositionCode, operation, positionOrigin)
                }
                onOpenAutoInvest={() => setView('auto-invest')}
              />
            )}
            {view === 'trade' && tradeCode && (
              <TradePage
                token={auth.token}
                code={tradeCode}
                initialOperation={tradeOperation}
                onBack={backFromTrade}
                onDone={backFromTrade}
                onOpenAutoInvest={() => setView('auto-invest')}
              />
            )}
            {view === 'fund' && selectedFund && (
              <FundDetailPage
                token={auth.token}
                code={selectedFund}
                onBack={() => setView(fundOrigin)}
                onOpenNavHistory={() => setView('nav-history')}
                onOpenPosition={(code) => openPosition(code, 'fund')}
                onOpenTransactions={(code) => openTransactions(code, 'fund')}
                onOpenAutoInvest={() => setView('auto-invest')}
                onTrade={(code, operation) => openTrade(code, operation, 'fund')}
                onOpenStock={(symbol) => {
                  setSelectedMarketSymbol(symbol);
                  setView('market-detail');
                }}
              />
            )}
            {view === 'nav-history' && selectedFund && (
              <NavHistoryPage
                token={auth.token}
                code={selectedFund}
                onBack={() => setView('fund')}
              />
            )}
            </Suspense>
          </div>
        )}
      </section>
      {accountOpen && (
        <Suspense fallback={null}>
          <AccountDialog
            open={accountOpen}
            onOpenChange={setAccountOpen}
            token={auth.token}
            onSaved={onUserUpdated}
          />
        </Suspense>
      )}
      {llmOpen && (
        <Suspense fallback={null}>
          <LlmSettingsDialog
            open={llmOpen}
            onOpenChange={setLlmOpen}
            token={auth.token}
            llm={llm}
            onSaved={setLlm}
          />
        </Suspense>
      )}
    </main>
  );
}

export default function Home() {
  const [auth, setAuth] = useState<StoredAuth | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const stored = window.localStorage.getItem(AUTH_STORAGE_KEY);
        if (stored) {
          const parsed = JSON.parse(stored) as StoredAuth;
          setAuth(parsed);
          // 旧版本只存了邮箱；进工作台时补一次 /auth/me，资料页才有 id 与注册时间。
          void getCurrentUser(parsed.token)
            .then((user) => {
              const next = { ...parsed, user };
              window.localStorage.setItem(
                AUTH_STORAGE_KEY,
                JSON.stringify(next),
              );
              setAuth(next);
            })
            .catch(() => undefined);
        }
      } catch {
        window.localStorage.removeItem(AUTH_STORAGE_KEY);
      } finally {
        setHydrated(true);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  function handleAuthenticated(nextAuth: StoredAuth) {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(nextAuth));
    setAuth(nextAuth);
  }

  function handleLogout() {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    setAuth(null);
  }

  if (!hydrated) {
    return (
      <main className="grid min-h-screen place-items-center bg-background">
        <div className="flex items-center gap-3 font-mono text-xs tracking-[0.15em] text-primary">
          <RefreshCw className="size-4 animate-spin" />
          INITIALIZING
        </div>
      </main>
    );
  }

  return auth ? (
    <ChatWorkspace
      auth={auth}
      onLogout={handleLogout}
      onUserUpdated={(user) => handleAuthenticated({ ...auth, user })}
    />
  ) : (
    <AuthScreen onAuthenticated={handleAuthenticated} />
  );
}
