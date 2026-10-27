'use client';

import { useState } from 'react';
import { ArrowLeft, CalendarClock, Plus, RefreshCw, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type AccountItem,
  type AutoInvestPlan,
  createAutoInvestPlan,
  deleteAutoInvestPlan,
  listAccounts,
  listAutoInvestPlans,
  updateAutoInvestPlan,
} from '@/lib/fund-api';
import { formatDate, formatMoney, localToday } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

type Frequency = AutoInvestPlan['frequency'];

const FREQUENCIES: Array<{ key: Frequency; label: string; max: number | null }> = [
  { key: 'daily', label: '每天', max: null },
  { key: 'weekly', label: '每周', max: 7 },
  { key: 'biweekly', label: '每两周', max: 7 },
  { key: 'monthly', label: '每月', max: 31 },
];

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

export function AutoInvestPage({
  token,
  initialAccountId = null,
  onBack,
  onOpenFund,
}: {
  token: string;
  initialAccountId?: number | null;
  onBack: () => void;
  onOpenFund: (code: string) => void;
}) {
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const plans = useResource<{ items: AutoInvestPlan[]; settled: number }>(
    () => listAutoInvestPlans(token, accountId),
    `${token}:${accountId}:auto-invest`,
  );
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');

  async function toggle(plan: AutoInvestPlan) {
    setError('');
    try {
      await updateAutoInvestPlan(token, plan.id, { active: !plan.active });
      plans.reload();
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : '更新计划失败');
    }
  }

  async function remove(plan: AutoInvestPlan) {
    if (
      !window.confirm(
        `删除 ${plan.fund_code} 的定投计划？已经扣款的流水会保留，不会一并删除。`,
      )
    ) {
      return;
    }
    setError('');
    try {
      await deleteAutoInvestPlan(token, plan.id);
      plans.reload();
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : '删除计划失败');
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
            AUTO INVEST
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            定投计划
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            打开页面即结算到期期数；净值还没公布的那一期会留到下次。
          </p>
        </div>
        <Button
          variant="outline"
          className="rounded-xl"
          onClick={() => plans.reload()}
        >
          <RefreshCw className={plans.loading ? 'animate-spin' : ''} /> 刷新
        </Button>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setAccountId(null)}
          className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
            accountId === null
              ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
              : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
          }`}
        >
          全部账户
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

      {(plans.data?.settled ?? 0) > 0 && (
        <p className="mt-4 rounded-xl border border-primary/15 bg-primary/[0.05] px-3 py-2 text-xs text-primary">
          本次打开补记了 {plans.data?.settled} 期定投扣款。
        </p>
      )}
      {error && (
        <p className="mt-4 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
          {error}
        </p>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {plans.loading ? (
          <p className="flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读计划…
          </p>
        ) : (plans.data?.items.length ?? 0) === 0 ? (
          <div className="rounded-[24px] border border-dashed border-border bg-card/50 px-5 py-10 text-center md:col-span-2">
            <CalendarClock className="mx-auto size-7 text-text-faint" />
            <p className="mt-3 text-sm text-muted-foreground">
              还没有定投计划。先把扣款排期定下来。
            </p>
          </div>
        ) : (
          plans.data?.items.map((plan) => (
            <section
              key={plan.id}
              className={`rounded-[24px] border border-border bg-card/75 p-5 ${
                plan.active ? '' : 'opacity-60'
              }`}
            >
              <button
                type="button"
                className="text-left"
                onClick={() => onOpenFund(plan.fund_code)}
              >
                <p className="text-sm font-semibold text-foreground">
                  {plan.fund_name ?? plan.fund_code}
                </p>
                <p className="mt-1 text-[11px] text-text-faint">
                  {plan.fund_code} · {describe(plan.frequency, plan.run_day)} ·{' '}
                  {formatMoney(plan.amount)}
                </p>
              </button>
              <p className="mt-3 text-xs text-text-soft">
                {plan.active
                  ? `下期 ${formatDate(plan.next_due)}`
                  : '已暂停'}
                {plan.last_run_date
                  ? ` · 上次扣款 ${formatDate(plan.last_run_date)}`
                  : ''}
              </p>
              {plan.end_date && (
                <p className="mt-1 text-[10px] text-text-faint">
                  到 {formatDate(plan.end_date)} 止
                </p>
              )}
              <div className="mt-4 flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="flex-1 rounded-xl"
                  onClick={() => void toggle(plan)}
                >
                  {plan.active ? '暂停' : '启用'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="rounded-xl text-text-faint hover:text-destructive"
                  onClick={() => void remove(plan)}
                  aria-label={`删除 ${plan.fund_code} 定投`}
                >
                  <Trash2 />
                </Button>
              </div>
            </section>
          ))
        )}
      </div>

      <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
        <button
          type="button"
          onClick={() => setCreating((value) => !value)}
          className="flex items-center gap-2 text-sm font-semibold text-foreground"
        >
          <Plus className="size-4 text-primary" />
          {creating ? '收起新建计划' : '新建定投计划'}
        </button>
        {creating && (
          <CreatePlan
            token={token}
            accountId={accountId ?? accounts.data?.[0]?.id ?? null}
            onCreated={() => {
              setCreating(false);
              plans.reload();
            }}
          />
        )}
      </section>
    </div>
  );
}

function CreatePlan({
  token,
  accountId,
  onCreated,
}: {
  token: string;
  accountId: number | null;
  onCreated: () => void;
}) {
  const [fundCode, setFundCode] = useState('');
  const [amount, setAmount] = useState('');
  const [frequency, setFrequency] = useState<Frequency>('weekly');
  const [runDay, setRunDay] = useState('1');
  const [startDate, setStartDate] = useState(localToday());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const max = FREQUENCIES.find((entry) => entry.key === frequency)?.max ?? null;

  async function submit() {
    setProblem('');
    if (accountId === null) {
      setProblem('请先在持仓页创建账户');
      return;
    }
    if (!/^\d{6}$/.test(fundCode.trim())) {
      setProblem('基金代码需为 6 位数字');
      return;
    }
    if (!amount.trim() || Number.isNaN(Number(amount)) || Number(amount) <= 0) {
      setProblem('每期定投金额需为大于 0 的数字');
      return;
    }
    const day = max === null ? 1 : Number(runDay);
    if (max !== null && (!Number.isInteger(day) || day < 1 || day > max)) {
      setProblem(`扣款日需为 1-${max} 的整数`);
      return;
    }
    setBusy(true);
    try {
      await createAutoInvestPlan(token, {
        account_id: accountId,
        fund_code: fundCode.trim(),
        amount: Number(amount),
        frequency,
        run_day: day,
        start_date: startDate,
      });
      onCreated();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '创建计划失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 rounded-2xl border border-border/70 bg-background/40 p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-muted-foreground">
          基金代码
          <Input
            value={fundCode}
            onChange={(event) => setFundCode(event.target.value)}
            placeholder="6 位基金代码"
            className="mt-1.5 h-10 rounded-xl bg-card"
          />
        </label>
        <label className="block text-xs text-muted-foreground">
          每期定投金额
          <Input
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="请输入金额"
            className="mt-1.5 h-10 rounded-xl bg-card"
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {FREQUENCIES.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setFrequency(entry.key)}
            className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
              frequency === entry.key
                ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                : 'border-border bg-card text-muted-foreground hover:text-foreground'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {max !== null && (
          <label className="block text-xs text-muted-foreground">
            {frequency === 'monthly' ? '每月几号扣款（1-31）' : '星期几扣款（1=周一）'}
            <Input
              inputMode="numeric"
              value={runDay}
              onChange={(event) => setRunDay(event.target.value)}
              className="mt-1.5 h-10 rounded-xl bg-card"
            />
          </label>
        )}
        <label className="block text-xs text-muted-foreground">
          开始日期
          <Input
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
            className="mt-1.5 h-10 rounded-xl bg-card"
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
        {busy ? <RefreshCw className="animate-spin" /> : null} 创建计划
      </Button>
    </div>
  );
}

function describe(frequency: string, runDay: number): string {
  if (frequency === 'daily') return '每天';
  if (frequency === 'monthly') return `每月 ${runDay} 号`;
  const label =
    FREQUENCIES.find((entry) => entry.key === frequency)?.label ?? frequency;
  return `${label} ${WEEKDAYS[runDay - 1] ?? runDay}`;
}
