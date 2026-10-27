'use client';

import { useState } from 'react';
import { ArrowLeft, Landmark, Plus, RefreshCw, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type AccountItem,
  createAccount,
  deleteAccount,
  listAccounts,
  updateAccount,
} from '@/lib/fund-api';
import { formatDateTime } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

export function AccountsPage({
  token,
  onBack,
  onOpenPortfolio,
}: {
  token: string;
  onBack: () => void;
  onOpenPortfolio: () => void;
}) {
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState('');

  async function create() {
    const name = newName.trim();
    if (!name || busy) return;
    if ((accounts.data ?? []).some((item) => item.name === name)) {
      setError('该账户名称已存在');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await createAccount(token, name);
      setNewName('');
      accounts.reload();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '创建账户失败');
    } finally {
      setBusy(false);
    }
  }

  async function rename(account: AccountItem) {
    const name = draftName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError('');
    try {
      await updateAccount(token, account.id, name);
      setEditingId(null);
      accounts.reload();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : '改名失败');
    } finally {
      setBusy(false);
    }
  }

  async function remove(account: AccountItem) {
    if (busy) return;
    if (
      !window.confirm(
        `删除账户“${account.name}”？该账户的持仓、调整记录与导入批次都会删除，且无法恢复。`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await deleteAccount(token, account.id);
      accounts.reload();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : '删除账户失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
            ACCOUNTS
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            账户管理
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            每个账户独立保存持仓与导入记录，可随时改名或删除。
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="rounded-xl" onClick={onOpenPortfolio}>
            查看持仓
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="rounded-xl"
            onClick={() => accounts.reload()}
            aria-label="刷新账户"
          >
            <RefreshCw className={accounts.loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      <section className="mt-5 rounded-[24px] border border-border bg-card/75 p-5">
        <p className="text-sm font-semibold text-foreground">新建账户</p>
        <div className="mt-3 flex max-w-xl gap-2">
          <Input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder="比如：支付宝 · 主动基金"
            className="h-10 rounded-xl bg-background/60"
            onKeyDown={(event) => {
              if (event.key === 'Enter') void create();
            }}
          />
          <Button
            className="h-10 rounded-xl"
            disabled={!newName.trim() || busy}
            onClick={() => void create()}
          >
            <Plus /> 创建
          </Button>
        </div>
        {error && (
          <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
            {error}
          </p>
        )}
      </section>

      <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">全部账户</p>
          <span className="text-[11px] text-text-faint">
            {accounts.data?.length ?? 0} 个
          </span>
        </div>
        {accounts.loading ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读账户…
          </p>
        ) : accounts.error ? (
          <p className="mt-4 text-sm text-destructive">{accounts.error}</p>
        ) : (accounts.data?.length ?? 0) === 0 ? (
          <p className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            还没有账户。先创建一个，再录入或导入持仓。
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {accounts.data?.map((account) => (
              <div
                key={account.id}
                className="rounded-2xl border border-border/70 bg-background/40 px-4 py-3"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-xl bg-primary/[0.07] text-primary">
                    <Landmark className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">
                      {account.name}
                    </p>
                    <p className="mt-0.5 text-[10px] text-text-faint">
                      来源 {account.source_app ?? '未标注'} · 导入方式{' '}
                      {account.import_mode} · 最近导入{' '}
                      {formatDateTime(account.last_imported_at)}
                    </p>
                  </div>
                  {editingId === account.id ? (
                    <div className="flex w-full max-w-md gap-2 sm:w-auto">
                      <Input
                        value={draftName}
                        onChange={(event) => setDraftName(event.target.value)}
                        className="h-8 rounded-lg bg-card text-xs"
                        autoFocus
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void rename(account);
                          if (event.key === 'Escape') setEditingId(null);
                        }}
                      />
                      <Button
                        size="sm"
                        className="rounded-lg"
                        disabled={busy || !draftName.trim()}
                        onClick={() => void rename(account)}
                      >
                        保存
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="rounded-lg"
                        onClick={() => setEditingId(null)}
                      >
                        取消
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="rounded-lg"
                        onClick={() => {
                          setEditingId(account.id);
                          setDraftName(account.name);
                        }}
                      >
                        改名
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="rounded-lg text-text-faint hover:text-destructive"
                        disabled={busy}
                        onClick={() => void remove(account)}
                        aria-label={`删除账户 ${account.name}`}
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
