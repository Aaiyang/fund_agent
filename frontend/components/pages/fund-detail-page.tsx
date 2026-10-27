'use client';

import { useState } from 'react';
import { ArrowLeft, CalendarClock, ListChecks, RefreshCw, Star } from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart as ReLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Button } from '@/components/ui/button';
import {
  type FundDetail,
  type FundHoldings,
  type FundNavPoint,
  addWatchlistFund,
  getFundDetail,
  getFundHoldings,
  getFundNav,
  removeWatchlistFund,
} from '@/lib/fund-api';
import {
  formatDate,
  formatNav,
  formatPercent,
  formatReturn,
  trendClass,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

export function FundDetailPage({
  token,
  code,
  onBack,
  onOpenNavHistory,
  onOpenPosition,
  onOpenTransactions,
  onOpenAutoInvest,
  onTrade,
  onOpenStock,
}: {
  token: string;
  code: string;
  onBack: () => void;
  onOpenNavHistory: (code: string) => void;
  onOpenPosition: (code: string) => void;
  onOpenTransactions: (code: string) => void;
  onOpenAutoInvest: () => void;
  onTrade: (code: string, operation: 'BUY' | 'SELL') => void;
  onOpenStock: (symbol: string) => void;
}) {
  const [watchlisted, setWatchlisted] = useState<boolean | null>(null);
  const [watchBusy, setWatchBusy] = useState(false);
  const detail = useResource<FundDetail>(() => getFundDetail(token, code), `${token}:${code}`);
  const nav = useResource<FundNavPoint[]>(
    () => getFundNav(token, code, '1y'),
    `${token}:${code}:nav`,
  );
  const holdings = useResource<FundHoldings>(
    () => getFundHoldings(token, code),
    `${token}:${code}:holdings`,
  );

  const fund = detail.data;
  const isWatchlisted = watchlisted ?? fund?.is_watchlisted ?? false;
  const performance = fund?.performance;

  async function toggleWatchlist() {
    setWatchBusy(true);
    try {
      if (isWatchlisted) await removeWatchlistFund(token, code);
      else await addWatchlistFund(token, code);
      setWatchlisted(!isWatchlisted);
    } finally {
      setWatchBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      {detail.loading ? (
        <p className="mt-8 flex items-center gap-2 text-sm text-text-faint">
          <RefreshCw className="size-4 animate-spin text-primary" /> 正在读基金…
        </p>
      ) : detail.error || !fund ? (
        <p className="mt-8 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-3 text-sm text-destructive">
          {detail.error || '没有找到这只基金'}
        </p>
      ) : (
        <>
          <header className="mt-5 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
                FUND DETAIL
              </p>
              <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
                {fund.fund_name}
              </h1>
              <p className="mt-1.5 text-xs text-muted-foreground">
                {fund.fund_code} · {fund.fund_type ?? '基金'}
                {fund.company ? ` · ${fund.company}` : ''}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                className="rounded-xl"
                onClick={() => onOpenPosition(code)}
              >
                同步持仓
              </Button>
              <Button
                variant="outline"
                className="rounded-xl"
                onClick={() => onTrade(code, 'BUY')}
              >
                加仓
              </Button>
              <Button
                variant="outline"
                className="rounded-xl"
                onClick={() => onTrade(code, 'SELL')}
              >
                减仓
              </Button>
              <Button
                variant="outline"
                className="rounded-xl"
                onClick={() => onOpenTransactions(code)}
              >
                <ListChecks /> 流水
              </Button>
              <Button
                variant="outline"
                className="rounded-xl"
                onClick={onOpenAutoInvest}
              >
                <CalendarClock /> 定投
              </Button>
              <Button
                variant={isWatchlisted ? 'secondary' : 'outline'}
                className="rounded-xl"
                disabled={watchBusy}
                onClick={() => void toggleWatchlist()}
              >
                <Star className={isWatchlisted ? 'fill-gold text-gold' : ''} />
                {isWatchlisted ? '已自选' : '加入自选'}
              </Button>
            </div>
          </header>

          <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(280px,0.45fr)]">
            <section className="rounded-[24px] border border-border bg-card p-5 shadow-[0_18px_40px_rgba(33,58,42,0.05)]">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="text-[11px] text-text-faint">最新单位净值</p>
                  <p className="font-display mt-1 text-4xl font-semibold text-foreground">
                    {formatNav(fund.latest_nav)}
                  </p>
                  <p
                    className={`mt-1 text-sm font-medium ${trendClass(fund.daily_return)}`}
                  >
                    {formatReturn(fund.daily_return, { points: true })} ·{' '}
                    {formatDate(fund.nav_date)}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-4 text-right text-xs text-muted-foreground sm:grid-cols-4">
                  <Stat label="累计净值" value={formatNav(fund.accumulated_nav)} />
                  <Stat label="成立" value={formatDate(fund.inception_date)} />
                  <Stat label="规模" value={fund.asset_size ?? '--'} />
                  <Stat label="经理" value={fund.manager_name ?? '--'} />
                </div>
              </div>

              <div className="mt-6 h-[280px] rounded-2xl border border-border bg-background/40 p-3">
                {nav.loading ? (
                  <p className="flex h-full items-center justify-center gap-2 text-sm text-text-faint">
                    <RefreshCw className="size-4 animate-spin text-primary" /> 正在读净值…
                  </p>
                ) : nav.error ? (
                  <p className="flex h-full items-center justify-center text-sm text-destructive">
                    {nav.error}
                  </p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <ReLineChart
                      data={nav.data ?? []}
                      margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
                    >
                      <CartesianGrid
                        stroke="rgba(43,80,56,0.08)"
                        vertical={false}
                      />
                      <XAxis
                        dataKey="nav_date"
                        tickLine={false}
                        axisLine={false}
                        minTickGap={42}
                        tick={{ fontSize: 10, fill: '#6f8577' }}
                        tickFormatter={(value: string) => value.slice(5)}
                      />
                      <YAxis
                        domain={['auto', 'auto']}
                        tickLine={false}
                        axisLine={false}
                        width={42}
                        tick={{ fontSize: 10, fill: '#6f8577' }}
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
                        formatter={(value) => [Number(value).toFixed(4), '单位净值']}
                      />
                      <Line
                        type="monotone"
                        dataKey="unit_nav"
                        stroke="#2f7057"
                        strokeWidth={2}
                        dot={false}
                      />
                    </ReLineChart>
                  </ResponsiveContainer>
                )}
              </div>
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => onOpenNavHistory(code)}
                  className="text-[11px] text-primary hover:underline"
                >
                  查看全部净值明细 ›
                </button>
              </div>
            </section>

            <section className="rounded-[24px] border border-border bg-card/70 p-5">
              <p className="text-sm font-semibold text-foreground">区间表现</p>
              <div className="mt-4 grid grid-cols-2 gap-4">
                <Stat label="近 1 月" value={formatReturn(performance?.return_1m)} tone={trendClass(performance?.return_1m)} />
                <Stat label="近 3 月" value={formatReturn(performance?.return_3m)} tone={trendClass(performance?.return_3m)} />
                <Stat label="近 6 月" value={formatReturn(performance?.return_6m)} tone={trendClass(performance?.return_6m)} />
                <Stat label="近 1 年" value={formatReturn(performance?.return_1y)} tone={trendClass(performance?.return_1y)} />
                <Stat label="近 3 年" value={formatReturn(performance?.return_3y)} tone={trendClass(performance?.return_3y)} />
                <Stat label="成立以来" value={formatReturn(performance?.return_since_inception)} tone={trendClass(performance?.return_since_inception)} />
                <Stat label="最大回撤" value={formatReturn(performance?.max_drawdown)} tone="text-down" />
                <Stat label="年化波动" value={formatPercent(performance?.annualized_volatility)} tone="text-text-soft" />
              </div>
              <p className="mt-4 text-[10px] leading-5 text-text-faint">
                单位净值变化，未做分红复权；区间指标来自后端。净值曲线默认近一年。
              </p>
            </section>
          </div>

          <section className="mt-4 rounded-[24px] border border-border bg-card/70 p-5">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-semibold text-foreground">前十大重仓</p>
              <span className="text-[10px] text-text-faint">
                {holdings.data?.quarter ?? '定期披露'}
              </span>
            </div>
            {holdings.loading ? (
              <p className="mt-4 flex items-center gap-2 text-sm text-text-faint">
                <RefreshCw className="size-4 animate-spin text-primary" /> 正在读持仓…
              </p>
            ) : holdings.error ? (
              <p className="mt-4 text-sm text-destructive">{holdings.error}</p>
            ) : (holdings.data?.items.length ?? 0) === 0 ? (
              <p className="mt-4 text-sm text-muted-foreground">
                暂无披露持仓。
              </p>
            ) : (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {holdings.data?.items.map((item) => (
                  <button
                    key={item.stock_code}
                    type="button"
                    disabled={!item.symbol}
                    onClick={() => {
                      if (item.symbol) onOpenStock(item.symbol);
                    }}
                    className="flex items-center gap-3 rounded-xl border border-border/70 bg-background/40 px-3 py-2.5 text-left transition-colors enabled:hover:border-primary/25 disabled:cursor-default"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-foreground">
                        {item.stock_name ?? item.stock_code}
                      </p>
                      <p className="mt-0.5 text-[10px] text-text-faint">
                        {item.stock_code}
                        {item.is_new ? ' · 新进' : ''}
                        {item.weight_change != null
                          ? ` · 较上季 ${item.weight_change > 0 ? '+' : ''}${item.weight_change.toFixed(2)}pp`
                          : ''}
                      </p>
                    </div>
                    <span className="text-sm font-medium tabular-nums text-foreground">
                      {item.weight != null ? `${item.weight.toFixed(2)}%` : '--'}
                    </span>
                  </button>
                ))}
              </div>
            )}
            {(holdings.data?.industries?.length ?? 0) > 0 && (
              <div className="mt-4 border-t border-border pt-3">
                <p className="text-[11px] font-medium text-foreground">行业配置</p>
                <div className="mt-2 space-y-1.5">
                  {holdings.data?.industries?.map((industry) => (
                    <div key={industry.industry} className="flex items-center gap-3">
                      <span className="w-28 shrink-0 truncate text-[10px] text-text-faint">
                        {industry.industry}
                      </span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
                        <div
                          className="h-full rounded-full bg-primary/70"
                          style={{
                            width: `${Math.min(100, Math.max(0, industry.weight ?? 0))}%`,
                          }}
                        />
                      </div>
                      <span className="w-16 text-right text-[10px] tabular-nums text-text-soft">
                        {industry.weight != null
                          ? `${industry.weight.toFixed(2)}%`
                          : '--'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}

function Stat({
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
      <p className={`mt-1 text-sm font-medium tabular-nums ${tone}`}>{value}</p>
    </div>
  );
}
