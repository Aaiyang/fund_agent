'use client';

import { useState } from 'react';
import {
  CalendarClock,
  Landmark,
  ListChecks,
  Minus,
  Pencil,
  Plus,
  RefreshCw,
  Settings2,
  Upload,
  Wallet,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type AccountItem,
  type PositionItem,
  type PortfolioSummary,
  createAccount,
  getPortfolioSummary,
  getPositions,
  listAccounts,
} from '@/lib/fund-api';
import {
  formatMoney,
  formatReturn,
  formatSignedMoney,
  trendClass,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

export function PortfolioPage({
  token,
  onOpenFund,
  onManageAccounts,
  onOpenImport,
  onOpenTransactions,
  onOpenAutoInvest,
  onEditPosition,
  onTrade,
}: {
  token: string;
  onOpenFund: (code: string) => void;
  onManageAccounts: () => void;
  onOpenImport: () => void;
  onOpenTransactions: () => void;
  onOpenAutoInvest: () => void;
  onEditPosition: (code: string) => void;
  onTrade: (code: string, operation: 'BUY' | 'SELL') => void;
}) {
  const [accountId, setAccountId] = useState<number | null>(null);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const summary = useResource<PortfolioSummary>(
    () => getPortfolioSummary(token, accountId),
    `${token}:${accountId}:summary`,
  );
  const positions = useResource<PositionItem[]>(
    () => getPositions(token, accountId),
    `${token}:${accountId}:positions`,
  );

  async function handleCreateAccount() {
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError('');
    try {
      await createAccount(token, name);
      setNewName('');
      accounts.reload();
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : '创建账户失败');
    } finally {
      setCreating(false);
    }
  }

  const summaryValue = summary.data;
  const activeName =
    accountId === null
      ? '全部账户'
      : (accounts.data ?? []).find((account) => account.id === accountId)
          ?.name ?? `账户 #${accountId}`;

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
            PORTFOLIO
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            持仓
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            按账户看总资产、成本和收益；点基金进入详情。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="rounded-xl" onClick={onOpenImport}>
            <Upload /> 导入持仓
          </Button>
          <Button variant="outline" className="rounded-xl" onClick={onOpenTransactions}>
            <ListChecks /> 流水
          </Button>
          <Button variant="outline" className="rounded-xl" onClick={onOpenAutoInvest}>
            <CalendarClock /> 定投
          </Button>
          <Button variant="outline" className="rounded-xl" onClick={onManageAccounts}>
            <Settings2 /> 账户
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="rounded-xl"
            onClick={() => {
              accounts.reload();
              summary.reload();
              positions.reload();
            }}
            aria-label="刷新持仓"
          >
            <RefreshCw className={accounts.loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setAccountId(null)}
          className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
            accountId === null
              ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
              : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
          }`}
        >
          账户汇总
        </button>
        {(accounts.data ?? []).map((account) => (
          <button
            key={account.id}
            type="button"
            onClick={() => setAccountId(account.id)}
            className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
              accountId === account.id
                ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
            }`}
          >
            {account.name}
          </button>
        ))}
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(260px,0.6fr)]">
        <section className="rounded-[24px] border border-border bg-card p-6 shadow-[0_18px_40px_rgba(33,58,42,0.05)]">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Wallet className="size-4 text-primary" />
            {activeName} · 总资产（元）
          </div>
          <p className="font-display mt-3 text-[38px] font-semibold tracking-tight text-foreground">
            {summaryValue ? formatMoney(summaryValue.total_market_value) : '--'}
          </p>
          <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric
              label="昨日收益"
              value={
                summaryValue
                  ? formatSignedMoney(summaryValue.daily_profit_loss)
                  : '--'
              }
              tone={trendClass(summaryValue?.daily_profit_loss)}
            />
            <Metric
              label="累计收益"
              value={
                summaryValue
                  ? formatSignedMoney(summaryValue.total_profit_loss)
                  : '--'
              }
              tone={trendClass(summaryValue?.total_profit_loss)}
            />
            <Metric
              label="累计收益率"
              value={
                summaryValue
                  ? formatReturn(summaryValue.total_profit_loss_rate)
                  : '--'
              }
              tone={trendClass(summaryValue?.total_profit_loss_rate)}
            />
            <Metric
              label="持仓数量"
              value={summaryValue ? `${summaryValue.fund_count} 只` : '--'}
              tone="text-foreground"
            />
          </div>
          {summary.error && (
            <p className="mt-4 text-xs text-destructive">{summary.error}</p>
          )}
        </section>

        <section className="rounded-[24px] border border-border bg-card/70 p-5">
          <div className="flex items-center gap-2">
            <Landmark className="size-4 text-gold" />
            <p className="text-sm font-semibold text-foreground">账户</p>
          </div>
          {accounts.data?.length ? (
            <div className="mt-3 space-y-2 text-xs text-muted-foreground">
              {accounts.data.map((account) => (
                <button
                  key={account.id}
                  type="button"
                  onClick={() => setAccountId(account.id)}
                  className="flex w-full items-center justify-between rounded-xl border border-border/70 bg-background/50 px-3 py-2 text-left hover:border-primary/25"
                >
                  <span className="truncate">{account.name}</span>
                  <span className="text-text-faint">#{account.id}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-xs leading-6 text-muted-foreground">
              还没有账户。先建一个，再录入或导入持仓。
            </p>
          )}
          <div className="mt-4 flex gap-2">
            <Input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="新账户名称"
              className="h-9 rounded-xl bg-background/60 text-xs"
              onKeyDown={(event) => {
                if (event.key === 'Enter') void handleCreateAccount();
              }}
            />
            <Button
              size="icon-sm"
              className="rounded-xl"
              disabled={!newName.trim() || creating}
              onClick={() => void handleCreateAccount()}
              aria-label="创建账户"
            >
              <Plus />
            </Button>
          </div>
          {createError && (
            <p className="mt-2 text-xs text-destructive">{createError}</p>
          )}
        </section>
      </div>

      <section className="mt-4 rounded-[24px] border border-border bg-card/70 p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">持仓基金</p>
          <span className="text-[11px] text-text-faint">
            {accountId === null ? '选择单个账户查看明细' : activeName}
          </span>
        </div>
        {accountId === null ? (
          <p className="mt-6 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            汇总视图只显示资产卡。选择上方某个账户，即可展开持仓明细。
          </p>
        ) : positions.loading ? (
          <p className="mt-6 flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读持仓…
          </p>
        ) : positions.error ? (
          <p className="mt-4 rounded-xl bg-destructive/[0.05] px-3 py-2 text-sm text-destructive">
            {positions.error}
          </p>
        ) : positions.data?.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-[13px]">
              <thead className="text-[11px] text-text-faint">
                <tr className="border-b border-border">
                  <th className="py-2.5 font-medium">基金</th>
                  <th className="py-2.5 text-right font-medium">市值</th>
                  <th className="py-2.5 text-right font-medium">成本</th>
                  <th className="py-2.5 text-right font-medium">累计收益</th>
                  <th className="py-2.5 text-right font-medium">收益率</th>
                  <th className="py-2.5 text-right font-medium">净值日</th>
                  <th className="py-2.5 pl-4 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {positions.data.map((item) => (
                  <tr
                    key={item.fund_code}
                    className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-primary/[0.025]"
                    onClick={() => onOpenFund(item.fund_code)}
                  >
                    <td className="py-3">
                      <p className="font-medium text-foreground">
                        {item.fund_name ?? item.fund_code}
                      </p>
                      <p className="mt-0.5 text-[10px] text-text-faint">
                        {item.fund_code}
                      </p>
                    </td>
                    <td className="py-3 text-right tabular-nums text-foreground">
                      {formatMoney(item.market_value)}
                    </td>
                    <td className="py-3 text-right tabular-nums text-muted-foreground">
                      {formatMoney(item.cost_amount)}
                    </td>
                    <td
                      className={`py-3 text-right tabular-nums ${trendClass(item.profit_loss)}`}
                    >
                      {formatSignedMoney(item.profit_loss)}
                    </td>
                    <td
                      className={`py-3 text-right tabular-nums ${trendClass(item.profit_loss_rate)}`}
                    >
                      {formatReturn(item.profit_loss_rate)}
                    </td>
                    <td className="py-3 text-right text-[11px] text-text-faint">
                      {item.nav_date?.slice(0, 10) ?? '--'}
                    </td>
                    <td className="py-3 pl-4">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className="rounded-lg text-text-faint hover:text-primary"
                          aria-label={`编辑 ${item.fund_code} 持仓`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onEditPosition(item.fund_code);
                          }}
                        >
                          <Pencil />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className="rounded-lg text-text-faint hover:text-up"
                          aria-label={`加仓 ${item.fund_code}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onTrade(item.fund_code, 'BUY');
                          }}
                        >
                          <Plus />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className="rounded-lg text-text-faint hover:text-down"
                          aria-label={`减仓 ${item.fund_code}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            onTrade(item.fund_code, 'SELL');
                          }}
                        >
                          <Minus />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-6 rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            这个账户还没有持仓。
          </p>
        )}
      </section>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div>
      <p className="text-[11px] text-text-faint">{label}</p>
      <p className={`mt-1 text-[17px] font-semibold tabular-nums ${tone}`}>
        {value}
      </p>
    </div>
  );
}
