'use client';

import { useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowUp, Plus, RefreshCw, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type WatchlistGroup,
  type WatchlistItem,
  createWatchlistGroup,
  deleteWatchlistGroup,
  listWatchlist,
  listWatchlistGroups,
  updateWatchlistGroup,
} from '@/lib/fund-api';
import { useResource } from '@/lib/use-resource';

export function WatchlistGroupsPage({
  token,
  onBack,
}: {
  token: string;
  onBack: () => void;
}) {
  const groups = useResource<WatchlistGroup[]>(
    () => listWatchlistGroups(token),
    token,
  );
  const [newName, setNewName] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftName, setDraftName] = useState('');

  async function create() {
    const name = newName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError('');
    try {
      const group = await createWatchlistGroup(token, name);
      setNewName('');
      setSelectedId(group.id);
      groups.reload();
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '创建分组失败');
    } finally {
      setBusy(false);
    }
  }

  async function rename(group: WatchlistGroup) {
    const name = draftName.trim();
    if (!name || busy) return;
    setBusy(true);
    setError('');
    try {
      await updateWatchlistGroup(token, group.id, { name });
      setEditingId(null);
      groups.reload();
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : '改名失败');
    } finally {
      setBusy(false);
    }
  }

  async function remove(group: WatchlistGroup) {
    if (
      !window.confirm(
        `删除分组“${group.name}”？组内基金仍保留在自选，只是不再属于这个分组。`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await deleteWatchlistGroup(token, group.id);
      if (selectedId === group.id) setSelectedId(null);
      groups.reload();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : '删除分组失败');
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
            GROUPS
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            自选分组
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            新建、改名、删除分组，并调整组内基金顺序。
          </p>
        </div>
        <Button variant="outline" className="rounded-xl" onClick={() => groups.reload()}>
          <RefreshCw className={groups.loading ? 'animate-spin' : ''} /> 刷新
        </Button>
      </div>

      <section className="mt-5 rounded-[24px] border border-border bg-card/75 p-5">
        <p className="text-sm font-semibold text-foreground">新建分组</p>
        <div className="mt-3 flex max-w-xl gap-2">
          <Input
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder="比如：稳健配置"
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
        <p className="text-sm font-semibold text-foreground">分组列表</p>
        {groups.loading ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读分组…
          </p>
        ) : (groups.data?.length ?? 0) === 0 ? (
          <p className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            还没有分组。默认视图“全部”始终可用。
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {groups.data?.map((group) => (
              <div
                key={group.id}
                className={`rounded-2xl border px-4 py-3 transition-colors ${
                  selectedId === group.id
                    ? 'border-primary/25 bg-primary/[0.04]'
                    : 'border-border/70 bg-background/40'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setSelectedId(group.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className="text-sm font-medium text-foreground">
                      {group.name}
                    </span>
                    <span className="ml-2 text-[11px] text-text-faint">
                      {group.fund_count ?? 0} 只基金
                    </span>
                  </button>
                  {editingId === group.id ? (
                    <div className="flex gap-2">
                      <Input
                        value={draftName}
                        onChange={(event) => setDraftName(event.target.value)}
                        className="h-8 w-40 rounded-lg bg-card text-xs"
                        autoFocus
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') void rename(group);
                          if (event.key === 'Escape') setEditingId(null);
                        }}
                      />
                      <Button
                        size="sm"
                        className="rounded-lg"
                        disabled={busy || !draftName.trim()}
                        onClick={() => void rename(group)}
                      >
                        保存
                      </Button>
                    </div>
                  ) : (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="rounded-lg"
                        onClick={() => {
                          setEditingId(group.id);
                          setDraftName(group.name);
                        }}
                      >
                        改名
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="rounded-lg text-text-faint hover:text-destructive"
                        onClick={() => void remove(group)}
                        aria-label={`删除分组 ${group.name}`}
                      >
                        <Trash2 />
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {selectedId !== null && (
        <GroupOrderEditor
          key={selectedId}
          token={token}
          groupId={selectedId}
          onSaved={() => groups.reload()}
        />
      )}
    </div>
  );
}

function GroupOrderEditor({
  token,
  groupId,
  onSaved,
}: {
  token: string;
  groupId: number;
  onSaved: () => void;
}) {
  const members = useResource<WatchlistItem[]>(
    () => listWatchlist(token, groupId),
    `${token}:${groupId}:group-members`,
  );
  const [order, setOrder] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const items = members.data ?? [];
  const codes = order ?? items.map((item) => item.fund_code);
  const names = new Map(items.map((item) => [item.fund_code, item.fund_name]));

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= codes.length) return;
    const next = [...codes];
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next);
  }

  async function save() {
    setBusy(true);
    setError('');
    try {
      await updateWatchlistGroup(token, groupId, { fund_codes: codes });
      setOrder(null);
      onSaved();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '保存顺序失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-foreground">组内排序</p>
        {order && <span className="text-[10px] text-gold">有未保存的调整</span>}
      </div>
      {members.loading ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-text-faint">
          <RefreshCw className="size-3.5 animate-spin text-primary" /> 正在读成员…
        </p>
      ) : items.length === 0 ? (
        <p className="mt-3 rounded-xl border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
          这个分组还没有基金。在自选页添加时勾选该分组即可。
        </p>
      ) : (
        <div className="mt-3 space-y-1">
          {codes.map((code, index) => (
            <div
              key={code}
              className="flex items-center gap-3 rounded-xl border border-border/60 bg-background/40 px-3 py-2"
            >
              <span className="w-6 text-[10px] tabular-nums text-text-faint">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                {names.get(code) ?? code}
              </span>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={index === 0}
                onClick={() => move(index, -1)}
                aria-label={`上移 ${code}`}
              >
                <ArrowUp />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={index === codes.length - 1}
                onClick={() => move(index, 1)}
                aria-label={`下移 ${code}`}
              >
                <ArrowDown />
              </Button>
            </div>
          ))}
          {error && <p className="text-xs text-destructive">{error}</p>}
          <Button
            className="mt-3 h-9 rounded-xl"
            disabled={!order || busy}
            onClick={() => void save()}
          >
            {busy ? <RefreshCw className="animate-spin" /> : null} 保存组内顺序
          </Button>
        </div>
      )}
    </section>
  );
}
