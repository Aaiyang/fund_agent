'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type AccountItem,
  type FundDetail,
  type PositionItem,
  type TradeOperation,
  type TradePreview,
  getFundDetail,
  getPosition,
  listAccounts,
  previewTrade,
  recordTrade,
} from '@/lib/fund-api';
import {
  formatMoney,
  formatNav,
  formatNumber,
  formatReturn,
  formatSignedMoney,
  localToday,
  trendClass,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const OPERATIONS: Array<{
  key: TradeOperation;
  label: string;
  verb: string;
  byMoney: boolean;
  pickDate: boolean;
  amountLabel: string;
}> = [
  { key: 'BUY', label: '加仓', verb: '确认加仓', byMoney: true, pickDate: true, amountLabel: '买入金额' },
  { key: 'SELL', label: '减仓', verb: '确认减仓', byMoney: false, pickDate: true, amountLabel: '' },
  { key: 'AUTO_INVEST', label: '定投', verb: '确认定投', byMoney: true, pickDate: false, amountLabel: '本期定投金额' },
  { key: 'CONVERT', label: '转换', verb: '确认转换', byMoney: false, pickDate: true, amountLabel: '' },
];

export function TradePage({
  token,
  code,
  initialOperation,
  initialAccountId = null,
  onBack,
  onDone,
  onOpenAutoInvest,
}: {
  token: string;
  code: string;
  initialOperation: TradeOperation;
  initialAccountId?: number | null;
  onBack: () => void;
  onDone: () => void;
  onOpenAutoInvest: () => void;
}) {
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const [operation, setOperation] = useState<TradeOperation>(initialOperation);
  const entry = OPERATIONS.find((item) => item.key === operation) ?? OPERATIONS[0];
  const detail = useResource<FundDetail>(
    () => getFundDetail(token, code),
    `${token}:${code}`,
  );
  const selectedAccount =
    accountId ?? accounts.data?.[0]?.id ?? null;
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
  const [amount, setAmount] = useState('');
  const [shares, setShares] = useState('');
  const [targetCode, setTargetCode] = useState('');
  const [tradeDate, setTradeDate] = useState(localToday());
  const [afterCutoff, setAfterCutoff] = useState(false);
  const [preview, setPreview] = useState<{
    key: string;
    data: TradePreview | null;
    error: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  const sized = entry.byMoney ? amount.trim() !== '' : shares.trim() !== '';
  const previewKey = `${selectedAccount}:${operation}:${tradeDate}:${afterCutoff}:${amount}:${shares}:${targetCode}`;

  useEffect(() => {
    if (!selectedAccount || !sized || !/^\d{4}-\d{2}-\d{2}$/.test(tradeDate)) {
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void previewTrade(token, code, {
        accountId: selectedAccount,
        operation,
        tradeDate,
        afterCutoff,
        amount,
        shares,
        targetCode,
      })
        .then((data) => {
          if (!cancelled) setPreview({ key: previewKey, data, error: '' });
        })
        .catch((error: unknown) => {
          if (!cancelled)
            setPreview({
              key: previewKey,
              data: null,
              error: error instanceof Error ? error.message : '预览失败',
            });
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    token,
    code,
    selectedAccount,
    operation,
    tradeDate,
    afterCutoff,
    amount,
    shares,
    targetCode,
    sized,
    previewKey,
  ]);

  const activePreview = preview?.key === previewKey ? preview : null;
  const held = position.data?.shares ?? 0;

  async function submit() {
    if (busy) return;
    setProblem('');
    if (selectedAccount === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(tradeDate.trim())) {
      setProblem('交易日期需为 YYYY-MM-DD');
      return;
    }
    const value = entry.byMoney ? amount : shares;
    if (value.trim() === '' || Number.isNaN(Number(value)) || Number(value) <= 0) {
      setProblem(
        `请填写${entry.byMoney ? entry.amountLabel : '转出份额'}，需为大于 0 的数字`,
      );
      return;
    }
    if (operation === 'CONVERT' && !/^\d{6}$/.test(targetCode.trim())) {
      setProblem('请填写转入基金代码，需为 6 位数字');
      return;
    }
    setBusy(true);
    try {
      await recordTrade(token, code, {
        account_id: selectedAccount,
        operation,
        trade_date: entry.pickDate ? tradeDate.trim() : localToday(),
        after_cutoff: entry.pickDate ? afterCutoff : false,
        amount: entry.byMoney ? Number(amount) : null,
        shares: entry.byMoney ? null : Number(shares),
        target_code: operation === 'CONVERT' ? targetCode.trim() : null,
        idempotency_key: crypto.randomUUID(),
      });
      onDone();
    } catch (error) {
      const message = error instanceof Error ? error.message : '下单失败';
      setProblem(
        message.includes('shares_exceed_holding')
          ? `转出份额不能超过当前持仓 ${formatNumber(held)} 份`
          : message,
      );
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

      <div className="mt-5">
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          TRADE
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          加减仓 · {detail.data?.fund_name ?? code}
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          按确认日净值定价；下单前会先算出这一笔对持仓的影响。
        </p>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(300px,0.75fr)]">
        <div className="space-y-4">
          <section className="rounded-[24px] border border-border bg-card/75 p-5">
            <p className="text-sm font-semibold text-foreground">持仓账户</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {(accounts.data ?? []).map((account) => (
                <button
                  key={account.id}
                  type="button"
                  onClick={() => setAccountId(account.id)}
                  className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
                    selectedAccount === account.id
                      ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                      : 'border-border bg-background/50 text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {account.name}
                </button>
              ))}
              {(accounts.data?.length ?? 0) === 0 && (
                <p className="text-xs text-muted-foreground">
                  还没有账户，请先在持仓页创建。
                </p>
              )}
            </div>
          </section>

          <section className="rounded-[24px] border border-border bg-card/75 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-foreground">
                  {detail.data?.fund_name ?? code}
                </p>
                <p className="mt-1 text-[11px] text-text-faint">
                  {code} · 最新净值 {formatNav(detail.data?.latest_nav)} · 当前持有{' '}
                  {formatNumber(held)} 份
                </p>
              </div>
              <span
                className={`text-sm font-medium tabular-nums ${trendClass(detail.data?.daily_return)}`}
              >
                {formatReturn(detail.data?.daily_return, { points: true })}
              </span>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {OPERATIONS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    setOperation(item.key);
                    setProblem('');
                  }}
                  className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
                    operation === item.key
                      ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                      : 'border-border bg-background/50 text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="block text-xs text-muted-foreground">
                交易日期
                <Input
                  type="date"
                  value={tradeDate}
                  disabled={!entry.pickDate}
                  onChange={(event) => setTradeDate(event.target.value)}
                  className="mt-1.5 h-10 rounded-xl bg-background/60"
                />
              </label>
              <label className="flex items-end gap-2 pb-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={afterCutoff}
                  disabled={!entry.pickDate}
                  onChange={(event) => setAfterCutoff(event.target.checked)}
                  className="size-4 accent-[#2f7057]"
                />
                15:00 后提交（顺延到下一场净值）
              </label>
              {entry.byMoney ? (
                <label className="block text-xs text-muted-foreground">
                  {entry.amountLabel}
                  <Input
                    inputMode="decimal"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    placeholder="请输入金额"
                    className="mt-1.5 h-10 rounded-xl bg-background/60"
                  />
                </label>
              ) : (
                <label className="block text-xs text-muted-foreground">
                  转出份额
                  <Input
                    inputMode="decimal"
                    value={shares}
                    onChange={(event) => setShares(event.target.value)}
                    placeholder={`当前持有 ${formatNumber(held)} 份`}
                    className="mt-1.5 h-10 rounded-xl bg-background/60"
                  />
                </label>
              )}
              {operation === 'CONVERT' && (
                <label className="block text-xs text-muted-foreground">
                  转入基金代码
                  <Input
                    inputMode="numeric"
                    value={targetCode}
                    onChange={(event) => setTargetCode(event.target.value)}
                    placeholder="6 位基金代码"
                    className="mt-1.5 h-10 rounded-xl bg-background/60"
                  />
                </label>
              )}
            </div>
            {operation === 'AUTO_INVEST' && (
              <p className="mt-3 text-[11px] text-text-faint">
                本期扣款日 {tradeDate}，按 15:00 前的净值计算。周期性排期请去
                <button
                  type="button"
                  className="ml-1 text-primary hover:underline"
                  onClick={onOpenAutoInvest}
                >
                  定投计划
                </button>
                。
              </p>
            )}
            {problem && (
              <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
                {problem}
              </p>
            )}
            <Button
              className="mt-4 h-10 w-full rounded-xl"
              disabled={busy || selectedAccount === null}
              onClick={() => void submit()}
            >
              {busy ? <RefreshCw className="animate-spin" /> : null}
              {entry.verb}
            </Button>
          </section>
        </div>

        <section className="rounded-[24px] border border-border bg-card/75 p-5">
          <p className="text-sm font-semibold text-foreground">成交预览</p>
          {!sized ? (
            <p className="mt-3 text-xs leading-6 text-muted-foreground">
              填入金额或份额后，这里会按确认日净值算出得到份额、成本与成交后持仓。
            </p>
          ) : !activePreview ? (
            <p className="mt-3 flex items-center gap-2 text-xs text-text-faint">
              <RefreshCw className="size-3.5 animate-spin text-primary" /> 计算中…
            </p>
          ) : activePreview.error ? (
            <p className="mt-3 text-xs text-destructive">{activePreview.error}</p>
          ) : activePreview.data ? (
            <div className="mt-3 space-y-3">
              <p className="text-[11px] text-text-faint">
                确认日 {activePreview.data.confirm_date}
              </p>
              {activePreview.data.legs.map((leg) => {
                const carried =
                  leg.cost_after && leg.shares_after
                    ? leg.cost_after / leg.shares_after
                    : null;
                const realized =
                  leg.direction === 'SELL'
                    ? leg.amount - (leg.cost_before - leg.cost_after)
                    : null;
                return (
                  <div
                    key={`${leg.fund_code}-${leg.direction}`}
                    className="rounded-2xl border border-border/70 bg-background/40 p-4"
                  >
                    <p className="text-xs font-medium text-foreground">
                      {leg.fund_code} {leg.direction === 'SELL' ? '转出' : '转入'}
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
                      <PreviewStat
                        label={`确认净值（${leg.confirm_nav_date}）`}
                        value={formatNav(leg.confirm_nav)}
                      />
                      <PreviewStat
                        label={entry.byMoney ? '得到份额' : '份额变动'}
                        value={`${leg.shares_delta > 0 ? '+' : ''}${formatNumber(leg.shares_delta)}`}
                      />
                      <PreviewStat
                        label={leg.direction === 'SELL' ? '到账金额' : '投入金额'}
                        value={formatMoney(leg.amount)}
                      />
                      <PreviewStat
                        label="成交后份额"
                        value={formatNumber(leg.shares_after)}
                      />
                      <PreviewStat
                        label="成交后成本"
                        value={formatMoney(leg.cost_after)}
                      />
                      <PreviewStat
                        label="成本净值"
                        value={formatNav(carried)}
                      />
                      {realized !== null && (
                        <PreviewStat
                          label="本单盈亏"
                          value={formatSignedMoney(realized)}
                          tone={trendClass(realized)}
                        />
                      )}
                    </div>
                    {leg.confirm_nav_date !== activePreview.data?.confirm_date && (
                      <p className="mt-2 text-[10px] text-text-faint">
                        {activePreview.data?.confirm_date} 当天没有净值，按最近一场{' '}
                        {leg.confirm_nav_date} 的净值算。
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function PreviewStat({
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
