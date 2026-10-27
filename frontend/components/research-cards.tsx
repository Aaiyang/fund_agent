'use client';

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
  type AllocationPreview,
  type MarketHistory,
  type MarketQuote,
  type SectorMarket,
  getAllocationPreview,
  getMarketHistory,
  getMarketQuote,
  getSectorMarket,
} from '@/lib/fund-api';
import {
  formatDate,
  formatMoney,
  formatNav,
  formatReturn,
  trendClass,
} from '@/lib/fund-format';
import type { ResearchCardBlock } from '@/lib/research-blocks';
import { useResource } from '@/lib/use-resource';

export function ResearchCard({
  token,
  card,
}: {
  token: string;
  card: ResearchCardBlock;
}) {
  if (card.kind === 'stock') return <StockCard token={token} symbol={card.symbol} />;
  if (card.kind === 'sector') {
    return (
      <SectorCard
        token={token}
        sectorCode={card.sectorCode}
        sectorType={card.sectorType}
      />
    );
  }
  return <AllocationCard token={token} card={card} />;
}

function StockCard({ token, symbol }: { token: string; symbol: string }) {
  const quote = useResource<MarketQuote>(
    () => getMarketQuote(token, symbol),
    `${token}:${symbol}:quote`,
  );
  const history = useResource<MarketHistory>(
    () => getMarketHistory(token, symbol, 'day', '1y'),
    `${token}:${symbol}:history`,
  );
  return (
    <section className="my-4 rounded-2xl border border-border bg-card/70 p-4">
      <p className="text-sm font-semibold text-foreground">股票价格走势</p>
      <p className="mt-0.5 text-[10px] text-text-faint">
        {quote.data?.name ?? symbol} · {symbol} · {quote.data?.currency ?? '币种待核验'}
      </p>
      {quote.data && (
        <div className="mt-2 flex gap-4 text-xs">
          <span className="tabular-nums text-foreground">
            最新 {formatNav(quote.data.price)}
          </span>
          <span className={`tabular-nums ${trendClass(quote.data.change_pct)}`}>
            {formatReturn(quote.data.change_pct, { points: true })}
          </span>
        </div>
      )}
      <div className="mt-3 h-[180px] rounded-xl border border-border/70 bg-background/40 p-2">
        {history.loading ? (
          <p className="flex h-full items-center justify-center text-xs text-text-faint">
            正在读价格…
          </p>
        ) : history.error ? (
          <p className="flex h-full items-center justify-center text-xs text-destructive">
            {history.error}
          </p>
        ) : (history.data?.bars.length ?? 0) < 2 ? (
          <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
            暂无足够价格历史。
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={history.data?.bars ?? []}
              margin={{ top: 6, right: 8, bottom: 0, left: 0 }}
            >
              <CartesianGrid stroke="rgba(43,80,56,0.08)" vertical={false} />
              <XAxis
                dataKey="trade_date"
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
                width={44}
                tick={{ fontSize: 9, fill: '#6f8577' }}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  border: '1px solid rgba(43,80,56,.13)',
                  background: '#fffdf7',
                  fontSize: 12,
                }}
                labelFormatter={(value) => formatDate(String(value))}
              />
              <Line
                type="monotone"
                dataKey="close"
                stroke="#2f7057"
                strokeWidth={1.8}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      <p className="mt-2 text-[10px] leading-5 text-text-faint">
        报价时间 {quote.data?.quote_time ?? '未核验'}。前复权日 K，未计股息再投资；图表随查询更新，可能与回答时不同。公开报价可能延迟。
      </p>
    </section>
  );
}

function SectorCard({
  token,
  sectorCode,
  sectorType,
}: {
  token: string;
  sectorCode: string;
  sectorType: 'industry' | 'concept';
}) {
  const sector = useResource<SectorMarket>(
    () => getSectorMarket(token, sectorCode, sectorType),
    `${token}:${sectorCode}:${sectorType}`,
  );
  const row = sector.data?.sectors.find(
    (item) =>
      item.sector_code === sectorCode && item.sector_type === sectorType,
  );
  return (
    <section className="my-4 rounded-2xl border border-border bg-card/70 p-4">
      <p className="text-sm font-semibold text-foreground">板块行情</p>
      {sector.loading ? (
        <p className="mt-2 text-xs text-text-faint">正在读板块…</p>
      ) : sector.error ? (
        <p className="mt-2 text-xs text-destructive">{sector.error}</p>
      ) : row ? (
        <>
          <p className="mt-1 text-[10px] text-text-faint">
            {row.name} · {row.sector_code} ·{' '}
            {row.sector_type === 'industry' ? '行业' : '概念'}
          </p>
          <div className="mt-2 flex gap-5 text-xs">
            <span className="tabular-nums text-foreground">
              最新点位 {formatNav(row.price)}
            </span>
            <span className={`tabular-nums ${trendClass(row.change_pct)}`}>
              {formatReturn(row.change_pct, { points: true })}
            </span>
          </div>
          <p className="mt-2 text-[10px] text-text-faint">
            报价时间 {row.quote_time ?? '未核验'}
            {row.stale ? ' · 数据可能延迟' : ''}
          </p>
        </>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">未找到对应板块。</p>
      )}
      {sector.data?.warnings.map((warning) => (
        <p key={warning} className="mt-1 text-[10px] text-gold">
          {warning}
        </p>
      ))}
    </section>
  );
}

function AllocationCard({
  token,
  card,
}: {
  token: string;
  card: Extract<ResearchCardBlock, { kind: 'allocation' }>;
}) {
  const preview = useResource<AllocationPreview>(
    () =>
      getAllocationPreview(
        token,
        card.fundCode,
        card.accountId,
        card.action,
        card.amount,
      ),
    `${token}:${card.fundCode}:${card.accountId}:${card.action}:${card.amount}`,
  );
  const scenario = preview.data?.scenario;
  const actionLabel = {
    build: '建仓',
    increase: '加仓',
    reduce: '减仓',
    exit: '清仓',
  }[card.action];
  return (
    <section className="my-4 rounded-2xl border border-border bg-card/70 p-4">
      <p className="text-sm font-semibold text-foreground">操作前后配置</p>
      <p className="mt-1 text-[10px] text-text-faint">
        {card.fundCode} ·{' '}
        {card.accountId === null ? '全部基金账户' : `账户 ${card.accountId}`} ·
        拟操作 {actionLabel} {formatMoney(card.amount)}
      </p>
      {preview.loading ? (
        <p className="mt-2 text-xs text-text-faint">正在试算…</p>
      ) : preview.error ? (
        <p className="mt-2 text-xs text-destructive">{preview.error}</p>
      ) : scenario && !scenario.available ? (
        <p className="mt-2 text-xs text-muted-foreground">
          暂不能计算操作比例：{scenario.reason ?? '数据不足'}
        </p>
      ) : scenario ? (
        <>
          {(
            [
              ['操作前', scenario.before_weight_ratio, scenario.before_target_value],
              ['操作后', scenario.after_weight_ratio, scenario.after_target_value],
            ] as const
          ).map(([label, ratio, value]) => (
            <div key={label} className="mt-3">
              <p className="text-xs text-foreground">
                {label}：{formatMoney(value)} ·{' '}
                {ratio == null ? '--' : `${(ratio * 100).toFixed(2)}%`}
              </p>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{
                    width: `${Math.min(100, Math.max(0, (ratio ?? 0) * 100))}%`,
                  }}
                />
              </div>
            </div>
          ))}
          <p className="mt-2 text-[10px] leading-5 text-text-faint">
            {scenario.assumption}
          </p>
          <p className="mt-1 text-[10px] leading-5 text-text-faint">
            基金资产：{formatMoney(scenario.before_fund_assets)} →{' '}
            {formatMoney(scenario.after_fund_assets)}。比例分母随资金进出变化，仅试算，不执行交易。
          </p>
        </>
      ) : null}
    </section>
  );
}
