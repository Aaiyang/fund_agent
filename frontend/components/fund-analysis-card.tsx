'use client';

import { useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import {
  type FundDetail,
  type FundNavPoint,
  getFundDetail,
  getFundNav,
} from '@/lib/fund-api';
import {
  formatDate,
  formatNav,
  formatPercent,
  formatReturn,
  trendClass,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const RANGES = [
  ['3m', '3月'],
  ['6m', '6月'],
  ['1y', '1年'],
] as const;

export function FundAnalysisCard({
  token,
  fundCode,
}: {
  token: string;
  fundCode: string;
}) {
  const [range, setRange] = useState<'3m' | '6m' | '1y'>('1y');
  const detail = useResource<FundDetail>(
    () => getFundDetail(token, fundCode),
    `${token}:${fundCode}:detail`,
  );
  const nav = useResource<FundNavPoint[]>(
    () => getFundNav(token, fundCode, range),
    `${token}:${fundCode}:${range}`,
  );
  const performance = detail.data?.performance;

  return (
    <section className="my-4 rounded-2xl border border-border bg-card/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-foreground">业绩走势</p>
          <p className="mt-0.5 text-[10px] text-text-faint">
            {detail.data?.fund_name ?? fundCode} · {fundCode}
          </p>
        </div>
        <div className="flex gap-1">
          {RANGES.map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setRange(value)}
              className={`rounded-full border px-2.5 py-1 text-[10px] ${
                range === value
                  ? 'border-primary/25 bg-primary/[0.08] text-primary'
                  : 'border-border bg-background/50 text-muted-foreground'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 h-[200px] rounded-xl border border-border/70 bg-background/40 p-2">
        {nav.loading ? (
          <p className="flex h-full items-center justify-center text-xs text-text-faint">
            正在读净值…
          </p>
        ) : nav.error ? (
          <p className="flex h-full items-center justify-center px-3 text-center text-xs text-destructive">
            {nav.error}
          </p>
        ) : (nav.data?.length ?? 0) < 2 ? (
          <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
            还没有足够的净值数据。
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={nav.data ?? []} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgba(43,80,56,0.08)" vertical={false} />
              <XAxis
                dataKey="nav_date"
                tickLine={false}
                axisLine={false}
                minTickGap={42}
                tick={{ fontSize: 9, fill: '#6f8577' }}
                tickFormatter={(value: string) => value.slice(5)}
              />
              <YAxis
                domain={['auto', 'auto']}
                tickLine={false}
                axisLine={false}
                width={40}
                tick={{ fontSize: 9, fill: '#6f8577' }}
                tickFormatter={(value: number) => value.toFixed(2)}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  border: '1px solid rgba(43,80,56,.13)',
                  background: '#fffdf7',
                  fontSize: 12,
                }}
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value) => [formatNav(Number(value)), '单位净值']}
              />
              <Line
                type="monotone"
                dataKey="unit_nav"
                stroke="#2f7057"
                strokeWidth={1.8}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {performance && (
        <div className="mt-3 grid grid-cols-4 gap-2 text-[10px] sm:grid-cols-8">
          {(
            [
              ['近1月', performance.return_1m],
              ['近3月', performance.return_3m],
              ['近6月', performance.return_6m],
              ['近1年', performance.return_1y],
              ['近3年', performance.return_3y],
              ['成立以来', performance.return_since_inception],
              ['最大回撤', performance.max_drawdown],
              ['年化波动', performance.annualized_volatility],
            ] as Array<[string, number | null | undefined]>
          ).map(([label, value]) => (
            <div key={label}>
              <p className="text-text-faint">{label}</p>
              <p className={`mt-0.5 tabular-nums ${trendClass(value)}`}>
                {label === '年化波动' ? formatPercent(value) : formatReturn(value)}
              </p>
            </div>
          ))}
        </div>
      )}
      <p className="mt-2 text-[10px] leading-5 text-text-faint">
        单位净值变化，未做分红复权；指标截至 {formatDate(detail.data?.nav_date)}。图表随查询更新，可能与回答时数据日期不同。
      </p>
    </section>
  );
}
