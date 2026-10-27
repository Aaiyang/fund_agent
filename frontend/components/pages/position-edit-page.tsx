'use client';

import { useState } from 'react';
import { ArrowLeft, RefreshCw, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type AccountItem,
  type FundDetail,
  type PositionItem,
  type TradeOperation,
  deletePosition,
  getFundDetail,
  getPosition,
  listAccounts,
  upsertPosition,
} from '@/lib/fund-api';
import {
  formatMoney,
  formatNav,
  formatNumber,
  formatSignedMoney,
  localToday,
  trendClass,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

type Mode = 'amount' | 'shares';

export function PositionEditPage({
  token,
  code,
  initialAccountId = null,
  onBack,
  onDone,
  onTrade,
  onOpenAutoInvest,
}: {
  token: string;
  code: string;
  initialAccountId?: number | null;
  onBack: () => void;
  onDone: () => void;
  onTrade: (operation: TradeOperation) => void;
  onOpenAutoInvest: () => void;
}) {
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const selectedAccount = accountId ?? accounts.data?.[0]?.id ?? null;
  const position = useResource<PositionItem | null>(
    async () => {
      if (!selectedAccount) return null;
      try {
        return await getPosition(token, selectedAccount, code);
      } catch {
        return null;
      }
    },
    `${token}:${selectedAccount}:${code}`,
  );

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <div className="mt-5">
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          POSITION
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          同步持仓 · {code}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          快照通道：把第三方持仓页上的数字照实转述进来，不按日期定价。
        </p>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {(accounts.data ?? []).map((account) => (
          <button
            key={account.id}
            type="button"
            onClick={() => setAccountId(account.id)}
            className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
              selectedAccount === account.id
                ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
            }`}
          >
            {account.name}
          </button>
        ))}
      </div>

      {position.loading ? (
        <p className="mt-8 flex items-center gap-2 text-sm text-text-faint">
          <RefreshCw className="size-4 animate-spin text-primary" /> 正在读持仓…
        </p>
      ) : (
        <PositionForm
          key={`${selectedAccount}:${position.data?.version ?? 'new'}`}
          token={token}
          code={code}
          accountId={selectedAccount}
          existing={position.data}
          onDone={onDone}
          onTrade={onTrade}
          onOpenAutoInvest={onOpenAutoInvest}
        />
      )}
    </div>
  );
}

function PositionForm({
  token,
  code,
  accountId,
  existing,
  onDone,
  onTrade,
  onOpenAutoInvest,
}: {
  token: string;
  code: string;
  accountId: number | null;
  existing: PositionItem | null;
  onDone: () => void;
  onTrade: (operation: TradeOperation) => void;
  onOpenAutoInvest: () => void;
}) {
  const detail = useResource<FundDetail>(
    () => getFundDetail(token, code),
    `${token}:${code}`,
  );
  const [purchaseDate, setPurchaseDate] = useState(
    existing?.purchase_date ?? localToday(),
  );
  const [mode, setMode] = useState<Mode>('amount');
  const [marketValue, setMarketValue] = useState(text(existing?.market_value));
  const [shares, setShares] = useState(text(existing?.shares));
  const [costNav, setCostNav] = useState(text(existing?.average_cost_nav));
  const [profitLoss, setProfitLoss] = useState(text(existing?.profit_loss));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const traded = (existing?.trade_count ?? 0) > 0;
  const nav = detail.data?.latest_nav ?? existing?.unit_nav ?? null;

  const amount = number(marketValue);
  const typedShares = number(shares);
  const typedCostNav = number(costNav);
  const typedProfit = number(profitLoss);
  const byAmount = mode === 'amount' || traded;
  const resolvedAmount =
    byAmount && amount !== null
      ? amount
      : !byAmount && typedShares !== null && nav
        ? typedShares * nav
        : null;
  const resolvedShares =
    byAmount && resolvedAmount !== null && nav
      ? resolvedAmount / nav
      : (typedShares ??
        (resolvedAmount !== null && nav ? resolvedAmount / nav : null));
  const resolvedProfit = byAmount ? typedProfit : null;
  const basis =
    resolvedProfit !== null && resolvedAmount !== null
      ? resolvedAmount - resolvedProfit
      : !byAmount && typedCostNav !== null && resolvedShares
        ? typedCostNav * resolvedShares
        : (existing?.cost_amount ?? null);
  const resolvedCostNav =
    !byAmount && typedCostNav !== null
      ? typedCostNav
      : basis !== null && resolvedShares
        ? basis / resolvedShares
        : null;
  const result = traded
    ? {
        market_value: amount ?? existing?.market_value ?? null,
        shares: existing?.shares ?? null,
        cost_amount: existing?.cost_amount ?? null,
        profit_loss: existing?.profit_loss ?? null,
        average_cost_nav: existing?.average_cost_nav ?? null,
      }
    : {
        market_value: resolvedAmount,
        shares: resolvedShares,
        cost_amount: basis,
        profit_loss:
          resolvedProfit ??
          (resolvedAmount !== null && basis !== null
            ? resolvedAmount - basis
            : null),
        average_cost_nav: resolvedCostNav,
      };
  const hasMoney = [
    result.market_value,
    result.shares,
    result.cost_amount,
    result.profit_loss,
    result.average_cost_nav,
  ].some((value) => value !== null);

  async function submit() {
    if (busy) return;
    setProblem('');
    if (accountId === null) {
      setProblem('请先创建或选择持仓账户');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(purchaseDate)) {
      setProblem('首次购买日期需为 YYYY-MM-DD');
      return;
    }
    for (const value of [marketValue, shares, costNav, profitLoss]) {
      if (value.trim() !== '' && Number.isNaN(Number(value))) {
        setProblem('持仓数字需为数字');
        return;
      }
    }
    setBusy(true);
    try {
      const sentShares = !traded && mode === 'shares' ? number(shares) : null;
      const sentCostNav =
        !traded && mode === 'shares' ? number(costNav) : null;
      const sentProfit =
        !traded && mode === 'amount' ? number(profitLoss) : null;
      await upsertPosition(token, code, {
        account_id: accountId,
        market_value: traded ? amount : result.market_value,
        shares: sentShares,
        average_cost_nav: sentCostNav,
        profit_loss: sentProfit,
        purchase_date: purchaseDate.trim() || null,
        reset: traded
          ? []
          : (
              [
                ['shares', sentShares],
                ['average_cost_nav', sentCostNav],
                ['profit_loss', sentProfit],
              ] as const
            )
              .filter(
                ([column, sent]) =>
                  sent === null &&
                  !isDerived(existing, column) &&
                  stored(existing, column) !== null,
              )
              .map(([column]) => column),
        expected_version: existing?.version ?? null,
      });
      onDone();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '保存持仓失败');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!existing || accountId === null) return;
    if (
      !window.confirm(
        `${code} 在本账户的持仓、全部流水与定投计划都会被删除，删除后无法恢复。`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await deletePosition(token, accountId, code);
      onDone();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '删除持仓失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(300px,0.8fr)]">
      <section className="rounded-[24px] border border-border bg-card/75 p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-foreground">
              {detail.data?.fund_name ?? code}
            </p>
            <p className="mt-1 text-[11px] text-text-faint">
              {code} · 最新净值 {formatNav(nav)}
              {existing
                ? ` · 已持有 ${formatMoney(existing.market_value)}`
                : ' · 该账户下还没有这只基金的持仓'}
            </p>
          </div>
          {existing && (
            <Button
              variant="ghost"
              size="sm"
              className="rounded-lg text-text-faint hover:text-destructive"
              onClick={() => void remove()}
              disabled={busy}
            >
              <Trash2 /> 删除持仓
            </Button>
          )}
        </div>

        <label className="mt-4 block text-xs text-muted-foreground">
          首次购买日期
          <Input
            type="date"
            value={purchaseDate}
            onChange={(event) => setPurchaseDate(event.target.value)}
            className="mt-1.5 h-10 rounded-xl bg-background/60"
          />
        </label>

        {traded ? (
          <p className="mt-3 rounded-xl border border-border/70 bg-secondary/30 px-3 py-2 text-[11px] leading-5 text-text-soft">
            这只基金记过 {existing?.trade_count} 笔买卖，份额与持仓成本以流水为准；这里只改持有金额和日期。
          </p>
        ) : (
          <>
            <div className="mt-4 flex gap-2">
              {(['amount', 'shares'] as Mode[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMode(value)}
                  className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
                    mode === value
                      ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                      : 'border-border bg-background/50 text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {value === 'amount' ? '按金额填' : '按份额填'}
                </button>
              ))}
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field
                label="持有金额"
                value={marketValue}
                onChange={setMarketValue}
              />
              {mode === 'amount' ? (
                <Field
                  label="持有收益"
                  value={profitLoss}
                  onChange={setProfitLoss}
                />
              ) : (
                <>
                  <Field label="持有份额" value={shares} onChange={setShares} />
                  <Field
                    label="持有成本（净值）"
                    value={costNav}
                    onChange={setCostNav}
                  />
                </>
              )}
            </div>
            <p className="mt-2 text-[10px] text-text-faint">
              {mode === 'shares'
                ? `金额按最新净值 ${formatNav(nav)} 折算，成本 = 成本净值 × 份额。`
                : '份额按最新净值折算，成本 = 金额 − 收益。'}
            </p>
          </>
        )}

        {problem && (
          <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
            {problem}
          </p>
        )}
        <Button
          className="mt-4 h-10 w-full rounded-xl"
          disabled={busy}
          onClick={() => void submit()}
        >
          {busy ? <RefreshCw className="animate-spin" /> : null} 保存持仓
        </Button>
      </section>

      <div className="space-y-4">
        {hasMoney && (
          <section className="rounded-[24px] border border-border bg-card/75 p-5">
            <p className="text-sm font-semibold text-foreground">持仓结果</p>
            <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
              <Result label="持有金额" value={formatMoney(result.market_value)} />
              <Result label="持有份额" value={formatNumber(result.shares)} />
              <Result label="持仓成本" value={formatMoney(result.cost_amount)} />
              <Result
                label="平均成本净值"
                value={formatNav(result.average_cost_nav)}
              />
              <Result
                label="持有收益"
                value={formatSignedMoney(result.profit_loss)}
                tone={trendClass(result.profit_loss)}
              />
              <Result
                label="收益率"
                value={
                  result.profit_loss != null && result.cost_amount
                    ? `${((result.profit_loss / result.cost_amount) * 100).toFixed(2)}%`
                    : '--'
                }
                tone={trendClass(result.profit_loss)}
              />
            </div>
          </section>
        )}

        <section className="rounded-[24px] border border-border bg-card/75 p-5">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-foreground">加减仓</p>
            <button
              type="button"
              onClick={onOpenAutoInvest}
              className="text-xs text-primary hover:underline"
            >
              定投计划
            </button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {(
              [
                ['BUY', '同步加仓'],
                ['SELL', '同步减仓'],
                ['AUTO_INVEST', '同步定投'],
                ['CONVERT', '同步转换'],
              ] as Array<[TradeOperation, string]>
            ).map(([operation, label]) => (
              <Button
                key={operation}
                variant="outline"
                className="h-9 rounded-xl text-xs"
                disabled={!existing}
                onClick={() => onTrade(operation)}
              >
                {label}
              </Button>
            ))}
          </div>
          {!existing && (
            <p className="mt-2 text-[10px] text-text-faint">
              先保存一笔持仓，才能记录买卖流水。
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-xs text-muted-foreground">
      {label}
      <Input
        inputMode="decimal"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 h-10 rounded-xl bg-background/60"
      />
    </label>
  );
}

function Result({
  label,
  value,
  tone = 'text-foreground',
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <p className="text-[10px] text-text-faint">{label}</p>
      <p className={`mt-0.5 tabular-nums ${tone}`}>{value}</p>
    </div>
  );
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? '' : String(value);
}

function number(value: string): number | null {
  return value.trim() === '' || Number.isNaN(Number(value))
    ? null
    : Number(value);
}

function isDerived(
  existing: PositionItem | null,
  column: 'shares' | 'average_cost_nav' | 'profit_loss',
): boolean {
  if (!existing) return false;
  if (column === 'shares') return Boolean(existing.shares_derived);
  if (column === 'average_cost_nav')
    return Boolean(existing.average_cost_nav_derived);
  return Boolean(existing.profit_derived);
}

function stored(
  existing: PositionItem | null,
  column: 'shares' | 'average_cost_nav' | 'profit_loss',
): number | null {
  if (!existing || isDerived(existing, column)) return null;
  return existing[column] ?? null;
}
