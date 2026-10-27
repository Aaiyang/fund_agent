'use client';

import { useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { type CurrentUser, type UserProfile, updateProfile } from '@/lib/api';
import { formatDateTime } from '@/lib/fund-format';

export function ProfileEditPage({
  token,
  user,
  onBack,
  onSaved,
}: {
  token: string;
  user: UserProfile & { created_at?: string | null };
  onBack: () => void;
  onSaved: (user: CurrentUser) => void;
}) {
  const [username, setUsername] = useState(user.username ?? '');
  const [email, setEmail] = useState(user.email);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  async function submit() {
    setProblem('');
    const nextEmail = email.trim();
    if (!nextEmail) {
      setProblem('请输入邮箱');
      return;
    }
    const payload: { email?: string; username?: string } = {};
    if (username.trim() !== (user.username ?? '')) payload.username = username.trim();
    if (nextEmail !== user.email) payload.email = nextEmail;
    if (Object.keys(payload).length === 0) {
      setProblem('没有需要保存的修改');
      return;
    }
    setBusy(true);
    try {
      onSaved(await updateProfile(token, payload));
      onBack();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '保存资料失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <div className="mt-5">
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          PROFILE
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          编辑资料
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          用户 #{user.id} · 注册于 {formatDateTime(user.created_at)}
        </p>
      </div>

      <section className="mt-5 rounded-[24px] border border-border bg-card/75 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-xs text-muted-foreground">
            昵称
            <Input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入昵称"
              className="mt-1.5 h-10 rounded-xl bg-background/60"
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            邮箱
            <Input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="请输入邮箱"
              className="mt-1.5 h-10 rounded-xl bg-background/60"
            />
          </label>
        </div>
        {problem && (
          <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
            {problem}
          </p>
        )}
        <Button
          className="mt-4 h-10 rounded-xl"
          disabled={busy}
          onClick={() => void submit()}
        >
          {busy ? <RefreshCw className="animate-spin" /> : null} 保存
        </Button>
      </section>
    </div>
  );
}
