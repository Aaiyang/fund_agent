'use client';

import {
  type KeyboardEvent,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  AlertCircle,
  ArrowUp,
  Bot,
  CheckCircle2,
  Clock3,
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
  Trash2,
  UserRound,
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
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { AccountDialog } from '@/components/account-dialog';
import { LlmSettingsDialog } from '@/components/llm-settings';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageHeader,
} from '@/components/ui/message';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  type ChatMessage,
  type LlmProfiles,
  type Session,
  type UserProfile,
  clearMessages,
  createSession,
  deleteSession,
  getMessages,
  getLlmProfiles,
  healthCheck,
  listSessions,
  login,
  register,
  streamMessage,
  switchLlmProfile,
} from '@/lib/api';

type StoredAuth = {
  token: string;
  user: UserProfile;
};

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
      onAuthenticated({ token: token.access_token, user: { email } });
    } catch (submitError) {
      setError(getErrorMessage(submitError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(460px,0.95fr)]">
      <section className="relative hidden min-h-screen overflow-hidden border-r border-white/8 bg-[#0b1210] p-12 lg:flex lg:flex-col lg:justify-between xl:p-16">
        <div
          aria-hidden="true"
          className="absolute inset-0 opacity-70 [background:radial-gradient(circle_at_18%_16%,rgba(55,213,138,.16),transparent_32%),radial-gradient(circle_at_80%_82%,rgba(55,213,138,.08),transparent_30%)]"
        />
        <div className="relative flex items-center gap-3">
          <div className="grid size-10 place-items-center border border-emerald-300/30 bg-emerald-300/10 text-emerald-300">
            <Sparkles className="size-5" />
          </div>
          <div>
            <p className="text-sm font-semibold tracking-[0.18em] text-emerald-300">
              FUND AGENT
            </p>
            <p className="text-xs text-zinc-500">LOCAL RESEARCH WORKBENCH</p>
          </div>
        </div>

        <div className="relative max-w-2xl">
          <p className="mb-5 font-mono text-xs tracking-[0.18em] text-emerald-300/80">
            {'// INTELLIGENCE, COMPOUNDED'}
          </p>
          <h1 className="max-w-xl text-5xl font-semibold leading-[1.08] tracking-[-0.045em] text-zinc-50 xl:text-6xl">
            把复杂投研，变成一场清晰对话。
          </h1>
          <p className="mt-7 max-w-lg text-base leading-7 text-zinc-400">
            基于 LangGraph
            的本地智能工作台。保持上下文、沉淀长期记忆，并通过流式响应把推理过程快速送到你面前。
          </p>
        </div>

        <div className="relative grid max-w-xl grid-cols-3 border-y border-white/8 py-5 text-xs">
          <div>
            <p className="font-mono text-emerald-300">DEEPSEEK</p>
            <p className="mt-1 text-zinc-500">推理模型</p>
          </div>
          <div className="border-l border-white/8 pl-6">
            <p className="font-mono text-emerald-300">LANGGRAPH</p>
            <p className="mt-1 text-zinc-500">状态编排</p>
          </div>
          <div className="border-l border-white/8 pl-6">
            <p className="font-mono text-emerald-300">PGVECTOR</p>
            <p className="mt-1 text-zinc-500">长期记忆</p>
          </div>
        </div>
      </section>

      <section className="flex min-h-screen items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <div className="grid size-9 place-items-center border border-emerald-300/30 bg-emerald-300/10 text-emerald-300">
              <Sparkles className="size-4" />
            </div>
            <p className="font-mono text-sm font-semibold tracking-[0.15em] text-emerald-300">
              FUND AGENT
            </p>
          </div>

          <p className="font-mono text-xs tracking-[0.16em] text-emerald-300">
            SECURE ACCESS
          </p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50">
            进入投研工作台
          </h2>
          <p className="mt-2 text-sm text-zinc-500">
            账户与对话数据仅连接到你的本地后端。
          </p>

          <Tabs
            className="mt-8"
            value={mode}
            onValueChange={(value) => {
              setMode(value as 'login' | 'register');
              setError('');
            }}
          >
            <TabsList className="grid h-10 w-full grid-cols-2 bg-white/5 p-1">
              <TabsTrigger value="login">登录</TabsTrigger>
              <TabsTrigger value="register">创建账户</TabsTrigger>
            </TabsList>

            <form onSubmit={handleSubmit} className="mt-7">
              {mode === 'register' && (
                <div className="mb-5 space-y-2">
                  <Label htmlFor="username">显示名称</Label>
                  <Input
                    id="username"
                    autoComplete="nickname"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="请输入显示名称"
                    className="h-11 bg-white/[0.035]"
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
                  className="h-11 bg-white/[0.035]"
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
                  className="h-11 bg-white/[0.035]"
                />
                {mode === 'register' && (
                  <p className="text-xs leading-5 text-zinc-600">
                    需包含大小写字母、数字与特殊字符。
                  </p>
                )}
              </div>

              {error && (
                <div
                  role="alert"
                  className="mt-5 flex gap-2 border border-red-400/20 bg-red-400/8 px-3 py-2.5 text-sm text-red-300"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                type="submit"
                size="lg"
                disabled={busy}
                className="mt-7 h-11 w-full rounded-md font-semibold"
              >
                {busy ? (
                  <RefreshCw className="animate-spin" />
                ) : (
                  <ShieldCheck />
                )}
                {busy
                  ? '正在连接…'
                  : mode === 'login'
                    ? '安全登录'
                    : '创建并登录'}
              </Button>
            </form>
            <TabsContent value="login" />
            <TabsContent value="register" />
          </Tabs>

          <p className="mt-8 flex items-center justify-center gap-2 text-xs text-zinc-600">
            <ShieldCheck className="size-3.5" /> JWT 会话保护 · 本地开发环境
          </p>
        </div>
      </section>
    </main>
  );
}

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
  const scrollRef = useRef<HTMLDivElement>(null);
  const [accountOpen, setAccountOpen] = useState(false);
  const [llmOpen, setLlmOpen] = useState(false);
  const [llm, setLlm] = useState<LlmProfiles | null>(null);
  const [loadingLlm, setLoadingLlm] = useState(false);

  async function openLlmSettings() {
    setLoadingLlm(true);
    try {
      setLlm(await getLlmProfiles(auth.token));
      setLlmOpen(true);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoadingLlm(false);
    }
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
        if (!current) return nextSessions[0] ?? null;
        return (
          nextSessions.find((item) => item.session_id === current.session_id) ??
          nextSessions[0] ??
          null
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
    if (!activeSession) {
      const timer = window.setTimeout(() => setMessages([]), 0);
      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => {
      setLoadingMessages(true);
      setError('');
      void getMessages(activeSession)
        .then((history) => {
          if (!cancelled) setMessages(history);
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
      setActiveSession(session);
      setMessages([]);
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
    if (sending) throw new Error('上一条消息仍在生成中');
    let session = activeSession;
    if (!session) session = await handleNewSession();
    if (!session) throw new Error('无法创建新会话');

    setDraft('');
    setError('');
    setSending(true);
    setMessages((current) => [
      ...current,
      { role: 'user', content },
      { role: 'assistant', content: '' },
    ]);

    try {
      await streamMessage(session, content, (chunk) => {
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last?.role === 'assistant')
            next[next.length - 1] = { ...last, content: last.content + chunk };
          return next;
        });
      });
      window.setTimeout(() => void refreshSessions(), 500);
    } catch (sendError) {
      setError(getErrorMessage(sendError));
      setMessages((current) =>
        current.filter(
          (message, index) => index !== current.length - 1 || message.content,
        ),
      );
      throw sendError;
    } finally {
      setSending(false);
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
    if (!activeSession) return;
    try {
      await clearMessages(activeSession);
      setMessages([]);
      setError('');
    } catch (clearError) {
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
        setActiveSession(remaining[0] ?? null);
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

  return (
    <main className="flex h-screen overflow-hidden bg-[#0c1210]">
      {sidebarOpen && (
        <button
          aria-label="关闭侧栏"
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[288px] flex-col border-r border-white/8 bg-[#101815] transition-transform lg:static lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className="flex h-16 items-center justify-between border-b border-white/8 px-5">
          <div className="flex items-center gap-2.5">
            <div className="grid size-8 place-items-center border border-emerald-300/30 bg-emerald-300/10 text-emerald-300">
              <Sparkles className="size-4" />
            </div>
            <div>
              <p className="font-mono text-xs font-semibold tracking-[0.14em] text-emerald-300">
                FUND AGENT
              </p>
              <p className="text-[10px] text-zinc-600">RESEARCH DESK</p>
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

        <div className="p-3">
          <Button
            variant="outline"
            className="h-10 w-full justify-start rounded-md border-emerald-300/20 bg-emerald-300/5 text-emerald-200 hover:bg-emerald-300/10"
            onClick={() => void handleNewSession()}
          >
            <Plus /> 新建对话
          </Button>
        </div>

        <div className="flex items-center justify-between px-4 pb-2 pt-2">
          <p className="font-mono text-[10px] tracking-[0.16em] text-zinc-600">
            RECENT THREADS
          </p>
          <span className="font-mono text-[10px] text-zinc-700">
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
                  className="h-12 animate-pulse bg-white/[0.035]"
                />
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <div className="mx-2 mt-3 border border-dashed border-white/10 px-4 py-6 text-center">
              <MessageSquare className="mx-auto size-5 text-zinc-600" />
              <p className="mt-2 text-xs text-zinc-600">还没有对话</p>
            </div>
          ) : (
            sessions.map((session) => {
              const isActive = activeSession?.session_id === session.session_id;
              return (
                <div
                  key={session.session_id}
                  className={`group mb-1 flex items-center border-l-2 ${isActive ? 'border-emerald-300 bg-emerald-300/[0.07]' : 'border-transparent hover:bg-white/[0.035]'}`}
                >
                  <button
                    className="min-w-0 flex-1 px-3 py-3 text-left"
                    onClick={() => {
                      setActiveSession(session);
                      setSidebarOpen(false);
                    }}
                  >
                    <p
                      className={`truncate text-sm ${isActive ? 'text-zinc-100' : 'text-zinc-400'}`}
                    >
                      {session.name?.trim() || '新对话'}
                    </p>
                    <p className="mt-1 truncate font-mono text-[9px] uppercase tracking-wider text-zinc-700">
                      {session.session_id.slice(0, 12)}
                    </p>
                  </button>
                  <DropdownMenu>
                    <DropdownMenuTrigger
                      aria-label="会话操作"
                      className="mr-2 grid size-7 place-items-center text-zinc-600 opacity-0 outline-none hover:text-zinc-200 group-hover:opacity-100 focus:opacity-100"
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

        <div className="border-t border-white/8 p-3">
          <DropdownMenu>
            <DropdownMenuTrigger className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left outline-none hover:bg-white/[0.04]">
              <div className="grid size-9 shrink-0 place-items-center bg-emerald-300/10 text-sm font-semibold text-emerald-300">
                {displayName.slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-200">
                  {displayName}
                </p>
                <p className="truncate text-xs text-zinc-600">
                  {auth.user.email}
                </p>
              </div>
              <MoreHorizontal className="size-4 text-zinc-600" />
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-64">
              <DropdownMenuLabel>{auth.user.email}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setAccountOpen(true)}>
                <UserRound /> 账号管理
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={loadingLlm || sending}
                onClick={() => void openLlmSettings()}
              >
                <Settings /> 模型供应商设置
              </DropdownMenuItem>
              {llm?.profiles.map((profile) => (
                <DropdownMenuItem
                  key={profile.name}
                  disabled={
                    loadingLlm || sending || profile.name === llm.active
                  }
                  onClick={() => void selectLlm(profile.name)}
                >
                  <Bot /> {profile.name}
                  {profile.name === llm.active ? '（当前）' : ''}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={onLogout}>
                <LogOut /> 退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/8 bg-[#0c1210]/90 px-4 backdrop-blur-md sm:px-6">
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
            <PanelLeftClose className="hidden size-4 text-zinc-700 lg:block" />
            <div className="min-w-0">
              <h1 className="truncate text-sm font-medium text-zinc-200">
                {activeName}
              </h1>
              <p className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] tracking-wider text-zinc-600">
                <span
                  className={`size-1.5 ${online ? 'bg-emerald-400' : online === false ? 'bg-red-400' : 'bg-zinc-600'}`}
                />
                {online
                  ? 'API ONLINE'
                  : online === false
                    ? 'API OFFLINE'
                    : 'CHECKING API'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1.5 border border-white/8 px-2.5 py-1.5 font-mono text-[10px] text-zinc-500 sm:flex">
              <Clock3 className="size-3" /> STREAM
            </span>
            <AlertDialog>
              <AlertDialogTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={!activeSession || messages.length === 0}
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
          </div>
        </header>

        {error && (
          <div
            role="alert"
            className="flex shrink-0 items-center justify-between border-b border-red-400/15 bg-red-400/[0.06] px-4 py-2 text-xs text-red-300 sm:px-6"
          >
            <span className="flex min-w-0 items-center gap-2">
              <AlertCircle className="size-3.5 shrink-0" />
              <span className="truncate">{error}</span>
            </span>
            <button
              className="ml-3 text-red-300/60 hover:text-red-200"
              onClick={() => setError('')}
              aria-label="关闭错误提示"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}

        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto scroll-smooth"
        >
          <div className="mx-auto flex min-h-full w-full max-w-4xl flex-col px-4 sm:px-8">
            {loadingMessages ? (
              <div className="flex flex-1 items-center justify-center">
                <RefreshCw className="size-5 animate-spin text-emerald-300" />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex flex-1 items-center py-12">
                <div className="w-full">
                  <div className="flex items-center gap-3">
                    <div className="grid size-11 place-items-center border border-emerald-300/25 bg-emerald-300/10 text-emerald-300">
                      <Bot className="size-5" />
                    </div>
                    <div className="h-px flex-1 bg-gradient-to-r from-emerald-300/20 to-transparent" />
                  </div>
                  <p className="mt-7 font-mono text-xs tracking-[0.16em] text-emerald-300">
                    READY FOR ANALYSIS
                  </p>
                  <h2 className="mt-3 max-w-2xl text-3xl font-semibold tracking-[-0.035em] text-zinc-100 sm:text-4xl">
                    今天想研究什么？
                  </h2>
                  <p className="mt-3 max-w-xl text-sm leading-6 text-zinc-500">
                    我会结合当前会话上下文与长期记忆，协助你拆解问题、整理线索并形成清晰结论。
                  </p>
                  <div className="mt-8 grid gap-2 sm:grid-cols-3">
                    {[
                      '分析一只基金的核心风险',
                      '整理今天的市场研究思路',
                      '比较两个投资策略',
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setDraft(suggestion)}
                        className="border border-white/8 bg-white/[0.025] p-4 text-left text-sm leading-5 text-zinc-400 transition-colors hover:border-emerald-300/25 hover:bg-emerald-300/[0.04] hover:text-zinc-200"
                      >
                        <ArrowUp className="mb-3 size-3.5 rotate-45 text-emerald-300/70" />
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-8 py-8 sm:py-12">
                {messages
                  .filter((message) => message.role !== 'system')
                  .map((message, index) => {
                    const isUser = message.role === 'user';
                    return (
                      <Message
                        key={`${index}-${message.role}`}
                        align={isUser ? 'end' : 'start'}
                      >
                        <MessageAvatar
                          className={`size-8 rounded-none ${isUser ? 'bg-zinc-700 text-zinc-300' : 'border border-emerald-300/20 bg-emerald-300/10 text-emerald-300'}`}
                        >
                          {isUser ? (
                            <UserRound className="size-4" />
                          ) : (
                            <Bot className="size-4" />
                          )}
                        </MessageAvatar>
                        <MessageContent className={isUser ? 'items-end' : ''}>
                          <MessageHeader>
                            {isUser ? '你' : 'Fund Agent'}
                          </MessageHeader>
                          <Bubble
                            variant={isUser ? 'secondary' : 'ghost'}
                            align={isUser ? 'end' : 'start'}
                          >
                            <BubbleContent
                              className={
                                isUser
                                  ? 'rounded-md px-4 py-3'
                                  : 'max-w-3xl whitespace-pre-wrap text-[15px] leading-7 text-zinc-300'
                              }
                            >
                              {message.content ||
                                (sending && index === messages.length - 1 ? (
                                  <span className="inline-flex items-center gap-1.5 text-zinc-500">
                                    <span className="size-1.5 animate-pulse bg-emerald-300" />
                                    正在思考…
                                  </span>
                                ) : (
                                  ''
                                ))}
                            </BubbleContent>
                          </Bubble>
                        </MessageContent>
                      </Message>
                    );
                  })}
              </div>
            )}
          </div>
        </div>

        <footer className="shrink-0 border-t border-white/8 bg-[#0c1210] px-4 pb-4 pt-3 sm:px-8 sm:pb-6">
          <div className="mx-auto max-w-4xl">
            <div className="border border-white/10 bg-[#111a17] p-2 shadow-[0_-18px_70px_rgba(0,0,0,.18)] focus-within:border-emerald-300/30">
              <Textarea
                value={draft}
                onChange={(event) =>
                  setDraft(event.target.value.slice(0, 3000))
                }
                onKeyDown={handleComposerKeyDown}
                disabled={sending}
                placeholder={
                  activeSession
                    ? '输入你的研究问题…'
                    : '输入问题，将自动创建新会话…'
                }
                className="max-h-44 min-h-20 resize-none border-0 bg-transparent px-3 py-2 text-[15px] leading-6 shadow-none focus-visible:ring-0"
              />
              <div className="flex items-center justify-between px-2 pb-1 pt-2">
                <div className="flex items-center gap-3 font-mono text-[10px] text-zinc-600">
                  <span>ENTER 发送</span>
                  <span className="hidden sm:inline">SHIFT + ENTER 换行</span>
                  <span>{draft.length}/3000</span>
                </div>
                <Button
                  size="icon"
                  disabled={!draft.trim() || sending}
                  onClick={handleSend}
                  aria-label="发送消息"
                  className="rounded-md"
                >
                  {sending ? (
                    <RefreshCw className="animate-spin" />
                  ) : (
                    <ArrowUp />
                  )}
                </Button>
              </div>
            </div>
            <p className="mt-2 flex items-center justify-center gap-1.5 text-[10px] text-zinc-700">
              <CheckCircle2 className="size-3" />
              AI 生成内容可能存在偏差，请核验关键投资信息。
            </p>
          </div>
        </footer>
      </section>
      {accountOpen && (
        <AccountDialog
          open={accountOpen}
          onOpenChange={setAccountOpen}
          token={auth.token}
          onSaved={onUserUpdated}
        />
      )}
      {llmOpen && (
        <LlmSettingsDialog
          open={llmOpen}
          onOpenChange={setLlmOpen}
          token={auth.token}
          llm={llm}
          onSaved={setLlm}
        />
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
        if (stored) setAuth(JSON.parse(stored) as StoredAuth);
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
      <main className="grid min-h-screen place-items-center bg-[#0c1210]">
        <div className="flex items-center gap-3 font-mono text-xs tracking-[0.15em] text-emerald-300">
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
