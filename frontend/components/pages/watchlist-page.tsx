'use client';

import { useEffect, useState } from 'react';
import { FolderCog, Plus, RefreshCw, Search, Star, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type FundSearchItem,
  type WatchlistGroup,
  type WatchlistItem,
  addWatchlistFund,
  listWatchlist,
  listWatchlistGroups,
  removeWatchlistFund,
  searchFunds,
} from '@/lib/fund-api';
import { formatDate, formatNav, formatReturn, trendClass } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

export function WatchlistPage({
  token,
  onOpenFund,
  onOpenGroups,
}: {
  token: string;
  onOpenFund: (code: string) => void;
  onOpenGroups: () => void;
}) {
  const [groupId, setGroupId] = useState<number | null>(null);
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState<FundSearchItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [pendingCode, setPendingCode] = useState('');
  const [picking, setPicking] = useState<FundSearchItem | null>(null);
  const [pickedGroups, setPickedGroups] = useState<number[]>([]);
  const [error, setError] = useState('');
  const list = useResource<WatchlistItem[]>(
    () => listWatchlist(token, groupId),
    `${token}:${groupId}:list`,
  );
  const groups = useResource<WatchlistGroup[]>(
    () => listWatchlistGroups(token),
    token,
  );

  useEffect(() => {
    const query = keyword.trim();
    if (!query) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setSearching(true);
      void searchFunds(token, query)
        .then((items) => {
          if (!cancelled) setResults(items);
        })
        .catch((searchError: unknown) => {
          if (!cancelled)
            setError(searchError instanceof Error ? searchError.message : '搜索失败');
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, 260);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [keyword, token]);

  async function handleAdd(code: string, groupIds: number[] = []) {
    setPendingCode(code);
    setError('');
    try {
      await addWatchlistFund(token, code, groupIds);
      list.reload();
      groups.reload();
      setResults((current) =>
        current.map((item) =>
          item.fund_code === code ? { ...item, is_watchlisted: true } : item,
        ),
      );
      setPicking(null);
      setPickedGroups([]);
    } catch (addError) {
      setError(addError instanceof Error ? addError.message : '添加自选失败');
    } finally {
      setPendingCode('');
    }
  }

  async function handleRemove(code: string) {
    setPendingCode(code);
    setError('');
    try {
      await removeWatchlistFund(token, code);
      list.reload();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : '移除自选失败');
    } finally {
      setPendingCode('');
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
            WATCHLIST
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            自选
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            把想持续观察的基金放在一起，按分组筛选。
          </p>
        </div>
        <div className="flex w-full max-w-md items-center gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-faint" />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索基金代码或名称"
              className="h-10 rounded-xl bg-card pl-9"
            />
          </div>
          <Button
            variant="outline"
            size="icon"
            className="rounded-xl"
            onClick={onOpenGroups}
            aria-label="管理自选分组"
          >
            <FolderCog />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="rounded-xl"
            onClick={() => {
              list.reload();
              groups.reload();
            }}
            aria-label="刷新自选"
          >
            <RefreshCw className={list.loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      {keyword.trim() && (
        <section className="mt-4 rounded-2xl border border-border bg-card/75 p-3 shadow-[0_12px_28px_rgba(33,58,42,0.04)]">
          <p className="px-1 pb-2 text-[10px] font-semibold tracking-[0.18em] text-muted-foreground">
            搜索结果
          </p>
          {searching ? (
            <p className="px-2 py-3 text-xs text-text-faint">正在搜索…</p>
          ) : results.length === 0 ? (
            <p className="px-2 py-3 text-xs text-text-faint">
              没找到匹配的基金，换个代码或名称试试。
            </p>
          ) : (
            <div className="space-y-1">
              {results.map((item) => (
                <div
                  key={item.fund_code}
                  className="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-primary/[0.035]"
                >
                  <button
                    type="button"
                    onClick={() => onOpenFund(item.fund_code)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <p className="truncate text-sm font-medium text-foreground">
                      {item.fund_name}
                    </p>
                    <p className="mt-0.5 text-[10px] text-text-faint">
                      {item.fund_code} · {item.fund_type ?? '基金'}
                    </p>
                  </button>
                  <span
                    className={`text-xs tabular-nums ${trendClass(item.daily_return)}`}
                  >
                    {formatReturn(item.daily_return, { points: true })}
                  </span>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    className="rounded-lg"
                    disabled={item.is_watchlisted || pendingCode === item.fund_code}
                    onClick={() => {
                      setPicking(item);
                      setPickedGroups([]);
                      setError('');
                    }}
                    aria-label={`添加 ${item.fund_code} 到自选`}
                  >
                    {item.is_watchlisted ? <Star className="text-gold" /> : <Plus />}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {picking && (
        <section className="mt-4 rounded-2xl border border-primary/20 bg-primary/[0.04] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-medium text-foreground">
                添加 {picking.fund_name}
              </p>
              <p className="mt-0.5 text-[10px] text-text-faint">
                {picking.fund_code} · 可同时加入多个分组
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="rounded-lg"
              onClick={() => setPicking(null)}
            >
              取消
            </Button>
          </div>
          {(groups.data?.length ?? 0) > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(groups.data ?? []).map((group) => {
                const active = pickedGroups.includes(group.id);
                return (
                  <button
                    key={group.id}
                    type="button"
                    onClick={() =>
                      setPickedGroups((current) =>
                        active
                          ? current.filter((id) => id !== group.id)
                          : [...current, group.id],
                      )
                    }
                    className={`rounded-full border px-3 py-1 text-[11px] ${
                      active
                        ? 'border-primary/25 bg-primary/[0.08] text-primary'
                        : 'border-border bg-card text-text-soft'
                    }`}
                  >
                    {active ? '✓ ' : ''}
                    {group.name}
                  </button>
                );
              })}
            </div>
          )}
          <Button
            className="mt-3 h-8 rounded-lg text-xs"
            disabled={pendingCode === picking.fund_code}
            onClick={() => void handleAdd(picking.fund_code, pickedGroups)}
          >
            <Plus /> 加入自选
          </Button>
        </section>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setGroupId(null)}
          className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
            groupId === null
              ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
              : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
          }`}
        >
          全部
        </button>
        {(groups.data ?? []).map((group) => (
          <button
            key={group.id}
            type="button"
            onClick={() => setGroupId(group.id)}
            className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
              groupId === group.id
                ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
            }`}
          >
            {group.name}（{group.fund_count ?? 0}）
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
          {error}
        </p>
      )}

      <section className="mt-4 overflow-hidden rounded-[24px] border border-border bg-card/75">
        {list.loading ? (
          <p className="flex items-center gap-2 px-5 py-8 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读自选…
          </p>
        ) : list.error ? (
          <p className="px-5 py-8 text-sm text-destructive">{list.error}</p>
        ) : (list.data?.length ?? 0) === 0 ? (
          <p className="px-5 py-12 text-center text-sm text-muted-foreground">
            还没有自选基金。用右上角搜索框按代码或名称添加。
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-[13px]">
              <thead className="bg-secondary/45 text-[11px] text-text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">基金</th>
                  <th className="px-3 py-3 text-right font-medium">最新净值</th>
                  <th className="px-3 py-3 text-right font-medium">日</th>
                  <th className="px-3 py-3 text-right font-medium">近1月</th>
                  <th className="px-3 py-3 text-right font-medium">近1年</th>
                  <th className="px-3 py-3 text-right font-medium">净值日</th>
                  <th className="px-5 py-3">
                    <span className="sr-only">操作</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.data?.map((item) => (
                  <tr
                    key={item.fund_code}
                    className="cursor-pointer border-t border-border/60 hover:bg-primary/[0.025]"
                    onClick={() => onOpenFund(item.fund_code)}
                  >
                    <td className="px-5 py-3">
                      <p className="font-medium text-foreground">{item.fund_name}</p>
                      <p className="mt-0.5 text-[10px] text-text-faint">
                        {item.fund_code} · {item.fund_type ?? '基金'}
                        {item.is_held ? ' · 持有中' : ''}
                      </p>
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-foreground">
                      {formatNav(item.latest_nav)}
                    </td>
                    <td
                      className={`px-3 py-3 text-right tabular-nums ${trendClass(item.daily_return)}`}
                    >
                      {formatReturn(item.daily_return, { points: true })}
                    </td>
                    <td
                      className={`px-3 py-3 text-right tabular-nums ${trendClass(item.monthly_return)}`}
                    >
                      {formatReturn(item.monthly_return, { points: true })}
                    </td>
                    <td
                      className={`px-3 py-3 text-right tabular-nums ${trendClass(item.annual_return)}`}
                    >
                      {formatReturn(item.annual_return, { points: true })}
                    </td>
                    <td className="px-3 py-3 text-right text-[11px] text-text-faint">
                      {formatDate(item.nav_date)}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        className="rounded-lg text-text-faint hover:text-destructive"
                        disabled={pendingCode === item.fund_code}
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleRemove(item.fund_code);
                        }}
                        aria-label={`移除 ${item.fund_code}`}
                      >
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
