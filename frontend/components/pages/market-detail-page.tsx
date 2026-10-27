'use client';

import { useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { Button } from '@/components/ui/button';
import {
  type MarketCompany,
  type MarketHistory,
  type MarketIntraday,
  type MarketQuote,
  getMarketCompany,
  getMarketHistory,
  getMarketIntraday,
  getMarketQuote,
} from '@/lib/fund-api';
import {
  formatCompact,
  formatDate,
  formatNumber,
  formatReturn,
  trendClass,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

type Mode = 'intraday' | 'fiveday' | 'day' | 'week' | 'month';

const MODES: Array<{ key: Mode; label: string }> = [
  { key: 'intraday', label: '分时' },
  { key: 'fiveday', label: '五日' },
  { key: 'day', label: '日K' },
  { key: 'week', label: '周K' },
  { key: 'month', label: '月K' },
];

export function MarketDetailPage({
  token,
  symbol,
  onBack,
}: {
  token: string;
  symbol: string;
  onBack: () => void;
}) {
  const [mode, setMode] = useState<Mode>('day');
  const quote = useResource<MarketQuote>(
    () => getMarketQuote(token, symbol),
    `${token}:${symbol}:quote`,
  );
  const company = useResource<MarketCompany>(
    () => getMarketCompany(token, symbol),
    `${token}:${symbol}:company`,
  );
  const isMinute = mode === 'intraday' || mode === 'fiveday';
  const period = isMinute ? 'day' : mode;
  const range = mode === 'month' ? '3y' : '1y';
  const history = useResource<MarketHistory | null>(
    () =>
      isMinute
        ? Promise.resolve(null)
        : getMarketHistory(token, symbol, period, range),
    `${token}:${symbol}:${period}:${range}`,
  );
  const intraday = useResource<MarketIntraday | null>(
    () =>
      isMinute
        ? getMarketIntraday(token, symbol, mode === 'fiveday' ? 5 : 1)
        : Promise.resolve(null),
    `${token}:${symbol}:${isMinute ? mode : 'off'}`,
  );

  const data = quote.data;
  const isUsd = data?.currency === 'USD' || /^us[A-Za-z]/.test(symbol);
  const modes = isUsd ? MODES.slice(2) : MODES;
  const profile = company.data?.company;
  const points = isMinute
    ? (intraday.data?.points ?? []).map((point) => ({
        label: point.time,
        value: point.price,
      }))
    : (history.data?.bars ?? []).map((bar) => ({
        label: bar.trade_date,
        value: bar.close,
      }));
  const metrics = data
    ? [
        ['成交量', data.volume == null ? null : `${formatCompact(data.volume)}${data.volume_unit ?? ''}`],
        ['成交额', data.amount == null ? null : formatCompact(data.amount)],
        ['换手率', data.turnover_rate == null ? null : `${data.turnover_rate.toFixed(2)}%`],
        ['振幅', data.amplitude == null ? null : `${data.amplitude.toFixed(2)}%`],
        ['市盈率', data.pe == null ? null : formatNumber(data.pe)],
        ['市净率', data.pb == null ? null : formatNumber(data.pb)],
        ['流通市值', data.float_market_cap == null ? null : `${formatNumber(data.float_market_cap)} 亿`],
        ['总市值', data.total_market_cap == null ? null : `${formatNumber(data.total_market_cap)} 亿`],
        ['52周高', data.week52_high == null ? null : formatNumber(data.week52_high)],
        ['52周低', data.week52_low == null ? null : formatNumber(data.week52_low)],
      ].filter((entry): entry is [string, string] => entry[1] !== null)
    : [];

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-7 sm:px-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> 返回
        </button>
        <Button
          variant="outline"
          className="rounded-xl"
          onClick={() => {
            quote.reload();
            history.reload();
            intraday.reload();
          }}
        >
          <RefreshCw
            className={
              quote.loading || history.loading || intraday.loading
                ? 'animate-spin'
                : ''
            }
          />
          刷新
        </Button>
      </div>

      <section className="mt-5 rounded-[24px] border border-border bg-card p-6 shadow-[0_18px_40px_rgba(33,58,42,0.05)]">
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          MARKET
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          {data?.name ?? symbol}
        </h1>
        <p className="mt-1 text-xs text-muted-foreground">
          {data?.listing_code ?? symbol} · {data?.kind === 'index' ? '指数' : '个股'}
          {data?.currency ? ` · ${data.currency}` : ''}
        </p>
        {quote.loading ? (
          <p className="mt-5 flex items-center gap-2 text-sm text-text-faint">
            <RefreshCw className="size-4 animate-spin text-primary" /> 正在读行情…
          </p>
        ) : quote.error ? (
          <p className="mt-5 text-sm text-destructive">{quote.error}</p>
        ) : (
          <>
            <div className="mt-4 flex flex-wrap items-baseline gap-2">
              <span className={`font-display text-4xl font-semibold tabular-nums ${trendClass(data?.change_pct)}`}>
                {formatNumber(data?.price)}
              </span>
              <span className={`text-sm tabular-nums ${trendClass(data?.change)}`}>
                {data?.change == null ? '--' : `${data.change > 0 ? '+' : ''}${data.change.toFixed(2)}`}
              </span>
              <span className={`text-sm tabular-nums ${trendClass(data?.change_pct)}`}>
                {data?.change_pct == null
                  ? '--'
                  : `${data.change_pct > 0 ? '+' : ''}${data.change_pct.toFixed(2)}%`}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['今开', data?.open],
                ['最高', data?.high],
                ['最低', data?.low],
                ['昨收', data?.prev_close],
              ].map(([label, value]) => (
                <div key={String(label)}>
                  <p className="text-[10px] text-text-faint">{label}</p>
                  <p className="mt-0.5 text-sm tabular-nums text-foreground">
                    {formatNumber(value as number | null | undefined)}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[10px] text-text-faint">
              行情时间 {data?.quote_time ?? '--'}
            </p>
          </>
        )}
      </section>

      <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1.5">
            {modes.map((entry) => (
              <button
                key={entry.key}
                type="button"
                onClick={() => setMode(entry.key)}
                className={`rounded-full border px-3 py-1 text-[11px] transition-colors ${
                  mode === entry.key
                    ? 'border-primary/25 bg-primary/[0.08] text-primary'
                    : 'border-border bg-background/50 text-muted-foreground hover:text-foreground'
                }`}
              >
                {entry.label}
              </button>
            ))}
          </div>
          {!isMinute && history.data?.period_return != null && (
            <span className={`text-xs tabular-nums ${trendClass(history.data.period_return)}`}>
              {mode === 'month' ? '近3年' : '近1年'}{' '}
              {formatReturn(history.data.period_return)}
            </span>
          )}
        </div>

        <div className="mt-3 h-[320px] rounded-2xl border border-border bg-background/40 p-3">
          {isMinute ? (
            intraday.loading ? (
              <Loading />
            ) : intraday.error ? (
              <p className="flex h-full items-center justify-center text-sm text-destructive">
                {intraday.error}
              </p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="rgba(43,80,56,0.08)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tickLine={false}
                    axisLine={false}
                    minTickGap={48}
                    tick={{ fontSize: 10, fill: '#6f8577' }}
                  />
                  <YAxis
                    domain={['auto', 'auto']}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                    tick={{ fontSize: 10, fill: '#6f8577' }}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, border: '1px solid rgba(43,80,56,.13)', background: '#fffdf7', fontSize: 12 }}
                  />
                  <Line type="monotone" dataKey="value" name="价格" stroke="#2f7057" strokeWidth={1.8} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )
          ) : history.loading ? (
            <Loading />
          ) : history.error ? (
            <p className="flex h-full items-center justify-center text-sm text-destructive">
              {history.error}
            </p>
          ) : points.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-muted-foreground">
              没有可用的 K 线数据。
            </p>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="rgba(43,80,56,0.08)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  minTickGap={48}
                  tick={{ fontSize: 10, fill: '#6f8577' }}
                  tickFormatter={(value: string) => value.slice(5)}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                  tick={{ fontSize: 10, fill: '#6f8577' }}
                />
                <Tooltip
                  contentStyle={{ borderRadius: 12, border: '1px solid rgba(43,80,56,.13)', background: '#fffdf7', fontSize: 12 }}
                  labelFormatter={(value) => formatDate(String(value))}
                />
                <Line type="monotone" dataKey="value" name="收盘" stroke="#2f7057" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {isMinute && (
          <p className="mt-2 text-[10px] text-text-faint">
            {mode === 'fiveday'
              ? `最近 5 个交易日，虚线参考${formatNumber(intraday.data?.prev_close)}（窗口前一日收盘）。`
              : `最近一个交易日的分钟线，昨收 ${formatNumber(intraday.data?.prev_close)}。`}
          </p>
        )}
      </section>

      {metrics.length > 0 && (
        <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
          <p className="text-sm font-semibold text-foreground">关键指标</p>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
            {metrics.map(([label, value]) => (
              <div key={label}>
                <p className="text-[10px] text-text-faint">{label}</p>
                <p className="mt-0.5 text-sm tabular-nums text-foreground">{value}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {profile && (
        <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
          <p className="text-sm font-semibold text-foreground">公司简介</p>
          <p className="mt-2 text-sm text-foreground">
            {profile.name ?? data?.name ?? profile.symbol}
          </p>
          <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
            {[
              ['所属行业', profile.industry],
              ['所在地区', profile.region],
              ['上市日期', profile.list_date ? formatDate(profile.list_date) : null],
              ['员工人数', profile.employees == null ? null : `${formatCompact(profile.employees)} 人`],
              ['主营业务', profile.main_business],
            ].map(([label, value]) =>
              value ? (
                <p key={String(label)} className="text-muted-foreground">
                  <span className="mr-2 text-text-faint">{label}</span>
                  <span className="text-text-soft">{value}</span>
                </p>
              ) : null,
            )}
          </div>
          {profile.description && (
            <p className="mt-3 text-xs leading-6 text-muted-foreground">{profile.description}</p>
          )}
          {(profile.concepts ?? []).length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {profile.concepts?.slice(0, 12).map((concept) => (
                <span key={concept} className="rounded-md bg-secondary px-2 py-0.5 text-[10px] text-text-soft">
                  {concept}
                </span>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function Loading() {
  return (
    <p className="flex h-full items-center justify-center gap-2 text-sm text-text-faint">
      <RefreshCw className="size-4 animate-spin text-primary" /> 正在读行情序列…
    </p>
  );
}
