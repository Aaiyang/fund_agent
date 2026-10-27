'use client';

import { useState } from 'react';

import type { FundHoldingsBlock } from '@/lib/research-blocks';

export function FundHoldingsCard({ data }: { data: FundHoldingsBlock }) {
  const [expanded, setExpanded] = useState(false);
  const items = expanded ? data.items : data.items.slice(0, 6);

  return (
    <section className="my-4 rounded-2xl border border-border bg-card/70 p-4">
      <p className="text-sm font-semibold text-foreground">重仓股票占比</p>
      <p className="mt-0.5 text-[10px] text-text-faint">
        {data.fundCode} · 披露期 {data.reportDate}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {items.map((item) => (
          <div
            key={item.stock_code}
            className="rounded-xl border border-border/60 bg-background/40 px-3 py-2"
          >
            <p className="truncate text-xs font-medium text-foreground">
              {item.stock_name}
            </p>
            <p className="mt-0.5 text-[10px] text-text-faint">{item.stock_code}</p>
            <p className="mt-1 text-[11px] text-primary">
              占净值 {item.weight.toFixed(2)}%
            </p>
          </div>
        ))}
      </div>
      {data.items.length > 6 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-3 text-[11px] text-primary hover:underline"
        >
          {expanded ? '收起' : '查看全部'}重仓股票（{data.items.length} 只）
        </button>
      )}
      <p className="mt-2 text-[10px] leading-5 text-text-faint">
        来源：基金数据服务 · 定期披露，非实时持仓；披露权重不能直接作为涨跌贡献。
      </p>
      {data.warnings.map((warning) => (
        <p key={warning} className="mt-1 text-[10px] leading-5 text-gold">
          {warning}
        </p>
      ))}
    </section>
  );
}
