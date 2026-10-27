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
  type FundComparisonChartRef,
  type FundComparisonSeries,
  type FundComparisonSeriesFund,
  getFundComparisonNav,
} from '@/lib/fund-api';
import { formatDate, formatPercent, formatReturn, trendClass } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const COLORS = ['#3F6E8C', '#806333', '#A35D3B'];
const PERIODS = [
  ['return_1m', '1月'],
  ['return_3m', '3月'],
  ['return_6m', '6月'],
  ['return_1y', '1年'],
] as const;

export function ComparisonCard({
  token,
  chart,
}: {
  token: string;
  chart: FundComparisonChartRef;
}) {
  const [mode, setMode] = useState<'return' | 'drawdown'>('return');
  const series = useResource<FundComparisonSeries>(
    () => getFundComparisonNav(token, chart),
    `${token}:compare:${chart.fund_codes.join(',')}:${chart.common_from}:${chart.common_to}`,
  );

  const funds = chart.funds ?? [];
  if (funds.length < 2) return null;
  const seriesFunds = (series.data?.funds ?? []).filter(
    (fund) => (fund.points?.length ?? 0) >= 2,
  );
  const names = new Map(
    seriesFunds.map((fund) => [fund.fund_code, fund.fund_name]),
  );
  const missingDrawdown = funds
    .filter((fund) => fund.observed_max_drawdown_ratio == null)
    .map((fund) => fund.fund_code);
  const drawdownFunds = seriesFunds.filter(
    (fund) => !missingDrawdown.includes(fund.fund_code),
  );
  const visible = mode === 'drawdown' ? drawdownFunds : seriesFunds;
  const rows = buildRows(visible, mode);

  return (
    <section className="mb-4 rounded-2xl border border-border bg-card/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">同期收益对比</p>
        <div className="flex gap-1 rounded-full border border-border bg-secondary/40 p-1">
          {(['return', 'drawdown'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              className={`rounded-full px-3 py-1 text-[11px] transition-colors ${
                mode === value
                  ? 'bg-card font-medium text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {value === 'return' ? '累计收益' : '回撤'}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-[10px] text-text-faint">
        共同窗口 {formatDate(chart.common_from)} 至 {formatDate(chart.common_to)} ·{' '}
        {chart.aligned_count ?? 0} 个交易日
      </p>

      <div className="mt-3 h-[240px] rounded-xl border border-border/70 bg-background/40 p-2">
        {series.loading ? (
          <p className="flex h-full items-center justify-center text-xs text-text-faint">
            正在读对比序列…
          </p>
        ) : series.error ? (
          <p className="flex h-full items-center justify-center px-3 text-center text-xs text-destructive">
            {series.error}
          </p>
        ) : visible.length < 2 && mode === 'return' ? (
          <p className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
            {series.data?.gaps?.[0] ?? '两只基金没有足够的共同交易日。'}
          </p>
        ) : visible.length === 0 ? (
          <p className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
            同窗口回撤都没有算出，切回累计收益查看对比。
          </p>
        ) : rows.length === 0 ? (
          <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
            对比数据没有对齐到同一组共同日期。
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgba(43,80,56,0.08)" vertical={false} />
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                minTickGap={40}
                tick={{ fontSize: 10, fill: '#6f8577' }}
                tickFormatter={(value: string) => value.slice(5)}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={44}
                tick={{ fontSize: 10, fill: '#6f8577' }}
                tickFormatter={(value: number) => `${value.toFixed(0)}%`}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  border: '1px solid rgba(43,80,56,.13)',
                  background: '#fffdf7',
                  fontSize: 12,
                }}
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value, name) => [
                  `${Number(value).toFixed(2)}%`,
                  String(name),
                ]}
              />
              {visible.map((fund, index) => (
                <Line
                  key={fund.fund_code}
                  type="monotone"
                  dataKey={fund.fund_code}
                  name={fund.fund_name ?? fund.fund_code}
                  stroke={COLORS[index % COLORS.length]}
                  strokeWidth={2}
                  dot={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {mode === 'drawdown' && missingDrawdown.length > 0 && (
        <p className="mt-2 text-[10px] text-gold">
          未绘制 {missingDrawdown.join('、')}：同窗口回撤未算出。
        </p>
      )}

      <div className="mt-3 space-y-2">
        {funds.map((fund, index) => (
          <div
            key={fund.fund_code}
            className="rounded-xl border border-border/60 bg-background/30 px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span
                className="size-2 rounded-full"
                style={{ background: COLORS[index % COLORS.length] }}
              />
              <span className="text-xs font-medium text-foreground">
                {names.get(fund.fund_code) ?? fund.fund_code}
              </span>
              <span className="text-[10px] text-text-faint">{fund.fund_code}</span>
              {fund.stale && (
                <span className="rounded-full bg-gold/10 px-1.5 py-0.5 text-[9px] text-gold">
                  数据可能不是最新
                </span>
              )}
            </div>
            <div className="mt-2 grid grid-cols-4 gap-2 text-[11px]">
              <Metric
                label="区间收益"
                value={formatReturn(fund.window_change_ratio)}
                tone={trendClass(fund.window_change_ratio)}
              />
              <Metric
                label="最大回撤"
                value={formatReturn(fund.observed_max_drawdown_ratio)}
                tone="text-down"
              />
              <Metric
                label="年化波动"
                value={formatPercent(fund.annualized_nav_volatility_ratio)}
              />
              <Metric label="样本" value={`${fund.aligned_count ?? 0} 天`} />
            </div>
          </div>
        ))}
      </div>

      {seriesFunds.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <p className="text-[11px] font-medium text-foreground">
            阶段收益（共同窗口内）
          </p>
          <table className="mt-1 w-full min-w-[420px] text-left text-[11px]">
            <thead className="text-[9px] text-text-faint">
              <tr>
                <th className="py-1 pr-3 font-medium">基金</th>
                {PERIODS.map(([, label]) => (
                  <th key={label} className="px-1 py-1 text-center font-medium">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seriesFunds.map((fund, index) => (
                <tr key={fund.fund_code}>
                  <td className="max-w-36 truncate py-1 pr-3 text-text-soft">
                    <span
                      className="mr-1.5 inline-block size-1.5 rounded-full"
                      style={{ background: COLORS[index % COLORS.length] }}
                    />
                    {fund.fund_name ?? fund.fund_code}
                  </td>
                  {PERIODS.map(([key]) => {
                    const value = fund.period_returns?.[key] ?? null;
                    return (
                      <td key={key} className="px-1 py-1 text-center">
                        <span
                          className={`inline-block min-w-14 rounded-md px-1.5 py-1 tabular-nums ${heatClass(value)}`}
                        >
                          {formatReturn(value)}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-2 text-[10px] leading-5 text-text-faint">
        {mode === 'drawdown'
          ? '回撤曲线为相对共同窗口内各自高点的当期回撤；数字表的「最大回撤」是窗口最低点。未算出的基金不绘制。'
          : '曲线以共同窗口首个共同净值为 0% 定基；未复权单位净值。数字表为报告时点指标，阶段收益按图表窗口重算。'}
      </p>
    </section>
  );
}

function buildRows(
  funds: FundComparisonSeriesFund[],
  mode: 'return' | 'drawdown',
): Array<Record<string, string | number>> {
  if (funds.length === 0) return [];
  const length = funds[0].points?.length ?? 0;
  if (length === 0 || funds.some((fund) => fund.points?.length !== length)) {
    return [];
  }
  return Array.from({ length }, (_, index) => {
    const row: Record<string, string | number> = {
      date: funds[0].points?.[index].nav_date ?? '',
    };
    for (const fund of funds) {
      const points = fund.points ?? [];
      if (mode === 'return') {
        row[fund.fund_code] = points[index].change_ratio * 100;
      } else {
        let peak = 1;
        for (let cursor = 0; cursor <= index; cursor += 1) {
          peak = Math.max(peak, 1 + points[cursor].change_ratio);
        }
        row[fund.fund_code] = ((1 + points[index].change_ratio) / peak - 1) * 100;
      }
    }
    return row;
  });
}

function Metric({
  label,
  value,
  tone = 'text-text-soft',
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div>
      <p className="text-[9px] text-text-faint">{label}</p>
      <p className={`mt-0.5 truncate tabular-nums ${tone}`}>{value}</p>
    </div>
  );
}

function heatClass(value: number | null): string {
  if (value == null || value === 0) return 'bg-secondary/50 text-text-faint';
  return value > 0 ? 'bg-up/10 text-up' : 'bg-down/10 text-down';
}
