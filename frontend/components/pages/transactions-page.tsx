'use client';

import { useState } from 'react';
import { ArrowLeft, History, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  type AccountItem,
  type TransactionItem,
  getTransactions,
  listAccounts,
} from '@/lib/fund-api';
import { formatDate, formatMoney, formatNumber } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const TYPE_LABEL: Record<string, string> = {
  BUY: '买入',
  SELL: '卖出',
  AUTO_INVEST: '定投',
  CONVERT_IN: '转入',
  CONVERT_OUT: '转出',
  OPENING: '期初持仓',
  DIVIDEND: '分红',
  IMPORT_ADJUSTMENT: '导入修正',
  MANUAL_ADJUSTMENT: '手工修正',
};

const TRADE_TYPES = new Set([
  'BUY',
  'SELL',
  'AUTO_INVEST',
  'CONVERT_IN',
  'CONVERT_OUT',
  'OPENING',
]);

export function TransactionsPage({
  token,
  initialAccountId = null,
  fundCode = null,
  onBack,
}: {
  token: string;
  initialAccountId?: number | null;
  fundCode?: string | null;
  onBack: () => void;
}) {
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const transactions = useResource<TransactionItem[]>(
    () => getTransactions(token, accountId, fundCode),
    `${token}:${accountId}:${fundCode}`,
  );
  const accountName =
    accounts.data?.find((item) => item.id === accountId)?.name ?? '全部账户';

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8">
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
            LEDGER
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            交易与调整记录
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {fundCode ? `基金 ${fundCode}` : '全部基金'} · {accountName}
          </p>
        </div>
        <Button
          variant="outline"
          className="rounded-xl"
          onClick={() => transactions.reload()}
        >
          <RefreshCw className={transactions.loading ? 'animate-spin' : ''} /> 刷新
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

      <p className="mt-4 rounded-xl border border-border/70 bg-secondary/30 px-3 py-2 text-[11px] leading-5 text-text-soft">
        买入、定投、转换与期初持仓会累计成份额与成本；导入修正和手工修正只是快照覆盖的审计记录。
      </p>

      <section className="mt-4 overflow-hidden rounded-[24px] border border-border bg-card/75">
        {transactions.loading ? (
          <p className="flex items-center gap-2 px-5 py-8 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读流水…
          </p>
        ) : transactions.error ? (
          <p className="px-5 py-8 text-sm text-destructive">{transactions.error}</p>
        ) : (transactions.data?.length ?? 0) === 0 ? (
          <div className="px-5 py-12 text-center">
            <History className="mx-auto size-7 text-text-faint" />
            <p className="mt-3 text-sm text-muted-foreground">还没有交易记录</p>
            <p className="mt-1 text-xs text-text-faint">
              去持仓页导入或手动录入持仓后，这里会显示每一笔变化。
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-[12px]">
              <thead className="bg-secondary/45 text-[10px] text-text-faint">
                <tr>
                  <th className="px-5 py-3 font-medium">日期</th>
                  <th className="px-3 py-3 font-medium">基金</th>
                  <th className="px-3 py-3 font-medium">类型</th>
                  <th className="px-3 py-3 text-right font-medium">份额</th>
                  <th className="px-3 py-3 text-right font-medium">净值</th>
                  <th className="px-3 py-3 text-right font-medium">金额</th>
                  <th className="px-3 py-3 text-right font-medium">费用</th>
                  <th className="px-5 py-3 font-medium">来源</th>
                </tr>
              </thead>
              <tbody>
                {transactions.data?.map((item) => (
                  <tr
                    key={item.id}
                    className="border-t border-border/60 hover:bg-primary/[0.02]"
                  >
                    <td className="px-5 py-3 text-text-soft">
                      {formatDate(item.trade_date)}
                      {item.confirm_date &&
                      item.confirm_date !== item.trade_date ? (
                        <span className="ml-1 text-[10px] text-text-faint">
                          确认 {formatDate(item.confirm_date)}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3">
                      <p className="font-medium text-foreground">
                        {item.fund_name ?? item.fund_code}
                      </p>
                      <p className="mt-0.5 text-[10px] text-text-faint">
                        {item.fund_code}
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] ${
                          TRADE_TYPES.has(item.transaction_type)
                            ? 'bg-secondary text-text-soft'
                            : 'bg-gold/10 text-gold'
                        }`}
                      >
                        {TYPE_LABEL[item.transaction_type] ?? item.transaction_type}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-muted-foreground">
                      {formatNumber(item.shares)}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-muted-foreground">
                      {formatNumber(item.nav, 4)}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-foreground">
                      {formatMoney(item.amount)}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums text-text-faint">
                      {formatMoney(item.fee)}
                    </td>
                    <td className="px-5 py-3 text-[10px] text-text-faint">
                      {item.source}
                      {item.external_transaction_id
                        ? ` · ${item.external_transaction_id.slice(0, 8)}…`
                        : ''}
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
